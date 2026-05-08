"""Health checker for V2Ray server configurations."""

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

# Google generate_204 endpoint — returns HTTP 204 with empty body when
# internet connectivity is present. Widely used for captive-portal detection.
_GOOGLE_204_URL = "http://connectivitycheck.gstatic.com/generate_204"
# Fallback lightweight HTTP check target
_HTTP_CHECK_URL = "http://www.gstatic.com/generate_204"


class HealthStatus(Enum):
    """Server health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    INVALID = "invalid"


@dataclass
class ServerHealth:
    """Container for server health check results."""

    config: str
    protocol: str
    status: HealthStatus
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    validation_error: Optional[str] = None
    # New: per-method results
    tcp_ok: bool = False
    http_ok: bool = False
    google_204_ok: bool = False
    check_methods: List[str] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        """Check if server is healthy."""
        return self.status == HealthStatus.HEALTHY

    @property
    def quality_score(self) -> float:
        """Calculate quality score (0-100)."""
        if self.status == HealthStatus.INVALID:
            return 0.0
        if self.status == HealthStatus.UNREACHABLE:
            return 10.0
        if self.latency_ms is None:
            return 50.0

        # Base score from latency
        if self.latency_ms < 100:
            base = 100.0
        elif self.latency_ms < 300:
            base = 100 - ((self.latency_ms - 100) * 0.2)
        else:
            base = max(30.0, 100 - (self.latency_ms * 0.15))

        # Bonus for passing additional health checks
        bonus = 0.0
        if self.http_ok:
            bonus += 5.0
        if self.google_204_ok:
            bonus += 10.0

        return min(100.0, base + bonus)


class ServerValidator:
    """Validates V2Ray server configuration strings."""

    @staticmethod
    def extract_vmess_info(config: str) -> Optional[Dict]:
        """Extract host/port from vmess config."""
        try:
            encoded = config.replace("vmess://", "")
            padding = 4 - len(encoded) % 4
            if padding != 4:
                encoded += "=" * padding
            decoded = base64.b64decode(encoded).decode("utf-8")
            data = json.loads(decoded)
            return {
                "host": data.get("add") or data.get("address"),
                "port": int(data.get("port", 0)),
                "valid": True,
            }
        except Exception as e:
            logger.debug(f"Failed to decode vmess: {e}")
            return None

    @staticmethod
    def extract_vless_info(config: str) -> Optional[Dict]:
        """Extract host/port from vless config."""
        try:
            config = config.replace("vless://", "")
            if "@" not in config:
                return None
            parts = config.split("@")[1].split("?")[0]
            host_port = parts.split(":")
            if len(host_port) != 2:
                return None
            return {"host": host_port[0], "port": int(host_port[1]), "valid": True}
        except Exception as e:
            logger.debug(f"Failed to parse vless: {e}")
            return None

    @staticmethod
    def extract_trojan_info(config: str) -> Optional[Dict]:
        """Extract host/port from trojan config."""
        try:
            config = config.replace("trojan://", "")
            if "@" not in config:
                return None
            parts = config.split("@")[1].split("?")[0]
            host_port = parts.split(":")
            if len(host_port) != 2:
                return None
            return {"host": host_port[0], "port": int(host_port[1]), "valid": True}
        except Exception as e:
            logger.debug(f"Failed to parse trojan: {e}")
            return None

    @staticmethod
    def extract_ss_info(config: str) -> Optional[Dict]:
        """Extract host/port from shadowsocks config."""
        try:
            config = config.replace("ss://", "")
            if "@" in config:
                parts = config.split("@")
                host_port = parts[1].split(":")[:2]
            else:
                try:
                    decoded = base64.b64decode(config).decode("utf-8")
                    if "@" in decoded:
                        parts = decoded.split("@")
                        host_port = parts[1].split(":")[:2]
                    else:
                        return None
                except Exception:
                    return None
            if len(host_port) != 2:
                return None
            return {"host": host_port[0], "port": int(host_port[1]), "valid": True}
        except Exception as e:
            logger.debug(f"Failed to parse ss: {e}")
            return None

    @staticmethod
    def extract_ssr_info(config: str) -> Optional[Dict]:
        """Extract host/port from ShadowsocksR config."""
        try:
            encoded = config.replace("ssr://", "").rstrip("/")
            padding = 4 - len(encoded) % 4
            if padding != 4:
                encoded += "=" * padding
            decoded = base64.b64decode(encoded).decode("utf-8", errors="replace")
            main_part = decoded.split("/?")[0].split("?")[0]
            parts = main_part.split(":")
            if len(parts) < 2:
                return None
            host = parts[0].strip()
            port = int(parts[1].strip())
            if not host or not (0 < port < 65536):
                return None
            return {"host": host, "port": port, "valid": True}
        except Exception as e:
            logger.debug(f"Failed to parse ssr: {e}")
            return None

    @classmethod
    def validate_config(
        cls, config: str
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[int]]:
        """Validate config and extract connection info.

        Returns:
            (is_valid, error_msg, host, port)
        """
        config = config.strip()

        if config.startswith("vmess://"):
            info = cls.extract_vmess_info(config)
            if info and info.get("valid"):
                return True, None, info["host"], info["port"]
            return False, "Invalid vmess format", None, None

        elif config.startswith("vless://"):
            info = cls.extract_vless_info(config)
            if info and info.get("valid"):
                return True, None, info["host"], info["port"]
            return False, "Invalid vless format", None, None

        elif config.startswith("trojan://"):
            info = cls.extract_trojan_info(config)
            if info and info.get("valid"):
                return True, None, info["host"], info["port"]
            return False, "Invalid trojan format", None, None

        elif config.startswith("ss://"):
            info = cls.extract_ss_info(config)
            if info and info.get("valid"):
                return True, None, info["host"], info["port"]
            return False, "Invalid shadowsocks format", None, None

        elif config.startswith("ssr://"):
            info = cls.extract_ssr_info(config)
            if info and info.get("valid"):
                return True, None, info["host"], info["port"]
            return False, "Invalid SSR format", None, None

        else:
            return False, "Unknown protocol", None, None


class HealthChecker:
    """Performs multi-method health checks on V2Ray servers.

    Check methods (in order, all run concurrently per server):
    1. TCP connectivity — raw socket connect to host:port
    2. HTTP reachability — lightweight HTTP GET to gstatic fallback
    3. Google 204 check — HTTP GET to connectivitycheck.gstatic.com/generate_204
                          expects HTTP 204; confirms general internet connectivity
    """

    def __init__(
        self,
        timeout: float = 5.0,
        concurrent_limit: int = 50,
        enable_google_204: bool = True,
        enable_http_check: bool = True,
    ):
        """
        Args:
            timeout: Connection timeout in seconds (applies to all check methods)
            concurrent_limit: Max concurrent checks
            enable_google_204: Whether to run Google 204 connectivity check
            enable_http_check: Whether to run HTTP-level reachability check
        """
        self.timeout = timeout
        self.concurrent_limit = concurrent_limit
        self.enable_google_204 = enable_google_204
        self.enable_http_check = enable_http_check
        self.validator = ServerValidator()

    # ------------------------------------------------------------------
    # Individual check methods
    # ------------------------------------------------------------------

    async def check_tcp_connectivity(
        self, host: str, port: int
    ) -> Tuple[bool, Optional[float], Optional[str]]:
        """Check if TCP port is reachable and measure latency.

        Returns:
            (is_reachable, latency_ms, error_msg)
        """
        if not host or not port:
            return False, None, "Missing host or port"

        start_time = time.time()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=self.timeout
            )
            latency = (time.time() - start_time) * 1000
            writer.close()
            await writer.wait_closed()
            return True, latency, None
        except asyncio.TimeoutError:
            return False, None, "TCP timeout"
        except Exception as e:
            return False, None, f"TCP failed: {str(e)}"

    async def check_google_204(
        self, session: aiohttp.ClientSession
    ) -> Tuple[bool, Optional[str]]:
        """Check internet connectivity via Google generate_204 endpoint.

        Google's generate_204 returns HTTP 204 No Content when the device
        has a working internet connection. This is the same check Android
        uses for captive portal detection.

        Returns:
            (is_ok, error_msg)
        """
        try:
            async with session.get(
                _GOOGLE_204_URL,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                allow_redirects=False,
            ) as resp:
                if resp.status == 204:
                    return True, None
                return False, f"Expected 204, got {resp.status}"
        except asyncio.TimeoutError:
            return False, "Google 204 timeout"
        except Exception as e:
            return False, f"Google 204 failed: {str(e)}"

    async def check_http_reachability(
        self, host: str, port: int, session: aiohttp.ClientSession
    ) -> Tuple[bool, Optional[str]]:
        """Attempt a lightweight HTTP GET to the server's host:port.

        We don't expect a meaningful V2Ray HTTP response — we just want
        to know if the host accepts HTTP connections at all (i.e. it is
        not firewalled). Any HTTP response (including 4xx/5xx) counts as
        reachable; only a connection error or timeout counts as failure.

        Returns:
            (is_reachable, error_msg)
        """
        url = f"http://{host}:{port}/"
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                allow_redirects=False,
            ) as resp:
                # Any HTTP response means the port is open and speaking HTTP
                _ = resp.status
                return True, None
        except asyncio.TimeoutError:
            return False, "HTTP timeout"
        except aiohttp.ClientConnectorError:
            return False, "HTTP connection refused"
        except Exception as e:
            # Some servers respond with TLS errors or garbage; that still
            # means the port is open — count it as reachable.
            err_str = str(e).lower()
            if any(kw in err_str for kw in ("ssl", "tls", "certificate", "decode", "parse")):
                return True, None
            return False, f"HTTP check failed: {str(e)}"

    # ------------------------------------------------------------------
    # Single-server orchestration
    # ------------------------------------------------------------------

    async def check_server_health(
        self,
        config: str,
        protocol: str,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> ServerHealth:
        """Perform full multi-method health check on a single server.

        The three checks run **concurrently** (via asyncio.gather) to keep
        per-server latency as low as possible.

        Args:
            config:   Server configuration string
            protocol: Protocol type (vmess, vless, etc.)
            session:  Optional shared aiohttp session (created internally if None)

        Returns:
            ServerHealth with results from all applicable check methods
        """
        # Step 1: Validate config format
        is_valid, validation_error, host, port = self.validator.validate_config(config)

        if not is_valid:
            return ServerHealth(
                config=config,
                protocol=protocol,
                status=HealthStatus.INVALID,
                validation_error=validation_error,
            )

        own_session = session is None
        if own_session:
            connector = aiohttp.TCPConnector(ssl=False)
            session = aiohttp.ClientSession(connector=connector)

        try:
            check_methods: List[str] = []
            tasks = []

            # Always run TCP check
            check_methods.append("tcp")
            tasks.append(self.check_tcp_connectivity(host, port))

            # Optional HTTP-level checks
            if self.enable_http_check and host and port:
                check_methods.append("http")
                tasks.append(self.check_http_reachability(host, port, session))

            if self.enable_google_204:
                check_methods.append("google_204")
                tasks.append(self.check_google_204(session))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Parse TCP result
            tcp_result = results[0]
            tcp_ok = False
            latency_ms = None
            tcp_error = None
            if isinstance(tcp_result, Exception):
                tcp_error = str(tcp_result)
            else:
                tcp_ok, latency_ms, tcp_error = tcp_result

            # Parse HTTP result (index 1 if enabled)
            http_ok = False
            if self.enable_http_check and "http" in check_methods:
                idx = check_methods.index("http")
                http_result = results[idx]
                if isinstance(http_result, Exception):
                    pass
                else:
                    http_ok, _ = http_result

            # Parse Google 204 result
            google_204_ok = False
            if self.enable_google_204 and "google_204" in check_methods:
                idx = check_methods.index("google_204")
                g204_result = results[idx]
                if isinstance(g204_result, Exception):
                    pass
                else:
                    google_204_ok, _ = g204_result

            # Determine overall status:
            # HEALTHY  — TCP reachable (and latency good)
            # DEGRADED — TCP reachable but high latency
            # UNREACHABLE — TCP failed
            if tcp_ok:
                status = (
                    HealthStatus.HEALTHY if (latency_ms is not None and latency_ms < 500)
                    else HealthStatus.DEGRADED
                )
            else:
                status = HealthStatus.UNREACHABLE

            return ServerHealth(
                config=config,
                protocol=protocol,
                status=status,
                latency_ms=latency_ms,
                error=tcp_error,
                host=host,
                port=port,
                tcp_ok=tcp_ok,
                http_ok=http_ok,
                google_204_ok=google_204_ok,
                check_methods=check_methods,
            )

        finally:
            if own_session:
                await session.close()

    # ------------------------------------------------------------------
    # Batch checks (shared session for efficiency)
    # ------------------------------------------------------------------

    async def check_servers_batch(
        self, servers: List[Tuple[str, str]]
    ) -> List[ServerHealth]:
        """Check multiple servers concurrently using a shared aiohttp session.

        Args:
            servers: List of (config, protocol) tuples

        Returns:
            List of ServerHealth results
        """
        semaphore = asyncio.Semaphore(self.concurrent_limit)
        connector = aiohttp.TCPConnector(ssl=False, limit=self.concurrent_limit)
        async with aiohttp.ClientSession(connector=connector) as session:

            async def check_with_semaphore(config: str, protocol: str) -> ServerHealth:
                async with semaphore:
                    return await self.check_server_health(config, protocol, session=session)

            tasks = [
                check_with_semaphore(config, protocol)
                for config, protocol in servers
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        health_results = []
        for result in results:
            if isinstance(result, ServerHealth):
                health_results.append(result)
            elif isinstance(result, Exception):
                logger.error(f"Health check failed with exception: {result}")

        return health_results

    def check_servers(
        self, servers: List[Tuple[str, str]]
    ) -> List["ServerHealth"]:
        """Synchronous wrapper for batch health checks."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            return loop.run_until_complete(self.check_servers_batch(servers))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.check_servers_batch(servers))
            finally:
                loop.close()

    # ------------------------------------------------------------------
    # Real-time single-server check (for inline/streaming use)
    # ------------------------------------------------------------------

    def check_server_now(
        self,
        config: str,
        protocol: Optional[str] = None,
    ) -> ServerHealth:
        """Synchronously health-check a **single** server immediately.

        Intended for real-time (per-server) use inside discovery pipelines
        so that a health result is available the moment a server is found,
        without waiting for a full batch to accumulate.

        Args:
            config:   Server configuration string
            protocol: Protocol string; auto-detected from config prefix if None

        Returns:
            ServerHealth instance
        """
        if protocol is None:
            protocol = config.split("://")[0] if "://" in config else "unknown"

        async def _run() -> ServerHealth:
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                return await self.check_server_health(config, protocol, session=session)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            return loop.run_until_complete(_run())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_run())
            finally:
                loop.close()


def filter_healthy_servers(
    health_results: List[ServerHealth],
    min_quality_score: float = 50.0,
    exclude_unreachable: bool = True,
) -> List[ServerHealth]:
    """Filter servers based on health criteria."""
    filtered = []
    for result in health_results:
        if result.status == HealthStatus.INVALID:
            continue
        if exclude_unreachable and result.status == HealthStatus.UNREACHABLE:
            continue
        if result.quality_score >= min_quality_score:
            filtered.append(result)
    return filtered


def sort_by_quality(
    health_results: List[ServerHealth], descending: bool = True
) -> List[ServerHealth]:
    """Sort servers by quality score."""
    return sorted(health_results, key=lambda x: x.quality_score, reverse=descending)
