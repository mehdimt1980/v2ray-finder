"""Multi-method health checker for v2ray server configs.

Tiered probe pipeline
---------------------
Every server goes through layers in order.  Each layer *enriches* the
ServerHealth object.  A layer is skipped only when the previous layer
already marks the server as unreachable or when the layer is explicitly
disabled.

  Layer 1 — TCP connect   (always)
      Raw asyncio socket connect to host:port.
      Measures TCP handshake latency.
      → UNREACHABLE if fails.

  Layer 2 — HTTP direct probe   (when tcp_ok=True, skippable)
      Opens a raw TCP socket to clients3.google.com:80 and sends an
      HTTP/1.1 HEAD request directly (no proxy).
      A 204 response confirms that the *runner machine* has internet.
      This is a pre-flight gate: if the machine itself is offline,
      there is no point launching xray for a full probe.
      → sets ServerHealth.http_probe_ok / http_probe_latency_ms

  Layer 3 — xray SOCKS5 / Google 204   (when xray available, opt-in)
      Spins up xray with the server’s config, then sends an HTTP GET
      through the SOCKS5 proxy to clients3.google.com/generate_204.
      A 204 confirms the *proxy server* has real internet access.
      This is the most accurate check; requires the xray binary.
      → sets ServerHealth.google_204_ok / google_204_latency_ms

Quality scoring
---------------
All layers use the same piecewise-linear latency curve (see scoring_curves.py):

    ≤100 ms   → 100
    ≤300 ms   → 100 → 70
    ≤1000 ms  → 70  → 20
    ≤3000 ms  → 20  → 0
    >3000 ms  → 0
    unreachable / INVALID → 0

When Layer 3 ran successfully its latency governs the score; otherwise
Layer 1 (TCP) latency is used.  This means a server whose proxy latency
is high scores low even if its TCP handshake was fast.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .probes import http_direct_probe as _http_direct_probe_fn
from .probes import socks5_http_get as _socks5_http_get_fn
from .scoring_curves import latency_to_score_100

logger = logging.getLogger(__name__)

_GOOGLE_204_HOST = "clients3.google.com"
_GOOGLE_204_PATH = "/generate_204"
_GOOGLE_204_PORT = 80
_GOOGLE_204_ALT_HOST = "connectivitycheck.gstatic.com"

# Maximum concurrency for Layer 3 (xray is heavy — one process per server).
_LAYER3_MAX_CONCURRENT = 5


# ---------------------------------------------------------------------------
# Shared latency → score helper (delegates to scoring_curves)
# ---------------------------------------------------------------------------


def _latency_to_score(latency_ms: float) -> float:
    """Piecewise-linear latency-to-score mapping (0–100).

    Delegates to the canonical implementation in scoring_curves.py.
    """
    return latency_to_score_100(latency_ms)


class HealthStatus(Enum):
    """Health status values for a server."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    INVALID = "invalid"


@dataclass
class ServerHealth:
    """Health information for a single server config.

    Fields populated per probe layer:

    Layer 1 (TCP):
        tcp_ok, latency_ms, error

    Layer 2 (HTTP direct):
        http_probe_ok, http_probe_latency_ms, http_probe_error

    Layer 3 (xray SOCKS5 / Google 204):
        google_204_ok, google_204_latency_ms

    probe_level records how far the pipeline ran (1, 2, or 3).
    """

    config: str
    protocol: str
    status: HealthStatus = HealthStatus.UNREACHABLE
    host: str = ""
    port: int = 0
    latency_ms: Optional[float] = None  # TCP latency
    tcp_ok: bool = False
    error: Optional[str] = None
    validation_error: Optional[str] = None

    # Layer 2 — HTTP direct probe
    http_probe_ok: bool = False
    http_probe_latency_ms: Optional[float] = None
    http_probe_error: Optional[str] = None

    # Layer 3 — xray SOCKS5 / Google 204
    google_204_ok: bool = False
    google_204_latency_ms: Optional[float] = None

    # How many layers completed (1 = TCP only, 2 = + HTTP, 3 = + xray/204)
    probe_level: int = 0

    # Source metadata (populated by pipeline / batch callers)
    source_url: str = ""
    source_trust: int = 1
    overlap_ratio: float = 0.0

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
        """Compute quality score (0-100).

        Priority:
          1. google_204_latency_ms  (most accurate — real proxy latency)
          2. latency_ms             (TCP latency fallback)
          3. INVALID / UNREACHABLE  → 0
          4. live but no latency    → 50
        """
        if self.status in (HealthStatus.INVALID, HealthStatus.UNREACHABLE):
            return 0.0
        # Prefer Layer 3 latency (real proxy round-trip)
        effective_latency = self.google_204_latency_ms or self.latency_ms
        if effective_latency is None:
            return 50.0
        return round(max(0.0, _latency_to_score(effective_latency)), 1)


