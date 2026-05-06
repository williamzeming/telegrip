"""Standalone entry point for the VR input bridge."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from typing import Optional

from .config import VRInputBridgeConfig
from .https_server import HTTPSServer
from .ros2_bridge import TelegripROS2Bridge
from .utils import get_preferred_local_ip
from .vr_ws_server import VRWebSocketServer

logger = logging.getLogger(__name__)


class VRInputBridgeSystem:
    """Minimal system that serves the web UI and publishes VR input into ROS 2."""

    def __init__(self, config: VRInputBridgeConfig, ros2_bridge: TelegripROS2Bridge):
        self.config = config
        self.ros2_bridge = ros2_bridge
        self.https_server = HTTPSServer(config)
        self.vr_server = VRWebSocketServer(config, ros2_bridge)

        self.https_server.set_system_ref(self)
        self.is_running = False
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None
        self.tasks: list[asyncio.Task] = []
        self._last_runtime_status = None

    def _current_vr_transport_mode(self) -> str:
        if self.vr_server and self.vr_server.clients:
            return "websocket"
        if self.vr_server and self.vr_server.has_recent_http_activity():
            return "https-fallback"
        return "waiting-for-client"

    async def _run_runtime_status_logger(self):
        while self.is_running:
            transport_mode = self._current_vr_transport_mode()
            input_rate_hz = self.ros2_bridge.get_input_rate_hz()

            if transport_mode == "waiting-for-client" and input_rate_hz == 0.0:
                status_line = "VR transport: waiting-for-client | input rate: 0.0 Hz"
            else:
                status_line = f"VR transport: {transport_mode} | input rate: {input_rate_hz:.1f} Hz"

            if status_line != self._last_runtime_status:
                logger.info(status_line)
                self._last_runtime_status = status_line

            await asyncio.sleep(2.0)

    async def start(self):
        self.ros2_bridge.start()
        self.is_running = True
        self.main_loop = asyncio.get_event_loop()

        await self.https_server.start()
        await self.vr_server.start()

        runtime_status_task = asyncio.create_task(self._run_runtime_status_logger())
        self.tasks.append(runtime_status_task)
        logger.info("VR input bridge started successfully")

        while self.is_running:
            try:
                await asyncio.gather(*self.tasks)
                break
            except asyncio.CancelledError:
                if self.is_running:
                    await asyncio.sleep(1)
                    continue
                break
            except Exception as exc:
                logger.error("Error in main task loop: %s", exc)
                break

    async def stop(self):
        logger.info("Shutting down VR input bridge...")
        self.is_running = False

        try:
            await asyncio.wait_for(self.vr_server.stop(), timeout=2.0)
        except Exception as exc:
            logger.warning("Error stopping VR server: %s", exc)

        for task in self.tasks:
            if not task.done():
                task.cancel()

        if self.tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*self.tasks, return_exceptions=True), timeout=3.0)
            except Exception as exc:
                logger.warning("Error waiting for tasks: %s", exc)

        try:
            await asyncio.wait_for(self.https_server.stop(), timeout=2.0)
        except Exception as exc:
            logger.warning("Error stopping HTTPS server: %s", exc)

        self.ros2_bridge.stop()
        logger.info("VR input bridge shutdown complete")


def create_signal_handler(system: VRInputBridgeSystem, loop: asyncio.AbstractEventLoop):
    def signal_handler(signum, frame):
        logger.info("Received signal %s, shutting down...", signum)
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(system.stop(), loop)

    return signal_handler


def parse_arguments():
    parser = argparse.ArgumentParser(description="Standalone VR input bridge with ROS 2 publishing")
    parser.add_argument("--log-level", default="warning", choices=["debug", "info", "warning", "error", "critical"])
    parser.add_argument("--https-port", type=int, default=8443, help="HTTPS server port")
    parser.add_argument("--ws-port", type=int, default=8442, help="WebSocket server port")
    parser.add_argument("--host", default="0.0.0.0", help="Host IP address")
    parser.add_argument("--cert", default="cert.pem", help="Path to SSL certificate")
    parser.add_argument("--key", default="key.pem", help="Path to SSL private key")
    parser.add_argument("--web-root", default="web-ui", help="Path to static web UI directory")
    parser.add_argument("--ros-frame-id", default="vr_world", help="ROS 2 parent frame for controller poses")
    parser.add_argument("--ros-node-name", default="telegrip_bridge", help="ROS 2 bridge node name")
    return parser.parse_args()


def create_config_from_args(args) -> VRInputBridgeConfig:
    return VRInputBridgeConfig(
        https_port=args.https_port,
        websocket_port=args.ws_port,
        host_ip=args.host,
        certfile=args.cert,
        keyfile=args.key,
        web_root=args.web_root,
        frame_id=args.ros_frame_id,
        ros_node_name=args.ros_node_name,
        log_level=args.log_level,
    )


async def main():
    args = parse_arguments()
    log_level = getattr(logging, args.log_level.upper())

    if log_level <= logging.INFO:
        logging.basicConfig(level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    else:
        logging.basicConfig(level=log_level, format="%(message)s")

    logging.getLogger("websockets").setLevel(logging.WARNING)

    config = create_config_from_args(args)
    bridge = TelegripROS2Bridge(frame_id=args.ros_frame_id, node_name=args.ros_node_name)
    bridge_outputs = bridge.get_topic_names()

    if not config.ensure_ssl_certificates():
        logger.error("Failed to ensure SSL certificates are available")
        sys.exit(1)

    if log_level <= logging.INFO:
        logger.info("Starting VR input bridge with configuration:")
        logger.info("  HTTPS Port: %s", config.https_port)
        logger.info("  WebSocket Port: %s", config.websocket_port)
        logger.info("  ROS frame_id: %s", args.ros_frame_id)
        logger.info("Published ROS 2 topics:")
        for topic_name in bridge_outputs["topics"]:
            logger.info("  %s", topic_name)
        logger.info("Published TF frames:")
        for tf_frame in bridge_outputs["tf_frames"]:
            logger.info("  %s", tf_frame)
    else:
        host_display = get_preferred_local_ip() if config.host_ip == "0.0.0.0" else config.host_ip
        print("VR input bridge starting...")
        print("Open the UI in your browser on:")
        print(f"  https://{host_display}:{config.https_port}")

    system = VRInputBridgeSystem(config, bridge)
    loop = asyncio.get_event_loop()
    signal_handler = create_signal_handler(system, loop)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await system.start()
    finally:
        try:
            await system.stop()
        except (asyncio.CancelledError, SystemExit):
            pass


def main_cli():
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nShutdown complete.")
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("Fatal error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main_cli()
