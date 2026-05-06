"""Utilities for the standalone VR input bridge package."""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import subprocess
import tempfile
from pathlib import Path

try:
    from ament_index_python.packages import get_package_share_directory
except Exception:  # pragma: no cover - available in ROS installs
    get_package_share_directory = None

logger = logging.getLogger(__name__)
PACKAGE_NAME = "vr_input_bridge"


def _is_rfc1918_address(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False

    if not isinstance(address, ipaddress.IPv4Address):
        return False

    return (
        ip.startswith("10.")
        or ip.startswith("192.168.")
        or (ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31)
    )


def get_preferred_local_ip() -> str:
    """Best-effort selection of a LAN-reachable IPv4 address."""
    candidates: list[str] = []

    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            check=False,
        )
        candidates.extend(result.stdout.split())
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None, socket.AF_INET):
            if family == socket.AF_INET:
                candidates.append(sockaddr[0])
    except Exception:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            candidates.append(sock.getsockname()[0])
    except Exception:
        pass

    seen: set[str] = set()
    filtered: list[str] = []
    for ip in candidates:
        if ip in seen:
            continue
        seen.add(ip)
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if address.is_loopback or address.is_unspecified or address.is_multicast:
            continue
        filtered.append(ip)

    for ip in filtered:
        if _is_rfc1918_address(ip):
            return ip

    if filtered:
        return filtered[0]

    return "localhost"


def get_package_root() -> Path:
    """Return the package root while working from source tree."""
    return Path(__file__).resolve().parent.parent


def get_share_directory() -> Path:
    """Return the installed ROS share directory, with source fallback."""
    if get_package_share_directory is not None:
        try:
            return Path(get_package_share_directory(PACKAGE_NAME))
        except Exception:
            pass
    return get_package_root()


def get_absolute_path(relative_path: str) -> Path:
    return get_share_directory() / relative_path


def _get_ssl_san_entries() -> list[str]:
    san_entries = ["DNS:localhost", "IP:127.0.0.1"]
    local_ip = get_preferred_local_ip()
    if local_ip != "localhost":
        san_entries.append(f"IP:{local_ip}")
    return san_entries


def _certificate_matches_expected_hosts(cert_path: Path) -> bool:
    if not cert_path.exists():
        return False

    try:
        result = subprocess.run(
            ["openssl", "x509", "-in", str(cert_path), "-text", "-noout"],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as exc:
        logger.warning("Could not inspect SSL certificate %s: %s", cert_path, exc)
        return False

    cert_text = result.stdout
    expected_entries = _get_ssl_san_entries()
    if "X509v3 Subject Alternative Name" not in cert_text:
        return False
    return all(entry in cert_text for entry in expected_entries)


def generate_ssl_certificates(cert_path: str = "cert.pem", key_path: str = "key.pem") -> bool:
    cert_abs_path = get_absolute_path(cert_path)
    key_abs_path = get_absolute_path(key_path)

    if cert_abs_path.exists() and key_abs_path.exists():
        if _certificate_matches_expected_hosts(cert_abs_path):
            logger.info("SSL certificates already exist: %s, %s", cert_abs_path, key_abs_path)
            return True

        logger.warning(
            "Existing SSL certificate does not match localhost/current LAN IP. "
            "Regenerating certificate for headset/browser access."
        )

    logger.info("SSL certificates not found, generating self-signed certificates...")

    try:
        san_entries = ",".join(_get_ssl_san_entries())
        with tempfile.TemporaryDirectory(prefix="telegrip-cert-") as temp_dir:
            temp_dir_path = Path(temp_dir)
            temp_cert_path = temp_dir_path / "cert.pem"
            temp_key_path = temp_dir_path / "key.pem"

            cmd = [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(temp_key_path),
                "-out",
                str(temp_cert_path),
                "-sha256",
                "-days",
                "365",
                "-nodes",
                "-subj",
                "/C=US/ST=Test/L=Test/O=Test/OU=Test/CN=localhost",
                "-addext",
                f"subjectAltName={san_entries}",
            ]

            subprocess.run(cmd, capture_output=True, text=True, check=True)
            cert_abs_path.write_bytes(temp_cert_path.read_bytes())
            key_abs_path.write_bytes(temp_key_path.read_bytes())

        os.chmod(key_abs_path, 0o600)
        os.chmod(cert_abs_path, 0o644)
        logger.info("SSL certificates generated successfully: %s, %s", cert_abs_path, key_abs_path)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to generate SSL certificates: %s", exc)
        logger.error("Command output: %s", exc.stderr)
        return False
    except FileNotFoundError:
        logger.error("OpenSSL not found. Please install OpenSSL to generate certificates.")
        return False


def ensure_ssl_certificates(cert_path: str = "cert.pem", key_path: str = "key.pem") -> bool:
    cert_abs_path = get_absolute_path(cert_path)
    key_abs_path = get_absolute_path(key_path)

    if cert_abs_path.exists() and key_abs_path.exists():
        if _certificate_matches_expected_hosts(cert_abs_path):
            return True

    return generate_ssl_certificates(cert_path, key_path)
