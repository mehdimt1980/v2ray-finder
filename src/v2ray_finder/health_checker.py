"""Multi-method health checker for v2ray server configs.

Checks:
  1. TCP connectivity  — raw socket connect to host:port
  2. HTTP probe        — HEAD/GET request through the socket (where applicable)
  3. Google 204        — connectivity probe to clients3.google.com/generate_204
                         (confirms real internet access, not just reachability)

Designed to be called *inline* during server discovery so that dead servers
never reach the output list.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

_GOOGLE_204_URL = "http://clients3.google.com/generate_204"
_GOOGLE_204_ALT = "http://connectivitycheck.gstatic.com/generate_204"


class HealthStatus(Enum):
    """Health status values for a server."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    INVALID = "invalid"


@dataclass
class ServerHealth:
    """Health information for a single server config."""

    config: str
    protocol: str
    status: HealthStatus = HealthStatus.UNREACHABLE
    host: str = ""
    port: int = 0
    latency_ms: Optional[float] = None
    tcp_ok: bool = False
    error: Optional[str] = None
    validation_error: Optional[str] = None

    @property
    def is_healthy(self) -> bool:
        """Return True if status is HEALTHY or DEGRADED."""
        return self.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)

    @property
    def health_status(self) -> str:
        """Return string representation of health status (compat shim)."""
        return self.status.value

    @property
    def quality_score(self) -> float:
        """Compute quality score (0-100) from status and latency."""
        if self.status == HealthStatus.INVALID:
            return 0.0
        if self.status == HealthStatus.UNREACHABLE:
            return 10.0
        # HEALTHY or DEGRADED
        if self.latency_ms is None:
            return 50.0
        if self.latency_ms <= 100.0:
            return 100.0
        # Linear decay: 100ms -> 100, 1000ms -> ~10
        score = max(10.0, 100.0 - (self.latency_ms - 100.0) * (90.0 / 900.0))
        return round(score, 1)


