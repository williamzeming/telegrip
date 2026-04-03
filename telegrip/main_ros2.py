"""
ROS 2-enabled entry point for telegrip.

This launcher preserves the original telegrip behavior and adds:
- controller pose topics for RViz2
- controller TF frames
- grip/trigger state topics for downstream ROS 2 nodes
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import queue
import signal
import sys
import threading
from typing import Dict

from .config import TelegripConfig, get_config_data
from .control_loop import ControlLoop
from .inputs.vr_ws_server import VRWebSocketServer
from .inputs.web_keyboard import WebKeyboardHandler
from .main import HTTPSServer, create_signal_handler, get_local_ip
from .ros2_bridge import TelegripROS2Bridge

logger = logging.getLogger(__name__)


class ROS2VRWebSocketServer(VRWebSocketServer):
    """VR server variant that mirrors incoming controller data into ROS 2."""

    def __init__(self, command_queue: asyncio.Queue, config: TelegripConfig, ros2_bridge: TelegripROS2Bridge):
        super().__init__(command_queue, config)
        self.ros2_bridge = ros2_bridge

    async def process_controller_data(self, data: Dict):
        try:
            self.ros2_bridge.publish_packet(data)
        except Exception as exc:
            logger.error("Failed to publish VR packet to ROS 2: %s", exc)

        await super().process_controller_data(data)


class ROS2TelegripSystem:
    """Telegrip system that keeps original behavior and adds ROS 2 publishing."""

    def __init__(self, config: TelegripConfig, ros2_bridge: TelegripROS2Bridge):
        self.config = config
        self.ros2_bridge = ros2_bridge

        self.command_queue = asyncio.Queue()
        self.control_commands_queue = queue.Queue(maxsize=10)

        self.https_server = HTTPSServer(config)
        self.vr_server = ROS2VRWebSocketServer(self.command_queue, config, ros2_bridge)
        self.web_keyboard_handler = WebKeyboardHandler(self.command_queue, config)
        self.control_loop = ControlLoop(self.command_queue, config, self.control_commands_queue)

        self.https_server.set_system_ref(self)
        self.control_loop.web_keyboard_handler = self.web_keyboard_handler
        self.web_keyboard_handler.disconnect_callback = lambda: self.add_control_command("robot_disconnect")

        self.tasks = []
        self.is_running = False
        self.main_loop = None

    def add_control_command(self, action: str):
        try:
            command = {"action": action}
            logger.info("🔌 Queueing control command: %s", command)
            self.control_commands_queue.put_nowait(command)
            logger.info("🔌 Command queued successfully")
        except queue.Full:
            logger.warning("Control commands queue is full, dropping command: %s", action)
        except Exception as exc:
            logger.error("🔌 Error queuing command: %s", exc)

    def add_keypress_command(self, command: dict):
        try:
            logger.info("🎮 Queueing keypress command: %s", command)
            self.control_commands_queue.put_nowait(command)
            logger.info("🎮 Keypress command queued successfully")
        except queue.Full:
            logger.warning("Control commands queue is full, dropping keypress command: %s", command)
        except Exception as exc:
            logger.error("🎮 Error queuing keypress command: %s", exc)

    async def process_control_commands(self):
        try:
            commands_to_process = []
            while True:
                try:
                    command = self.control_commands_queue.get_nowait()
                    commands_to_process.append(command)
                except queue.Empty:
                    break

            for command in commands_to_process:
                if self.control_loop:
                    await self.control_loop._handle_command(command)
        except Exception as exc:
            logger.error("Error processing control commands: %s", exc)

    async def _run_command_processor(self):
        while self.is_running:
            await self.process_control_commands()
            await asyncio.sleep(0.05)

    def restart(self):
        def do_restart():
            try:
                logger.info("Initiating system restart...")
                if self.main_loop and not self.main_loop.is_closed():
                    future = asyncio.run_coroutine_threadsafe(self._soft_restart_sequence(), self.main_loop)
                    future.result(timeout=30.0)
                else:
                    logger.error("Main event loop not available for restart")
            except Exception as exc:
                logger.error("Error during restart: %s", exc)

        restart_thread = threading.Thread(target=do_restart, daemon=True)
        restart_thread.start()

    async def _soft_restart_sequence(self):
        try:
            logger.info("Starting soft restart sequence...")
            await asyncio.sleep(1)

            for task in self.tasks:
                task.cancel()

            if self.tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*self.tasks, return_exceptions=True),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Some tasks did not complete within timeout")

            await self.control_loop.stop()
            await self.web_keyboard_handler.stop()
            await self.vr_server.stop()
            await asyncio.sleep(1)

            _ = get_config_data()
            logger.info("Configuration reloaded from file")

            self.command_queue = asyncio.Queue()
            self.control_commands_queue = queue.Queue(maxsize=10)

            self.vr_server = ROS2VRWebSocketServer(self.command_queue, self.config, self.ros2_bridge)
            self.web_keyboard_handler = WebKeyboardHandler(self.command_queue, self.config)
            self.control_loop = ControlLoop(self.command_queue, self.config, self.control_commands_queue)

            self.control_loop.web_keyboard_handler = self.web_keyboard_handler
            self.web_keyboard_handler.disconnect_callback = lambda: self.add_control_command("robot_disconnect")

            self.tasks = []

            await self.vr_server.start()
            await self.web_keyboard_handler.start()

            control_task = asyncio.create_task(self.control_loop.start())
            self.tasks.append(control_task)

            command_processor_task = asyncio.create_task(self._run_command_processor())
            self.tasks.append(command_processor_task)

            logger.info("System restart completed successfully")

            if self.config.autoconnect and self.config.enable_robot:
                logger.info("🔌 Auto-connecting to robot motors after restart...")
                await asyncio.sleep(0.5)
                self.add_control_command("robot_connect")

        except Exception as exc:
            logger.error("Error during soft restart sequence: %s", exc)
            raise

    async def start(self):
        self.ros2_bridge.start()

        try:
            self.is_running = True
            self.main_loop = asyncio.get_event_loop()

            await self.https_server.start()
            await self.vr_server.start()
            await self.web_keyboard_handler.start()

            control_task = asyncio.create_task(self.control_loop.start())
            self.tasks.append(control_task)

            command_processor_task = asyncio.create_task(self._run_command_processor())
            self.tasks.append(command_processor_task)

            logger.info("All system components started successfully")

            if self.config.autoconnect and self.config.enable_robot:
                logger.info("🔌 Auto-connecting to robot motors...")
                await asyncio.sleep(0.5)
                self.add_control_command("robot_connect")

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

        except OSError as exc:
            if exc.errno == 98:
                logger.error("Error starting teleoperation system: %s", exc)
                logger.error("To find and kill the process using these ports, run:")
                logger.error(
                    "  kill -9 $(lsof -t -i:%s -i:%s)",
                    self.config.https_port,
                    self.config.websocket_port,
                )
            else:
                logger.error("Error starting teleoperation system: %s", exc)
            await self.stop()
            raise
        except Exception:
            await self.stop()
            raise

    async def stop(self):
        logger.info("Shutting down teleoperation system...")
        self.is_running = False

        try:
            await asyncio.wait_for(self.vr_server.stop(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning("VR server stop timed out")
        except Exception as exc:
            logger.warning("Error stopping VR server: %s", exc)

        for task in self.tasks:
            if not task.done():
                task.cancel()

        if self.tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.tasks, return_exceptions=True),
                    timeout=3.0,
                )
            except asyncio.TimeoutError:
                logger.warning("Tasks cancellation timed out")
            except Exception as exc:
                logger.warning("Error waiting for tasks: %s", exc)

        try:
            await asyncio.wait_for(self.control_loop.stop(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning("Control loop stop timed out")
        except Exception as exc:
            logger.warning("Error stopping control loop: %s", exc)

        try:
            await asyncio.wait_for(self.web_keyboard_handler.stop(), timeout=1.0)
        except asyncio.TimeoutError:
            logger.warning("Web keyboard handler stop timed out")
        except Exception as exc:
            logger.warning("Error stopping web keyboard handler: %s", exc)

        try:
            await asyncio.wait_for(self.https_server.stop(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning("HTTPS server stop timed out")
        except Exception as exc:
            logger.warning("Error stopping HTTPS server: %s", exc)

        self.ros2_bridge.stop()
        logger.info("Teleoperation system shutdown complete")


def parse_arguments():
    parser = argparse.ArgumentParser(description="Unified SO100 Robot Teleoperation System with ROS 2 publishing")

    parser.add_argument("--no-robot", action="store_true", help="Disable robot connection (visualization only)")
    parser.add_argument("--no-sim", action="store_true", help="Disable PyBullet simulation and inverse kinematics")
    parser.add_argument("--no-viz", action="store_true", help="Disable PyBullet visualization (headless mode)")
    parser.add_argument("--no-vr", action="store_true", help="Disable VR WebSocket server")
    parser.add_argument("--no-keyboard", action="store_true", help="Disable keyboard input")
    parser.add_argument("--no-https", action="store_true", help="Disable HTTPS server")
    parser.add_argument("--autoconnect", action="store_true", help="Automatically connect to robot motors on startup")
    parser.add_argument(
        "--log-level",
        default="warning",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Set logging level (default: warning)",
    )

    parser.add_argument("--https-port", type=int, default=8443, help="HTTPS server port")
    parser.add_argument("--ws-port", type=int, default=8442, help="WebSocket server port")
    parser.add_argument("--host", default="0.0.0.0", help="Host IP address")

    parser.add_argument("--urdf", default="URDF/SO100/so100.urdf", help="Path to robot URDF file")
    parser.add_argument("--webapp", default="webapp", help="Path to webapp directory")
    parser.add_argument("--cert", default="cert.pem", help="Path to SSL certificate")
    parser.add_argument("--key", default="key.pem", help="Path to SSL private key")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--left-port", help="Left arm serial port (overrides config file)")
    parser.add_argument("--right-port", help="Right arm serial port (overrides config file)")

    parser.add_argument("--ros-frame-id", default="vr_world", help="ROS 2 parent frame for controller poses")
    parser.add_argument("--ros-node-name", default="telegrip_bridge", help="ROS 2 bridge node name")

    return parser.parse_args()


def create_config_from_args(args) -> TelegripConfig:
    config_data = get_config_data()
    config = TelegripConfig()

    config.enable_robot = not args.no_robot
    config.enable_pybullet = not args.no_sim
    config.enable_pybullet_gui = config.enable_pybullet and not args.no_viz
    config.enable_vr = not args.no_vr
    config.enable_keyboard = not args.no_keyboard
    config.autoconnect = args.autoconnect
    config.log_level = args.log_level

    config.https_port = args.https_port
    config.websocket_port = args.ws_port
    config.host_ip = args.host

    config.urdf_path = args.urdf
    config.webapp_dir = args.webapp
    config.certfile = args.cert
    config.keyfile = args.key

    if args.left_port or args.right_port:
        config.follower_ports = {
            "left": args.left_port if args.left_port else config_data["robot"]["left_arm"]["port"],
            "right": args.right_port if args.right_port else config_data["robot"]["right_arm"]["port"],
        }

    return config


async def main():
    args = parse_arguments()
    log_level = getattr(logging, args.log_level.upper())

    if log_level > logging.INFO:
        os.environ["PYBULLET_SUPPRESS_CONSOLE_OUTPUT"] = "1"
        os.environ["PYBULLET_SUPPRESS_WARNINGS"] = "1"

    if log_level <= logging.INFO:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
    else:
        logging.basicConfig(level=log_level, format="%(message)s")

    logging.getLogger("websockets").setLevel(logging.WARNING)

    config = create_config_from_args(args)
    bridge = TelegripROS2Bridge(frame_id=args.ros_frame_id, node_name=args.ros_node_name)

    if not config.ensure_ssl_certificates():
        logger.error("Failed to ensure SSL certificates are available")
        sys.exit(1)

    if log_level <= logging.INFO:
        logger.info("Starting with configuration:")
        logger.info("  Robot: %s", "enabled" if config.enable_robot else "disabled")
        logger.info("  PyBullet: %s", "enabled" if config.enable_pybullet else "disabled")
        logger.info(
            "  Headless mode: %s",
            "enabled" if not config.enable_pybullet_gui and config.enable_pybullet else "disabled",
        )
        logger.info("  VR: %s", "enabled" if config.enable_vr else "disabled")
        logger.info("  Keyboard: %s", "enabled" if config.enable_keyboard else "disabled")
        logger.info("  Auto-connect: %s", "enabled" if config.autoconnect else "disabled")
        logger.info("  HTTPS Port: %s", config.https_port)
        logger.info("  WebSocket Port: %s", config.websocket_port)
        logger.info("  Robot Ports: %s", config.follower_ports)
        logger.info("  ROS frame_id: %s", args.ros_frame_id)
    else:
        host_display = get_local_ip() if config.host_ip == "0.0.0.0" else config.host_ip
        print("🤖 telegrip ROS 2 bridge starting...")
        print("📱 Open the UI in your browser on:")
        print(f"   https://{host_display}:{config.https_port}")
        print("📡 RViz2 topics:")
        print("   /telegrip/left/pose")
        print("   /telegrip/right/pose")
        print("💡 Use --log-level info to see detailed output")
        print()

    system = ROS2TelegripSystem(config, bridge)

    loop = asyncio.get_event_loop()
    signal_handler = create_signal_handler(system, loop)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await system.start()
    except (KeyboardInterrupt, SystemExit):
        if log_level <= logging.INFO:
            logger.info("Received interrupt signal")
        else:
            print("\n🛑 Shutting down...")
    except asyncio.CancelledError:
        if log_level <= logging.INFO:
            logger.info("System tasks cancelled")
    except Exception as exc:
        if log_level <= logging.INFO:
            logger.error("System error: %s", exc)
        else:
            print(f"❌ Error: {exc}")
    finally:
        try:
            await system.stop()
        except (asyncio.CancelledError, SystemExit):
            pass

        def ignore_ssl_errors(loop_obj, context):
            if "exception" in context:
                exc = context["exception"]
                if isinstance(exc, (OSError, RuntimeError)):
                    return
            loop_obj.default_exception_handler(context)

        loop.set_exception_handler(ignore_ssl_errors)

        if log_level > logging.INFO:
            print("✅ Shutdown complete.")


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
