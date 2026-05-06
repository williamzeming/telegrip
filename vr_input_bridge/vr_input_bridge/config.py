"""Minimal configuration for the standalone VR input bridge."""

from __future__ import annotations

from dataclasses import dataclass

from .utils import get_absolute_path, ensure_ssl_certificates


@dataclass
class VRInputBridgeConfig:
    https_port: int = 8443
    websocket_port: int = 8442
    host_ip: str = "0.0.0.0"
    certfile: str = "cert.pem"
    keyfile: str = "key.pem"
    web_root: str = "web-ui"
    frame_id: str = "vr_world"
    ros_node_name: str = "telegrip_bridge"
    log_level: str = "warning"

    @property
    def ssl_files_exist(self) -> bool:
        cert_path = get_absolute_path(self.certfile)
        key_path = get_absolute_path(self.keyfile)
        return cert_path.exists() and key_path.exists()

    def ensure_ssl_certificates(self) -> bool:
        return ensure_ssl_certificates(self.certfile, self.keyfile)

    def get_absolute_ssl_paths(self) -> tuple[str, str]:
        cert_path = str(get_absolute_path(self.certfile))
        key_path = str(get_absolute_path(self.keyfile))
        return cert_path, key_path

    def get_absolute_web_root(self) -> str:
        return str(get_absolute_path(self.web_root))