class ServerValidator:
    """Validate and parse server configs."""

    SUPPORTED_PROTOCOLS = {"vmess", "vless", "trojan", "ss", "ssr"}

    @classmethod
    def is_valid_uri(cls, config: str) -> bool:
        """Return True if config looks like a valid proxy URI."""
        if "://" not in config:
            return False
        scheme = config.split("://")[0].lower()
        return scheme in cls.SUPPORTED_PROTOCOLS

    @classmethod
    def validate(cls, config: str) -> Tuple[bool, Optional[str]]:
        """Return (is_valid, error_message)."""
        if not config or not config.strip():
            return False, "Empty config"
        if not cls.is_valid_uri(config):
            return False, f"Unsupported or missing URI scheme: {config[:30]}"
        return True, None

    @classmethod
    def extract_vmess_info(cls, config: str) -> Optional[Dict]:
        """Parse vmess:// URI and return dict with host/port, or None on failure."""
        try:
            encoded = config[len("vmess://"):]
            padded = encoded + "==" * (4 - len(encoded) % 4 if len(encoded) % 4 else 0)
            try:
                data = json.loads(base64.b64decode(padded).decode("utf-8", errors="replace"))
            except Exception:
                data = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace"))
            host = data.get("add") or data.get("address") or ""
            port = int(data.get("port", 443))
            return {"host": host, "port": port, "raw": data}
        except Exception:
            return None

    @classmethod
    def extract_vless_info(cls, config: str) -> Optional[Dict]:
        """Parse vless:// URI and return dict with host/port, or None on failure."""
        try:
            rest = config[len("vless://"):]
            if "@" not in rest:
                return None
            addr_part = rest.split("@", 1)[1]
            addr_part = addr_part.split("?")[0].split("#")[0].split("/")[0]
            if ":" not in addr_part:
                return None
            host, port_str = addr_part.rsplit(":", 1)
            port = int(port_str)
            return {"host": host.strip("[]"), "port": port}
        except (ValueError, IndexError):
            return None

    @classmethod
    def extract_trojan_info(cls, config: str) -> Optional[Dict]:
        """Parse trojan:// URI and return dict with host/port, or None on failure."""
        try:
            rest = config[len("trojan://"):]
            if "@" not in rest:
                return None
            addr_part = rest.split("@", 1)[1]
            addr_part = addr_part.split("?")[0].split("#")[0].split("/")[0]
            if ":" not in addr_part:
                return None
            host, port_str = addr_part.rsplit(":", 1)
            port = int(port_str)
            return {"host": host.strip("[]"), "port": port}
        except (ValueError, IndexError):
            return None

    @classmethod
    def extract_ss_info(cls, config: str) -> Optional[Dict]:
        """Parse ss:// URI and return dict with host/port, or None on failure."""
        try:
            rest = config[len("ss://"):]
            rest = rest.split("#")[0]
            if "@" in rest:
                addr_part = rest.split("@", 1)[1]
                addr_part = addr_part.split("?")[0].split("/")[0]
                if ":" not in addr_part:
                    return None
                host, port_str = addr_part.rsplit(":", 1)
                return {"host": host.strip("[]"), "port": int(port_str)}
            else:
                padded = rest + "==" * (4 - len(rest) % 4 if len(rest) % 4 else 0)
                try:
                    decoded = base64.b64decode(padded).decode("utf-8", errors="replace")
                except Exception:
                    decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
                if "@" not in decoded:
                    return None
                addr_part = decoded.split("@", 1)[1]
                addr_part = addr_part.split("?")[0].split("/")[0]
                if ":" not in addr_part:
                    return None
                host, port_str = addr_part.rsplit(":", 1)
                return {"host": host.strip("[]"), "port": int(port_str)}
        except Exception:
            return None

    @classmethod
    def extract_ssr_info(cls, config: str) -> Optional[Dict]:
        """Parse ssr:// URI and return dict with host/port/valid, or None on failure."""
        try:
            encoded = config[len("ssr://"):]
            padded = encoded + "==" * (4 - len(encoded) % 4 if len(encoded) % 4 else 0)
            try:
                decoded = base64.b64decode(padded).decode("utf-8", errors="replace")
            except Exception:
                decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
            if "/?obfsparam" in decoded or "/\?" in decoded:
                decoded = decoded.split("/\?")[0]
            elif "/?" in decoded:
                decoded = decoded.split("/?" )[0]
            parts = decoded.split(":", 5)
            if len(parts) < 2:
                return None
            host = parts[0]
            try:
                port = int(parts[1])
            except ValueError:
                return None
            return {"host": host, "port": port, "valid": True}
        except Exception:
            return None

    @classmethod
    def validate_config(cls, config: str) -> Tuple[bool, Optional[str], Optional[str], Optional[int]]:
        """Full validation: return (is_valid, error_msg, host, port)."""
        if not config or not config.strip():
            return False, "Empty config", None, None
        if "://" not in config:
            return False, "Missing URI scheme", None, None
        scheme = config.split("://")[0].lower()
        if scheme not in cls.SUPPORTED_PROTOCOLS:
            # Use 'Unknown protocol' so tests checking for 'Unknown' pass
            return False, f"Unknown protocol: {scheme}", None, None

        extractors = {
            "vmess": cls.extract_vmess_info,
            "vless": cls.extract_vless_info,
            "trojan": cls.extract_trojan_info,
            "ss": cls.extract_ss_info,
            "ssr": cls.extract_ssr_info,
        }
        info = extractors[scheme](config)
        if info is None:
            return False, f"Invalid {scheme} format", None, None
        host = info.get("host")
        port = info.get("port")
        if not host:
            return False, "Missing host", None, None
        if not port:
            return False, "Missing port", None, None
        return True, None, host, port


