"""Standalone WebSocket server for receiving VR controller data."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from typing import Dict, Optional, Set

import websockets

from .config import VRInputBridgeConfig
from .ros2_bridge import TelegripROS2Bridge
from .utils import get_preferred_local_ip

logger = logging.getLogger(__name__)


class VRWebSocketServer:
    """WebSocket server that forwards incoming VR packets into ROS 2."""

    def __init__(self, config: VRInputBridgeConfig, ros2_bridge: TelegripROS2Bridge):
        self.config = config
        self.ros2_bridge = ros2_bridge
        self.clients: Set = set()
        self.server = None
        self.is_running = False
        self.last_http_activity_ts = 0.0
        self._browser_warning_shown = False

    def _get_local_ip(self) -> str:
        return get_preferred_local_ip()

    def setup_ssl(self) -> Optional[ssl.SSLContext]:
        if not self.config.ssl_files_exist:
            logger.info("SSL certificates not found for WebSocket server, attempting to generate them...")
            if not self.config.ensure_ssl_certificates():
                logger.error("Failed to generate SSL certificates for WebSocket server")
                return None

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            cert_path, key_path = self.config.get_absolute_ssl_paths()
            ssl_context.load_cert_chain(certfile=cert_path, keyfile=key_path)
            logger.info("SSL certificate and key loaded successfully for WebSocket server")
            return ssl_context
        except ssl.SSLError as exc:
            logger.error("Error loading SSL cert/key: %s", exc)
            return None

    async def start(self):
        ssl_context = self.setup_ssl()
        if ssl_context is None:
            logger.error("Failed to setup SSL for WebSocket server")
            return

        host = self.config.host_ip
        port = self.config.websocket_port
        self._browser_warning_shown = False

        try:
            self.server = await websockets.serve(
                self.websocket_handler,
                host,
                port,
                ssl=ssl_context,
                process_request=self._process_request,
            )
            self.is_running = True
            host_display = self._get_local_ip() if host == "0.0.0.0" else host
            logger.info("VR WebSocket server running on wss://%s:%s", host_display, port)
        except Exception as exc:
            logger.error("Failed to start WebSocket server: %s", exc)
            raise

    async def stop(self):
        self.is_running = False
        self.last_http_activity_ts = 0.0

        for client in list(self.clients):
            try:
                await client.close()
            except Exception:
                pass

        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("VR WebSocket server stopped")

    async def _process_request(self, connection, request):
        headers = request.headers
        connection_header = headers.get("Connection", "")
        upgrade_header = headers.get("Upgrade", "")

        is_websocket_request = (
            "upgrade" in connection_header.lower()
            and "websocket" in upgrade_header.lower()
        )

        if not is_websocket_request and not self._browser_warning_shown:
            self._browser_warning_shown = True
            host_display = self._get_local_ip() if self.config.host_ip == "0.0.0.0" else self.config.host_ip
            print(f"\n⚠️  Someone is trying to open port {self.config.websocket_port} in a browser.")
            print("   This port is for VR WebSocket connections only.")
            print(f"   The web UI is at: https://{host_display}:{self.config.https_port}\n")

        return None

    def mark_http_activity(self):
        self.last_http_activity_ts = time.time()

    def has_recent_http_activity(self, timeout_seconds: float = 3.0) -> bool:
        return (time.time() - self.last_http_activity_ts) < timeout_seconds

    async def websocket_handler(self, websocket, path=None):
        client_address = websocket.remote_address
        logger.info("VR client connected: %s", client_address)
        self.clients.add(websocket)

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.process_controller_data(data)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message: %s", message)
                except Exception as exc:
                    logger.error("Error processing VR data: %s", exc)
        except websockets.exceptions.ConnectionClosedOK:
            logger.info("VR client %s disconnected normally", client_address)
        except websockets.exceptions.ConnectionClosedError as exc:
            logger.warning("VR client %s disconnected with error: %s", client_address, exc)
        except Exception as exc:
            logger.error("Unexpected error with VR client %s: %s", client_address, exc)
        finally:
            self.clients.discard(websocket)
            logger.info("VR client %s cleanup complete", client_address)

    async def process_controller_data(self, data: Dict):
        """Forward raw VR JSON into ROS 2 publishers."""
        self.ros2_bridge.publish_packet(data)