# ---------------------------------------------------------------------------
# Layer 2 helper — direct HTTP probe (no proxy)
# ---------------------------------------------------------------------------


def _http_direct_probe(
    host: str = _GOOGLE_204_HOST,
    port: int = _GOOGLE_204_PORT,
    path: str = _GOOGLE_204_PATH,
    timeout: float = 5.0,
) -> Tuple[bool, Optional[int], Optional[float], Optional[str]]:
    """Thin wrapper around probes.http_direct_probe for backward compatibility."""
    return _http_direct_probe_fn(host=host, port=port, path=path, timeout=timeout)


# ---------------------------------------------------------------------------
# Layer 3 helper — SOCKS5 HTTP probe (through xray proxy)
# ---------------------------------------------------------------------------


def _socks5_http_get(
    socks_host: str,
    socks_port: int,
    target_host: str,
    target_port: int,
    path: str,
    timeout: float = 8.0,
) -> Tuple[bool, int, float]:
    """Thin wrapper around probes.socks5_http_get for backward compatibility."""
    return _socks5_http_get_fn(
        socks_host=socks_host,
        socks_port=socks_port,
        target_host=target_host,
        target_port=target_port,
        path=path,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# ServerValidator
# ---------------------------------------------------------------------------


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
            encoded = config[len("vmess://") :]
            padded = encoded + "==" * (4 - len(encoded) % 4 if len(encoded) % 4 else 0)
            try:
                data = json.loads(
                    base64.b64decode(padded).decode("utf-8", errors="replace")
                )
            except Exception:
                data = json.loads(
                    base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
                )
            host = data.get("add") or data.get("address") or ""
            port = int(data.get("port", 443))
            return {"host": host, "port": port, "raw": data}
        except Exception:
            return None

    @classmethod
    def extract_vless_info(cls, config: str) -> Optional[Dict]:
        """Parse vless:// URI and return dict with host/port, or None on failure."""
        try:
            rest = config[len("vless://") :]
            if "@" not in rest:
                return None
            addr_part = rest.split("@", 1)[1]
            addr_part = addr_part.split("?")[0].split("#")[0].split("/")[0]
            if ":" not in addr_part:
                return None
            host, port_str = addr_part.rsplit(":", 1)
            return {"host": host.strip("[]"), "port": int(port_str)}
        except (ValueError, IndexError):
            return None

    @classmethod
    def extract_trojan_info(cls, config: str) -> Optional[Dict]:
        """Parse trojan:// URI and return dict with host/port, or None on failure."""
        try:
            rest = config[len("trojan://") :]
            if "@" not in rest:
                return None
            addr_part = rest.split("@", 1)[1]
            addr_part = addr_part.split("?")[0].split("#")[0].split("/")[0]
            if ":" not in addr_part:
                return None
            host, port_str = addr_part.rsplit(":", 1)
            return {"host": host.strip("[]"), "port": int(port_str)}
        except (ValueError, IndexError):
            return None

    @classmethod
    def extract_ss_info(cls, config: str) -> Optional[Dict]:
        """Parse ss:// URI and return dict with host/port, or None on failure."""
        try:
            rest = config[len("ss://") :]
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
                    decoded = base64.urlsafe_b64decode(padded).decode(
                        "utf-8", errors="replace"
                    )
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
            encoded = config[len("ssr://") :]
            padded = encoded + "==" * (4 - len(encoded) % 4 if len(encoded) % 4 else 0)
            try:
                decoded = base64.b64decode(padded).decode("utf-8", errors="replace")
            except Exception:
                decoded = base64.urlsafe_b64decode(padded).decode(
                    "utf-8", errors="replace"
                )
            if "/?obfsparam" in decoded or "/?" in decoded:
                decoded = decoded.split("/?")[0]
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
    def validate_config(
        cls, config: str
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[int]]:
        """Full validation: return (is_valid, error_msg, host, port)."""
        if not config or not config.strip():
            return False, "Empty config", None, None
        if "://" not in config:
            return False, "Missing URI scheme", None, None
        scheme = config.split("://")[0].lower()
        if scheme not in cls.SUPPORTED_PROTOCOLS:
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


# ---------------------------------------------------------------------------
# HealthChecker
# ---------------------------------------------------------------------------


class HealthChecker:
    """High-level async health checker for v2ray server configs.

    Tiered probe pipeline:
      Layer 1 (always)         — async TCP connect
      Layer 2 (opt-in)         — direct HTTP probe to Google 204
      Layer 3 (opt-in, heavy)  — xray SOCKS5 proxy + Google 204

    Parameters
    ----------
    timeout:
        Seconds for TCP connect and HTTP probes.
    max_workers:
        Concurrency limit for TCP/HTTP checks (Layers 1–2).
    check_http_probe:
        Enable Layer 2 (direct HTTP probe to Google 204).
        Default: False.  Adds ~200-500 ms per server but confirms the
        *runner machine* has internet access before deeper checks.
    check_google_204:
        Enable Layer 3 (xray SOCKS5 proxy probe).
        Requires xray binary.  Default: False.
        Layer 3 concurrency is capped at _LAYER3_MAX_CONCURRENT (5)
        regardless of max_workers, because each check spawns an xray process.
    min_quality_score:
        Servers scoring below this threshold are excluded from batch results.
    binary_path:
        Optional explicit path to the xray binary.
    """

    def __init__(
        self,
        timeout: float = 5.0,
        max_workers: int = 50,
        check_http_probe: bool = False,
        check_google_204: bool = False,
        min_quality_score: float = 0.0,
        binary_path: Optional[str] = None,
    ) -> None:
        self.timeout = timeout
        self.max_workers = max_workers
        self.check_http_probe = check_http_probe
        self.check_google_204 = check_google_204
        self.min_quality_score = min_quality_score
        self.binary_path = binary_path

        # Shared Layer-3 checker: one instance, one port counter, one cache.
        # Only instantiated when check_google_204=True to avoid importing
        # xray_connectivity unnecessarily.
        self._layer3_checker = None
        if check_google_204:
            try:
                from .xray_connectivity import RealConnectivityChecker

                self._layer3_checker = RealConnectivityChecker(
                    timeout=timeout,
                    auto_download=False,
                    binary_path=binary_path,
                    concurrent_limit=_LAYER3_MAX_CONCURRENT,
                )
            except Exception as exc:
                logger.warning("Could not initialise Layer 3 checker: %s", exc)

    # ------------------------------------------------------------------
    # Layer 1 — TCP
    # ------------------------------------------------------------------

    async def check_tcp_connectivity(
        self, host: str, port: int
    ) -> Tuple[bool, Optional[float], Optional[str]]:
        """Async TCP connect to host:port.

        Returns (success, latency_ms_or_None, error_str_or_None).
        """
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

    # ------------------------------------------------------------------
    # Layer 2 — direct HTTP probe (run in executor to stay async)
    # ------------------------------------------------------------------

    async def _run_http_probe(
        self,
        host: str = _GOOGLE_204_HOST,
        port: int = _GOOGLE_204_PORT,
        path: str = _GOOGLE_204_PATH,
    ) -> Tuple[bool, Optional[int], Optional[float], Optional[str]]:
        """Async wrapper around _http_direct_probe."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: _http_direct_probe(host, port, path, self.timeout),
        )

    # ------------------------------------------------------------------
    # Layer 3 — xray SOCKS5 (uses shared checker)
    # ------------------------------------------------------------------

    async def _run_layer3_probe(self, config: str) -> Tuple[bool, Optional[float]]:
        """Run Layer 3 probe using the shared RealConnectivityChecker.

        Returns (google_204_ok, latency_ms_or_None).
        Uses the shared self._layer3_checker to avoid per-server port-counter
        churn and port-binding collisions under concurrency.
        """
        if self._layer3_checker is None:
            return False, None
        if not self._layer3_checker.is_xray_available():
            return False, None
        loop = asyncio.get_event_loop()
        try:
            real = await loop.run_in_executor(
                None,
                lambda: self._layer3_checker.check_server_real_sync(config),
            )
            return real.google_204_ok, real.latency_ms
        except Exception as exc:
            logger.debug("Layer 3 probe failed for %s: %s", config[:60], exc)
            return False, None

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    async def check_server_health(self, config: str, protocol: str) -> ServerHealth:
        """Run the tiered health probe on a single (config, protocol) pair.

        Always runs Layer 1 (TCP).
        Runs Layer 2 when check_http_probe=True and TCP succeeded.
        Runs Layer 3 when check_google_204=True and xray is available.
        """
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

        # --- Layer 1: TCP ---
        ok, latency, err = await self.check_tcp_connectivity(host, port)
        if not ok:
            return ServerHealth(
                config=config,
                protocol=protocol,
                status=HealthStatus.UNREACHABLE,
                host=host,
                port=port,
                error=err,
                probe_level=1,
            )

        result = ServerHealth(
            config=config,
            protocol=protocol,
            host=host,
            port=port,
            latency_ms=latency,
            tcp_ok=True,
            probe_level=1,
        )

        # --- Layer 2: direct HTTP probe ---
        if self.check_http_probe:
            http_ok, http_status, http_latency, http_err = await self._run_http_probe()
            result.http_probe_ok = http_ok and http_status in (200, 204)
            result.http_probe_latency_ms = http_latency
            result.http_probe_error = http_err
            result.probe_level = 2

        # --- Layer 3: xray SOCKS5 / Google 204 ---
        if self.check_google_204 and self._layer3_checker is not None:
            g204_ok, g204_latency = await self._run_layer3_probe(config)
            result.google_204_ok = g204_ok
            result.google_204_latency_ms = g204_latency
            result.probe_level = 3

        # Determine final status using best available latency
        effective_latency = result.google_204_latency_ms or latency or 0.0
        result.status = (
            HealthStatus.DEGRADED if effective_latency > 500 else HealthStatus.HEALTHY
        )
        return result

    # ------------------------------------------------------------------
    # Batch helpers
    # ------------------------------------------------------------------

    async def check_servers_batch(
        self, servers: List[Tuple[str, str]]
    ) -> List[ServerHealth]:
        """Check a list of (config, protocol) pairs concurrently."""
        semaphore = asyncio.Semaphore(self.max_workers)

        async def _guarded(config: str, protocol: str) -> Optional[ServerHealth]:
            async with semaphore:
                try:
                    return await self.check_server_health(config, protocol)
                except Exception:
                    return None

        tasks = [_guarded(c, p) for c, p in servers]
        results = await asyncio.gather(*tasks)
        return [r for r in results if isinstance(r, ServerHealth)]

    def check_servers(self, servers: List[Tuple[str, str]]) -> List[ServerHealth]:
        """Synchronous wrapper around check_servers_batch."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(asyncio.run, self.check_servers_batch(servers))
                return future.result()
        return asyncio.run(self.check_servers_batch(servers))

    def check_one(self, config: str) -> ServerHealth:
        """Run health check on a single config string (sync)."""
        protocol = config.split("://")[0].lower() if "://" in config else "unknown"
        results = self.check_servers([(config, protocol)])
        if results:
            return results[0]
        return ServerHealth(
            config=config, protocol=protocol, status=HealthStatus.INVALID
        )

    def check_batch(self, configs: List[str]) -> List[ServerHealth]:
        """Run health checks on a batch of config strings (sync)."""
        pairs = [
            (c, c.split("://")[0].lower() if "://" in c else "unknown") for c in configs
        ]
        return self.check_servers(pairs)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


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