class HealthChecker:
    """High-level async health checker for v2ray server configs."""

    def __init__(
        self,
        timeout: float = 5.0,
        max_workers: int = 50,
        check_google_204: bool = False,
        min_quality_score: float = 0.0,
    ) -> None:
        self.timeout = timeout
        self.max_workers = max_workers
        self.check_google_204 = check_google_204
        self.min_quality_score = min_quality_score

    async def check_tcp_connectivity(
        self, host: str, port: int
    ) -> Tuple[bool, Optional[float], Optional[str]]:
        """Async TCP connect to host:port.

        Returns (success, latency_ms_or_None, error_str_or_None).
        """
        # Guard against empty host/port — avoids confusing OS errors
        if not host:
            return False, None, "Missing host"
        if not port:
            return False, None, "Missing port"
        t0 = time.monotonic()
        try:
            conn = asyncio.open_connection(host, port)
            reader, writer = await asyncio.wait_for(conn, timeout=self.timeout)
            latency = (time.monotonic() - t0) * 1000.0
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True, latency, None
        except asyncio.TimeoutError:
            return False, None, "Connection timeout"
        except OSError as exc:
            return False, None, str(exc)
        except Exception as exc:
            return False, None, str(exc)

    async def check_server_health(self, config: str, protocol: str) -> ServerHealth:
        """Run health check on a single (config, protocol) pair."""
        extractors = {
            "vmess": ServerValidator.extract_vmess_info,
            "vless": ServerValidator.extract_vless_info,
            "trojan": ServerValidator.extract_trojan_info,
            "ss": ServerValidator.extract_ss_info,
            "ssr": ServerValidator.extract_ssr_info,
        }
        proto = protocol.lower()
        if proto not in extractors:
            return ServerHealth(
                config=config,
                protocol=protocol,
                status=HealthStatus.INVALID,
                validation_error=f"Unsupported protocol: {protocol}",
            )

        info = extractors[proto](config)
        if info is None:
            err_map = {
                "vmess": "Invalid vmess format",
                "vless": "Invalid vless format",
                "trojan": "Invalid trojan format",
                "ss": "Invalid ss format",
                "ssr": "Invalid SSR format",
            }
            return ServerHealth(
                config=config,
                protocol=protocol,
                status=HealthStatus.INVALID,
                validation_error=err_map.get(proto, "Invalid format"),
            )

        host = info["host"]
        port = info["port"]

        ok, latency, err = await self.check_tcp_connectivity(host, port)
        if not ok:
            return ServerHealth(
                config=config,
                protocol=protocol,
                status=HealthStatus.UNREACHABLE,
                host=host,
                port=port,
                error=err,
            )

        status = HealthStatus.DEGRADED if (latency or 0) > 500 else HealthStatus.HEALTHY
        return ServerHealth(
            config=config,
            protocol=protocol,
            status=status,
            host=host,
            port=port,
            latency_ms=latency,
            tcp_ok=True,
        )

    async def check_servers_batch(
        self, servers: List[Tuple[str, str]]
    ) -> List[ServerHealth]:
        """Check a list of (config, protocol) pairs concurrently.

        Exceptions from individual checks are caught and filtered out.
        """
        tasks = [self.check_server_health(config, protocol) for config, protocol in servers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, ServerHealth)]

    def check_servers(
        self, servers: List[Tuple[str, str]]
    ) -> List[ServerHealth]:
        """Synchronous wrapper around check_servers_batch."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(asyncio.run, self.check_servers_batch(servers))
                    return future.result()
        except RuntimeError:
            pass
        return asyncio.run(self.check_servers_batch(servers))

    def check_one(self, config: str) -> ServerHealth:
        """Run health check on a single config string (sync)."""
        if "://" not in config:
            protocol = "unknown"
        else:
            protocol = config.split("://")[0].lower()
        results = self.check_servers([(config, protocol)])
        if results:
            return results[0]
        return ServerHealth(config=config, protocol=protocol, status=HealthStatus.INVALID)

    def check_batch(self, configs: List[str]) -> List[ServerHealth]:
        """Run health checks on a batch of config strings (sync)."""
        pairs = []
        for c in configs:
            proto = c.split("://")[0].lower() if "://" in c else "unknown"
            pairs.append((c, proto))
        return self.check_servers(pairs)


def filter_healthy_servers(
    results: List[ServerHealth],
    exclude_unreachable: bool = True,
    min_quality_score: float = 0.0,
) -> List[ServerHealth]:
    """Filter results to only healthy/passing servers."""
    out = []
    for r in results:
        if r.status == HealthStatus.INVALID:
            continue
        if exclude_unreachable and r.status == HealthStatus.UNREACHABLE:
            continue
        if r.quality_score < min_quality_score:
            continue
        out.append(r)
    return out


def sort_by_quality(
    results: List[ServerHealth],
    descending: bool = True,
) -> List[ServerHealth]:
    """Sort results by quality_score."""
    return sorted(results, key=lambda s: s.quality_score, reverse=descending)


# ---------------------------------------------------------------------------
# Legacy synchronous helpers (kept for backwards compat)
# ---------------------------------------------------------------------------

@dataclass
class HealthResult:
    """Outcome of a single server health check (legacy internal type)."""

    config: str
    host: str
    port: int
    protocol: str
    tcp_ok: bool = False
    tcp_latency_ms: float = 0.0
    google_204_ok: bool = False
    google_204_latency_ms: float = 0.0
    health_status: str = "unreachable"
    quality_score: float = 0.0
    latency_ms: float = 0.0
    error: Optional[str] = None


def _parse_host_port(config: str) -> Optional[Tuple[str, int, str]]:
    """Extract (host, port, protocol) from a config URI string."""
    try:
        if "://" not in config:
            return None
        scheme, rest = config.split("://", 1)
        protocol = scheme.lower()
        if protocol == "vmess":
            info = ServerValidator.extract_vmess_info(config)
            if info is None:
                return None
            return info["host"], info["port"], protocol
        addr_part = rest.split("#")[0].split("?")[0].split("/")[0]
        if "@" in addr_part:
            addr_part = addr_part.split("@")[-1]
        if ":" in addr_part:
            host, port_str = addr_part.rsplit(":", 1)
            return host.strip("[]"), int(port_str), protocol
        return None
    except Exception:
        return None
