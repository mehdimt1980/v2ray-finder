"""Shared low-level network probe helpers.

Extracted from health_checker.py and xray_connectivity.py to eliminate
duplication and ensure both modules use identical probe behaviour.

Public API
----------
socks5_http_get(socks_host, socks_port, target_host, target_port, path, timeout)
    -> (success: bool, http_status: int, latency_ms: float)

http_direct_probe(host, port, path, timeout)
    -> (success: bool, http_status: int | None, latency_ms: float, error: str | None)
"""

from __future__ import annotations

import logging
import socket
import struct
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def socks5_http_get(
    socks_host: str,
    socks_port: int,
    target_host: str,
    target_port: int,
    path: str,
    timeout: float = 8.0,
) -> Tuple[bool, int, float]:
    """Send an HTTP GET through a SOCKS5 proxy (no auth).

    Performs the full SOCKS5 handshake then sends a minimal HTTP/1.1 GET
    request.  Reads only the first response line to determine the status code.

    Args:
        socks_host:  SOCKS5 proxy host (usually "127.0.0.1").
        socks_port:  SOCKS5 proxy port.
        target_host: Destination hostname (resolved by the proxy).
        target_port: Destination port.
        path:        HTTP request path (e.g. "/generate_204").
        timeout:     Socket timeout in seconds.

    Returns:
        ``(success, http_status_code, latency_ms)``
        On any failure ``success=False``, ``http_status_code=0``.
    """
    t0 = time.monotonic()
    try:
        sock = socket.create_connection((socks_host, socks_port), timeout=timeout)
        sock.settimeout(timeout)

        # --- SOCKS5 greeting (no-auth) ---
        sock.sendall(b"\x05\x01\x00")
        resp = sock.recv(2)
        if len(resp) < 2 or resp[1] != 0x00:
            sock.close()
            return False, 0, (time.monotonic() - t0) * 1000.0

        # --- SOCKS5 CONNECT request (DOMAINNAME) ---
        host_bytes = target_host.encode()
        connect_req = (
            b"\x05\x01\x00\x03"
            + bytes([len(host_bytes)])
            + host_bytes
            + struct.pack(">H", target_port)
        )
        sock.sendall(connect_req)
        conn_resp = sock.recv(10)
        if len(conn_resp) < 2 or conn_resp[1] != 0x00:
            sock.close()
            return False, 0, (time.monotonic() - t0) * 1000.0

        # --- HTTP GET ---
        http_req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {target_host}\r\n"
            "Connection: close\r\n"
            "User-Agent: v2ray-finder-probe/1.0\r\n"
            "\r\n"
        ).encode()
        sock.sendall(http_req)

        raw = b""
        while True:
            chunk = sock.recv(256)
            if not chunk:
                break
            raw += chunk
            if b"\r\n" in raw:
                break
        sock.close()

        latency = (time.monotonic() - t0) * 1000.0
        first_line = raw.split(b"\r\n")[0].decode(errors="replace")
        parts = first_line.split()
        if len(parts) >= 2:
            return True, int(parts[1]), latency
        return False, 0, latency

    except Exception as exc:
        logger.debug("SOCKS5 probe failed: %s", exc)
        return False, 0, (time.monotonic() - t0) * 1000.0


def http_direct_probe(
    host: str,
    port: int,
    path: str,
    timeout: float = 5.0,
) -> Tuple[bool, Optional[int], float, Optional[str]]:
    """Send a direct HTTP HEAD request (no proxy).

    Uses a raw socket so there are zero external dependencies and it works
    even when urllib / requests is monkey-patched in tests.

    Args:
        host:    Target hostname or IP.
        port:    Target port (usually 80).
        path:    HTTP request path.
        timeout: Socket timeout in seconds.

    Returns:
        ``(success, http_status_or_None, latency_ms, error_or_None)``
    """
    t0 = time.monotonic()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(timeout)
        request = (
            f"HEAD {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Connection: close\r\n"
            "User-Agent: v2ray-finder-probe/1.0\r\n"
            "\r\n"
        ).encode()
        sock.sendall(request)
        raw = b""
        while True:
            chunk = sock.recv(256)
            if not chunk:
                break
            raw += chunk
            if b"\r\n" in raw:
                break
        sock.close()
        latency = (time.monotonic() - t0) * 1000.0
        first_line = raw.split(b"\r\n")[0].decode(errors="replace")
        parts = first_line.split()
        if len(parts) >= 2:
            return True, int(parts[1]), latency, None
        return False, None, latency, "Malformed HTTP response"
    except socket.timeout:
        return False, None, (time.monotonic() - t0) * 1000.0, "HTTP probe timeout"
    except Exception as exc:
        return False, None, (time.monotonic() - t0) * 1000.0, str(exc)
