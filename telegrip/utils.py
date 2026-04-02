"""
Utility functions for the teleoperation system.
"""

import ipaddress
import os
import socket
import subprocess
import logging
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
    
    # Check if certificates already exist
    if cert_abs_path.exists() and key_abs_path.exists():
        logger.info(f"SSL certificates already exist: {cert_abs_path}, {key_abs_path}")
        return True
    
    logger.info("SSL certificates not found, generating self-signed certificates...")
    
    try:
        # Generate self-signed certificate using openssl
        cmd = [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key_abs_path),
            "-out", str(cert_abs_path),
            "-sha256", "-days", "365", "-nodes",
            "-subj", "/C=US/ST=Test/L=Test/O=Test/OU=Test/CN=localhost"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
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
        logger.error("openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -sha256 -days 365 -nodes -subj \"/C=US/ST=Test/L=Test/O=Test/OU=Test/CN=localhost\"")
        return False
    
    return True 