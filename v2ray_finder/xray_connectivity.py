"""Probe real internet connectivity through a running xray SOCKS5 proxy.

This is the *real* health check: we spin up xray with the server's config,
then send an HTTP request through the SOCKS5 proxy to Google's generate_204
endpoint.  A 204 response means the proxy is alive and has internet access.

All heavy lifting is done by :class:`RealConnectivityChecker`.
For batch use, call :func:`check_real_connectivity_batch`.

Quality scoring methodology
---------------------------
We use a piecewise-linear latency curve that mirrors real-world UX thresholds,
the same approach used by v2rayA and hiddify-next:

    ≤100 ms   → 100   (excellent)
    ≤300 ms   → 100→70 (good)
    ≤1000 ms  → 70→20  (acceptable → poor)
    ≤3000 ms  → 20→0   (poor → floor)
    >3000 ms  → 0      (hard floor)
    unreachable/None → 0

Curve is defined once in :mod:`scoring_curves` and imported here.
SOCKS5 probe logic lives in :mod:`probes` and is imported here.

Retry policy (V1-D4)
--------------------
:func:`check_one` retries **once** with a fresh free port when xray fails to
start (port contention, flaky binary, etc.).  The retry uses :func:`find_free_port`
so it is unlikely to collide with the original port.  Note: a small TOCTOU
race exists between :func:`find_free_port` and the actual bind; this is
unavoidable without OS-level SO_REUSEPORT and is documented here rather than
silently ignored.  Both attempts are logged at ``DEBUG`` level.
On retry success ``retried=True`` is set on the returned result.
If the retry also fails, **both** the original and retry errors are included
in ``result.error``, and ``retried=True`` is still set.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .probes import socks5_http_get as _socks5_http_get
from .scoring_curves import latency_to_score_100 as _latency_to_score_100
from .xray_config_adapter import config_to_xray
from .xray_runner import XrayRunner

logger = logging.getLogger(__name__)

_GOOGLE_204_HOST = "clients3.google.com"
_GOOGLE_204_PATH = "/generate_204"
_GOOGLE_204_PORT = 80


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def find_free_port() -> int:
    """Return an available TCP port on localhost.

    Note: a TOCTOU race exists between this call and the subsequent bind.
    In practice the window is tiny, but callers should be prepared to handle
    a second failure and not treat this as a guaranteed-free port.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class RealHealthResult:
    """Result of a real-connectivity probe through xray."""

    config: str
    protocol: str
    reachable: bool = False
    google_204_ok: bool = False
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    from_cache: bool = False
    xray_version: Optional[str] = None
    socks_port: Optional[int] = None
    check_methods: List[str] = field(default_factory=list)
    retried: bool = False
    endpoint_probe: Optional[Dict[str, Any]] = None

    @property
    def quality_score(self) -> float:
        """Score 0-100 based on reachability and latency.

        Uses the canonical piecewise-linear curve from scoring_curves:
          unreachable / no latency  → 0
          ≤100 ms                   → 100
          ≤300 ms                   → 100 → 70
          ≤1000 ms                  → 70  → 20
          ≤3000 ms                  → 20  → 0
          >3000 ms                  → 0
        """
        if not self.reachable or self.latency_ms is None:
            return 0.0
        return round(max(0.0, _latency_to_score_100(self.latency_ms)), 1)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class _ResultCache:
    """In-memory cache for connectivity check results with per-entry TTL."""

    def __init__(self) -> None:
        self._cache: Dict[str, Tuple[RealHealthResult, float, float]] = {}
        self._hits: int = 0
        self._misses: int = 0

    @staticmethod
    def _key(config: str) -> str:
        return config.strip()

    def get(self, config: str) -> Optional[RealHealthResult]:
        """Return cached result or None if absent / expired."""
        key = self._key(config)
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None
        result, timestamp, ttl = entry
        if time.monotonic() - timestamp > ttl:
            del self._cache[key]
            self._misses += 1
            return None
        self._hits += 1
        return result

    def set(self, config: str, result: RealHealthResult, ttl: float = 300.0) -> None:
        """Store *result* under *config* key with the given TTL (seconds)."""
        self._cache[self._key(config)] = (result, time.monotonic(), ttl)

    def clear(self) -> None:
        """Remove all cached entries and reset counters."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def __len__(self) -> int:
        return len(self._cache)

    @property
    def stats(self) -> Dict[str, Any]:
        """Return hit/miss statistics."""
        total = self._hits + self._misses
        hit_rate = round(self._hits / total * 100, 1) if total else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
            "hit_rate": hit_rate,
        }


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------


class RealConnectivityChecker:
    """Check real internet connectivity through xray proxies.

    Supports both sync and async (asyncio) usage::

        checker = RealConnectivityChecker()

        # Sync
        result = checker.check_server_real_sync(uri)

        # Async
        result = await checker.check_server_real(uri)

        # Batch (async)
        results = await checker.check_servers_real_batch([(uri, protocol)])
    """

    def __init__(
        self,
        timeout: float = 10.0,
        startup_timeout: float = 5.0,
        max_workers: int = 5,
        concurrent_limit: int = 5,
        local_port_base: int = 10900,
        binary_path: Optional[str] = None,
        auto_download: bool = True,
        cache_enabled: bool = True,
        cache_ttl: float = 300.0,
        show_progress: bool = False,
    ) -> None:
        self.timeout = timeout
        self.startup_timeout = startup_timeout
        self.max_workers = max_workers
        self.concurrent_limit = concurrent_limit
        self.local_port_base = local_port_base
        self.binary_path = binary_path
        self.auto_download = auto_download
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        self.show_progress = show_progress

        self._cache = _ResultCache()
        self._port_counter = local_port_base

        self._manager: Any = None
        self._adapter: Any = None

    # ------------------------------------------------------------------
    # Port helpers
    # ------------------------------------------------------------------

    def _next_port(self) -> int:
        port = self._port_counter
        self._port_counter += 1
        return port

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    @property
    def cache_stats(self) -> Dict[str, Any]:
        """Return cache hit/miss statistics."""
        return self._cache.stats

    def clear_result_cache(self) -> None:
        """Clear the result cache."""
        self._cache.clear()

    def clear_cache(self) -> None:
        self.clear_result_cache()

    # ------------------------------------------------------------------
    # xray availability check
    # ------------------------------------------------------------------

    def is_xray_available(self) -> bool:
        """Return True if the xray binary can be located."""
        try:
            runner = XrayRunner(
                local_port=10808,
                binary_path=self.binary_path,
                auto_download=False,
            )
            return runner.is_available()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # async real connectivity check
    # ------------------------------------------------------------------

    async def check_real_connectivity(
        self,
        config: str,
        socks_port: int,
    ) -> Tuple[bool, Optional[float], bool, Optional[str]]:
        """Low-level async probe: returns (reachable, latency_ms, g204_ok, error)."""
        loop = asyncio.get_event_loop()
        ok, status, latency = await loop.run_in_executor(
            None,
            lambda: _socks5_http_get(
                socks_host="127.0.0.1",
                socks_port=socks_port,
                target_host=_GOOGLE_204_HOST,
                target_port=_GOOGLE_204_PORT,
                path=_GOOGLE_204_PATH,
                timeout=self.timeout,
            ),
        )
        g204 = ok and status == 204
        return ok, latency if ok else None, g204, None

    async def check_server_real(
        self,
        config: str,
        protocol: Optional[str] = None,
    ) -> RealHealthResult:
        """Async check of a single server config."""
        if protocol is None:
            protocol = config.split("://")[0] if "://" in config else "unknown"

        if self.cache_enabled:
            cached = self._cache.get(config)
            if cached is not None:
                return RealHealthResult(
                    config=cached.config,
                    protocol=cached.protocol,
                    reachable=cached.reachable,
                    google_204_ok=cached.google_204_ok,
                    latency_ms=cached.latency_ms,
                    error=cached.error,
                    from_cache=True,
                    xray_version=cached.xray_version,
                    socks_port=cached.socks_port,
                    check_methods=list(cached.check_methods),
                )

        retried = False
        if self._manager is not None and self._adapter is not None:
            socks_port = find_free_port()
            xray_version: Optional[str] = None
            try:
                with self._adapter.build_config_file(config, socks_port=socks_port):
                    async with self._manager.run(config, socks_port=socks_port):
                        xray_version = self._manager.get_version()
                        reachable, latency, g204, err = (
                            await self.check_real_connectivity(config, socks_port)
                        )
            except Exception as exc:
                reachable, latency, g204, err = False, None, False, str(exc)

            result = RealHealthResult(
                config=config,
                protocol=protocol,
                reachable=reachable,
                google_204_ok=g204,
                latency_ms=latency,
                error=err,
                from_cache=False,
                xray_version=xray_version,
                socks_port=socks_port,
                check_methods=["xray_start", "socks5_probe", "google_204"],
                retried=retried,
            )
        else:
            # Fallback: run sync check_one in executor (with built-in retry)
            loop = asyncio.get_event_loop()
            port = self._next_port()
            sync_result = await loop.run_in_executor(
                None,
                lambda: check_one(
                    config,
                    local_port=port,
                    timeout=self.timeout,
                    binary_path=self.binary_path,
                    auto_download=self.auto_download,
                ),
            )
            result = RealHealthResult(
                config=sync_result.config,
                protocol=sync_result.protocol,
                reachable=sync_result.reachable,
                google_204_ok=sync_result.google_204_ok,
                latency_ms=sync_result.latency_ms,
                error=sync_result.error,
                from_cache=False,
                socks_port=sync_result.socks_port,
                check_methods=["socks5_probe", "google_204"],
                retried=sync_result.retried,
            )

        if self.cache_enabled:
            ttl = self.cache_ttl if result.reachable else 60.0
            self._cache.set(config, result, ttl=ttl)

        return result

    async def check_servers_real_batch(
        self,
        servers: List[Tuple[str, str]],
    ) -> List[RealHealthResult]:
        """Async batch check with semaphore-based concurrency control."""
        if not servers:
            return []

        semaphore = asyncio.Semaphore(self.concurrent_limit)
        consecutive_failures = [0]

        async def _checked(config: str, protocol: str) -> RealHealthResult:
            async with semaphore:
                try:
                    result = await self.check_server_real(config, protocol=protocol)
                    if not result.reachable:
                        consecutive_failures[0] += 1
                        if consecutive_failures[0] > 1:
                            await asyncio.sleep(0.1 * consecutive_failures[0])
                    else:
                        consecutive_failures[0] = 0
                    return result
                except Exception as exc:
                    consecutive_failures[0] += 1
                    return RealHealthResult(
                        config=config,
                        protocol=protocol,
                        reachable=False,
                        error=str(exc),
                    )

        tasks = [_checked(cfg, proto) for cfg, proto in servers]
        results = await asyncio.gather(*tasks)
        return list(results)

    def check_server_real_sync(
        self, uri: str, use_cache: bool = True
    ) -> RealHealthResult:
        """Synchronous wrapper around check_server_real."""
        if use_cache and self.cache_enabled:
            cached = self._cache.get(uri)
            if cached is not None:
                return cached

        result = check_one(
            uri,
            local_port=self._next_port(),
            timeout=self.timeout,
            binary_path=self.binary_path,
            auto_download=self.auto_download,
        )
        rhr = RealHealthResult(
            config=result.config,
            protocol=result.protocol,
            reachable=result.reachable,
            google_204_ok=result.google_204_ok,
            latency_ms=result.latency_ms,
            error=result.error,
            socks_port=result.socks_port,
            retried=result.retried,
        )
        if use_cache and self.cache_enabled:
            ttl = self.cache_ttl if rhr.reachable else 60.0
            self._cache.set(uri, rhr, ttl=ttl)
        return rhr


# ---------------------------------------------------------------------------
# Standalone check_one (used by sync path and legacy callers)
# ---------------------------------------------------------------------------


@dataclass
class _LegacyResult:
    """Minimal result for check_one — consumed internally only."""

    config: str
    protocol: str
    reachable: bool = False
    google_204_ok: bool = False
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    socks_port: Optional[int] = None
    retried: bool = False
    endpoint_probe: Optional[Dict[str, Any]] = None


def _try_start_xray(
    port: int,
    cfg: Any,
    binary_path: Optional[str],
    auto_download: bool,
) -> Tuple[Optional[str], Optional[XrayRunner]]:
    """Attempt to start xray on *port*.

    Returns ``(None, runner)`` on success or ``(error_str, None)`` on failure.
    Guarantees that the runner is stopped if ``start()`` raises, preventing
    resource leaks in the calling retry loop.
    """
    runner = XrayRunner(
        local_port=port,
        binary_path=binary_path,
        auto_download=auto_download,
    )
    try:
        runner.start(cfg)
        return None, runner
    except RuntimeError as exc:
        # Best-effort cleanup: XrayRunner.stop() is a no-op when not started,
        # but call it anyway to release any partial state (open file handles,
        # half-initialised subprocess, etc.).
        try:
            runner.stop()
        except Exception:
            pass
        return str(exc), None


def check_one(
    uri: str,
    local_port: int = 10808,
    timeout: float = 10.0,
    binary_path: Optional[str] = None,
    auto_download: bool = True,
    live_probe: Optional[Callable[[int], Dict[str, Any]]] = None,
) -> _LegacyResult:
    """Spin up xray for *uri*, probe Google 204, return result.

    Retry policy (V1-D4)
    --------------------
    If xray fails to start (port contention, flaky binary, etc.), one retry is
    attempted with a fresh port from :func:`find_free_port`.  Both attempts are
    logged at DEBUG level.  On retry success ``retried=True`` is set on the
    returned result.  If the retry also fails, both the original and retry
    error messages are included in ``result.error`` and ``retried=True`` is
    still set.

    Resource safety
    ---------------
    :func:`_try_start_xray` always stops the runner on failure so no file
    handles or subprocess state leaks from a failed start attempt.
    The successful runner is stopped in a ``finally`` block after the probe.
    """
    if "://" not in uri:
        return _LegacyResult(config=uri, protocol="unknown", error="Not a valid URI")

    protocol = uri.split("://")[0].lower()
    xray_cfg = config_to_xray(uri, local_port=local_port)
    if xray_cfg is None:
        return _LegacyResult(
            config=uri,
            protocol=protocol,
            error="Could not convert URI to xray config",
        )

    # --- First attempt ---
    err_msg, runner = _try_start_xray(local_port, xray_cfg, binary_path, auto_download)
    retried = False

    if err_msg is not None:
        # --- Retry with a fresh free port (V1-D4) ---
        retry_port = find_free_port()
        retry_cfg = config_to_xray(uri, local_port=retry_port)
        if retry_cfg is None:
            return _LegacyResult(
                config=uri,
                protocol=protocol,
                error=err_msg,
                retried=True,
            )
        logger.debug(
            "[check_one] xray start failed on port %d (%s); retrying on port %d.",
            local_port,
            err_msg,
            retry_port,
        )
        retry_err, runner = _try_start_xray(
            retry_port, retry_cfg, binary_path, auto_download
        )
        retried = True
        if retry_err is not None:
            logger.debug(
                "[check_one] Retry on port %d also failed: %s.",
                retry_port,
                retry_err,
            )
            return _LegacyResult(
                config=uri,
                protocol=protocol,
                error=f"xray start failed: {err_msg} (retry: {retry_err})",
                retried=True,
            )
        local_port = retry_port

    # runner is guaranteed non-None here: both failure paths returned above.
    assert runner is not None  # noqa: S101 — invariant, not user-facing

    # --- Probe ---
    try:
        ok, status, latency = _socks5_http_get(
            socks_host="127.0.0.1",
            socks_port=local_port,
            target_host=_GOOGLE_204_HOST,
            target_port=_GOOGLE_204_PORT,
            path=_GOOGLE_204_PATH,
            timeout=timeout,
        )
        g204 = ok and status == 204
        endpoint_probe = None
        if ok and live_probe is not None:
            try:
                endpoint_probe = live_probe(local_port)
            except Exception as exc:
                endpoint_probe = {
                    "results": [],
                    "ok_count": 0,
                    "checked": 0,
                    "success_rate": 0.0,
                    "note": f"live endpoint probe failed: {exc}",
                }
        return _LegacyResult(
            config=uri,
            protocol=protocol,
            reachable=ok,
            google_204_ok=g204,
            latency_ms=latency,
            socks_port=local_port,
            retried=retried,
            endpoint_probe=endpoint_probe,
        )
    finally:
        runner.stop()


# ---------------------------------------------------------------------------
# Batch helper (public, backward compat)
# ---------------------------------------------------------------------------


def check_real_connectivity_batch(
    uris: List[str],
    max_workers: int = 5,
    local_port_base: int = 10900,
    timeout: float = 10.0,
    binary_path: Optional[str] = None,
    auto_download: bool = True,
    live_probe: Optional[Callable[[int], Dict[str, Any]]] = None,
) -> List[RealHealthResult]:
    """Run real-connectivity checks on a list of URIs concurrently."""
    import threading

    results: List[RealHealthResult] = []
    port_lock = threading.Lock()
    port_counter = [local_port_base]

    def _get_port() -> int:
        with port_lock:
            p = port_counter[0]
            port_counter[0] += 1
            return p

    def _worker(uri: str) -> RealHealthResult:
        port = _get_port()
        r = check_one(
            uri,
            local_port=port,
            timeout=timeout,
            binary_path=binary_path,
            auto_download=auto_download,
            live_probe=live_probe,
        )
        return RealHealthResult(
            config=r.config,
            protocol=r.protocol,
            reachable=r.reachable,
            google_204_ok=r.google_204_ok,
            latency_ms=r.latency_ms,
            error=r.error,
            socks_port=r.socks_port,
            retried=r.retried,
            endpoint_probe=r.endpoint_probe,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_worker, u): u for u in uris}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:
                uri = futures[fut]
                results.append(
                    RealHealthResult(
                        config=uri,
                        protocol=uri.split("://")[0] if "://" in uri else "unknown",
                        error=str(exc),
                    )
                )

    results.sort(
        key=lambda r: (
            not r.google_204_ok,
            not r.reachable,
            r.latency_ms if r.latency_ms is not None else 9999,
        )
    )
    return results


def real_health_to_dict(r: RealHealthResult) -> Dict:
    """Serialise to plain dict (CLI / JSON output)."""
    return {
        "config": r.config,
        "protocol": r.protocol,
        "reachable": r.reachable,
        "google_204_ok": r.google_204_ok,
        "latency_ms": r.latency_ms,
        "error": r.error,
        "endpoint_probe": r.endpoint_probe,
        "from_cache": r.from_cache,
        "xray_version": r.xray_version,
        "quality_score": r.quality_score,
        "retried": r.retried,
    }
