"""
Utility functions for the teleoperation system.
"""

import ipaddress
import os
import socket
import subprocess
import logging
import tempfile
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


def _is_rfc1918_address(ip: str) -> bool:
    """Return True for common private LAN IPv4 ranges."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False

    if not isinstance(address, ipaddress.IPv4Address):
        return False

    return (
        ip.startswith("10.")
        or ip.startswith("192.168.")
        or (
            ip.startswith("172.")
            and 16 <= int(ip.split(".")[1]) <= 31
        )
    )


def get_preferred_local_ip() -> str:
    """Best-effort selection of a LAN-reachable IPv4 address."""
    candidates = []

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

    seen = set()
    filtered = []
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

def get_package_dir() -> Path:
    """
    Get the directory where the telegrip package is installed.
    This allows us to find package files regardless of current working directory.
    """
    # Get the directory containing this utils.py file
    # which is the telegrip package directory
    return Path(__file__).parent

def get_project_root() -> Path:
    """
    Get the project root directory (parent of the telegrip package).
    This is where config files, SSL certificates, web-ui, URDF, etc. should be located.
    """
    return get_package_dir().parent

def get_absolute_path(relative_path: str) -> Path:
    """
    Convert a relative path to an absolute path relative to the project root.
    
    Args:
        relative_path: Path relative to project root
        
    Returns:
        Absolute Path object
    """
    return get_project_root() / relative_path


def _get_ssl_san_entries() -> list[str]:
    """Build subjectAltName entries for localhost and the current LAN IP."""
    san_entries = ["DNS:localhost", "IP:127.0.0.1"]
    local_ip = get_preferred_local_ip()

    if local_ip != "localhost":
        san_entries.append(f"IP:{local_ip}")

    return san_entries


def _certificate_matches_expected_hosts(cert_path: Path) -> bool:
    """Return True when an existing certificate covers localhost and the current LAN IP."""
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
        logger.warning(f"Could not inspect SSL certificate {cert_path}: {exc}")
        return False

    cert_text = result.stdout
    expected_entries = _get_ssl_san_entries()

    # Require SAN coverage, since many browsers ignore CN for host validation.
    if "X509v3 Subject Alternative Name" not in cert_text:
        return False

    return all(entry in cert_text for entry in expected_entries)

def generate_ssl_certificates(cert_path: str = "cert.pem", key_path: str = "key.pem") -> bool:
    """
    Automatically generate self-signed SSL certificates if they don't exist.
    
    Args:
        cert_path: Path where to save the certificate file (relative to project root)
        key_path: Path where to save the private key file (relative to project root)
        
    Returns:
        True if certificates exist or were generated successfully, False otherwise
    """
    # Convert to absolute paths
    cert_abs_path = get_absolute_path(cert_path)
    key_abs_path = get_absolute_path(key_path)
    
    # Check if compatible certificates already exist
    if cert_abs_path.exists() and key_abs_path.exists():
        if _certificate_matches_expected_hosts(cert_abs_path):
            logger.info(f"SSL certificates already exist: {cert_abs_path}, {key_abs_path}")
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

            # Generate self-signed certificate using openssl with SAN entries.
            cmd = [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(temp_key_path),
                "-out", str(temp_cert_path),
                "-sha256", "-days", "365", "-nodes",
                "-subj", "/C=US/ST=Test/L=Test/O=Test/OU=Test/CN=localhost",
                "-addext", f"subjectAltName={san_entries}",
            ]

            subprocess.run(cmd, capture_output=True, text=True, check=True)

            cert_abs_path.write_bytes(temp_cert_path.read_bytes())
            key_abs_path.write_bytes(temp_key_path.read_bytes())

        # Set appropriate permissions (readable by owner only for security)
        os.chmod(key_abs_path, 0o600)
        os.chmod(cert_abs_path, 0o644)
        
        logger.info(f"SSL certificates generated successfully: {cert_abs_path}, {key_abs_path}")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to generate SSL certificates: {e}")
        logger.error(f"Command output: {e.stderr}")
        return False
    except FileNotFoundError:
        logger.error("OpenSSL not found. Please install OpenSSL to generate certificates.")
        logger.error("On Ubuntu/Debian: sudo apt-get install openssl")
        logger.error("On macOS: brew install openssl")
        return False
    except Exception as e:
        logger.error(f"Unexpected error generating SSL certificates: {e}")
        return False

def ensure_ssl_certificates(cert_path: str = "cert.pem", key_path: str = "key.pem") -> bool:
    """
    Ensure SSL certificates exist, generating them if necessary.
    
    Args:
        cert_path: Path to certificate file (relative to project root)
        key_path: Path to private key file (relative to project root)
        
    Returns:
        True if certificates are available, False if generation failed
    """
    if not generate_ssl_certificates(cert_path, key_path):
        logger.error("Could not ensure SSL certificates are available")
        logger.error("Manual certificate generation may be required:")
        logger.error(
            "openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem "
            "-sha256 -days 365 -nodes "
            "-subj \"/C=US/ST=Test/L=Test/O=Test/OU=Test/CN=localhost\" "
            "-addext \"subjectAltName=DNS:localhost,IP:127.0.0.1,IP:<your-lan-ip>\""
        )
        return False
    
    return True 