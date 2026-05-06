"""Minimal HTTPS server for serving the VR web UI and HTTPS fallback input."""

from __future__ import annotations

import asyncio
import http.server
import json
import logging
import ssl
import threading
import urllib.parse

from .config import VRInputBridgeConfig
from .utils import get_absolute_path, get_preferred_local_ip

logger = logging.getLogger(__name__)


class APIHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the standalone VR input bridge."""

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        try:
            super().end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, ssl.SSLError):
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        request_path = urllib.parse.urlparse(self.path).path

        if request_path == "/api/status":
            self.handle_status_request()
        elif request_path == "/" or request_path == "/index.html":
            self.serve_web_file("index.html", "text/html")
        elif request_path.endswith(".css"):
            self.serve_web_file(request_path.lstrip("/"), "text/css")
        elif request_path.endswith(".js"):
            self.serve_web_file(request_path.lstrip("/"), "application/javascript")
        elif request_path.endswith(".ico"):
            self.serve_web_file(request_path.lstrip("/"), "image/x-icon")
        elif request_path.endswith((".jpg", ".jpeg")):
            self.serve_web_file(request_path.lstrip("/"), "image/jpeg")
        elif request_path.endswith(".png"):
            self.serve_web_file(request_path.lstrip("/"), "image/png")
        elif request_path.endswith(".gif"):
            self.serve_web_file(request_path.lstrip("/"), "image/gif")
        elif request_path.endswith(".webp"):
            self.serve_web_file(request_path.lstrip("/"), "image/webp")
        else:
            self.send_error(404, "Not found")

    def do_POST(self):
        request_path = urllib.parse.urlparse(self.path).path
        if request_path == "/api/vr":
            self.handle_vr_input_request()
        else:
            self.send_error(404, "Not found")

    def handle_status_request(self):
        try:
            if hasattr(self.server, "api_handler") and self.server.api_handler:
                system = self.server.api_handler
                vr_connected = False
                if system.vr_server and system.vr_server.is_running:
                    vr_connected = (
                        len(system.vr_server.clients) > 0
                        or system.vr_server.has_recent_http_activity()
                    )

                if system.vr_server and system.vr_server.clients:
                    transport_mode = "websocket"
                elif system.vr_server and system.vr_server.has_recent_http_activity():
                    transport_mode = "https-fallback"
                else:
                    transport_mode = "waiting-for-client"

                status = {
                    "vrConnected": vr_connected,
                    "transportMode": transport_mode,
                    "inputRateHz": system.ros2_bridge.get_input_rate_hz(),
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(status).encode("utf-8"))
            else:
                self.send_error(500, "System not available")
        except Exception as exc:
            logger.error("Error handling status request: %s", exc)
            self.send_error(500, str(exc))

    def handle_vr_input_request(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self.send_error(400, "No request body")
                return

            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode("utf-8"))

            if not hasattr(self.server, "api_handler") or not self.server.api_handler:
                self.send_error(500, "System not available")
                return

            system = self.server.api_handler
            if not system.vr_server or not system.main_loop:
                self.send_error(500, "VR server not available")
                return

            system.vr_server.mark_http_activity()
            future = asyncio.run_coroutine_threadsafe(
                system.vr_server.process_controller_data(data),
                system.main_loop,
            )
            future.result(timeout=1.0)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "transport": "https-fallback"}).encode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
        except Exception as exc:
            logger.error("Error handling VR input request: %s", exc)
            self.send_error(500, str(exc))

    def serve_web_file(self, filename: str, content_type: str):
        try:
            abs_path = get_absolute_path(f"web-ui/{filename}")
            with open(abs_path, "rb") as file_obj:
                file_content = file_obj.read()

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", len(file_content))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(file_content)
        except FileNotFoundError:
            self.send_error(404, f"File {filename} not found")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            logger.debug("Client disconnected while serving %s", filename)
        except Exception as exc:
            logger.error("Error serving file %s: %s", filename, exc)
            try:
                self.send_error(500, "Internal server error")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass


class HTTPSServer:
    """HTTPS server for the standalone VR input bridge."""

    def __init__(self, config: VRInputBridgeConfig):
        self.config = config
        self.httpd = None
        self.server_thread = None
        self.system_ref = None

    def set_system_ref(self, system_ref):
        self.system_ref = system_ref

    async def start(self):
        self.httpd = http.server.HTTPServer((self.config.host_ip, self.config.https_port), APIHandler)
        self.httpd.api_handler = self.system_ref

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cert_path, key_path = self.config.get_absolute_ssl_paths()
        context.load_cert_chain(cert_path, key_path)
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)

        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()

        host_display = get_preferred_local_ip() if self.config.host_ip == "0.0.0.0" else self.config.host_ip
        logger.info("HTTPS server started on https://%s:%s", host_display, self.config.https_port)

    async def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            if self.server_thread:
                self.server_thread.join(timeout=5)
            logger.info("HTTPS server stopped")
