"""Pipeline orchestrator for v2ray-finder.

Provides a single :class:`Pipeline` entry point that owns the full
discovery → fetch → dedup → health → score → output chain.

CLI, Rich TUI, and GUI callers should instantiate ``Pipeline`` and call
``Pipeline.run()`` instead of re-implementing the sequence themselves.

Progress callback protocol
--------------------------
All progress callbacks follow the signature::

    callback(stage: str, current: int, total: int, message: str) -> None

``stage`` is one of ``"fetch"``, ``"health"``, ``"score"``.

Cancellation
------------
Pass a :class:`StopController` (or any ``threading.Event``) as
``stop_event`` to ``Pipeline.run()``.  The pipeline checks the event
before every source fetch and every health-check batch.

Async fetch
-----------
When ``httpx`` is installed, :meth:`Pipeline._fetch_all` uses
``asyncio`` + ``httpx.AsyncClient`` with a shared semaphore capped at
``fetch_concurrency`` (default 10).  If ``httpx`` is not available the
pipeline silently falls back to sequential ``requests`` calls so
existing deployments are not broken.

Example
-------
::

    from v2ray_finder.pipeline import Pipeline, StopController

    stop = StopController()
    pipeline = Pipeline(check_health=True, check_google_204=True)
    result = pipeline.run(stop_event=stop.event)
    for score in result.scores[:10]:
        print(score.grade, score.config[:80])
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .normalizer import deduplicate_across_sources
from .scorer import ServerScore, score_servers, sort_by_quality
from .sources import SourceEntry, SourceTrust, get_enabled_sources

logger = logging.getLogger(__name__)

# Regex shared across fetch paths
_PROTO_RE = re.compile(
    r"(?:vmess|vless|trojan|ss|ssr)://[A-Za-z0-9+/=_\-@:.?&#%]+",
    re.IGNORECASE,
)

# Default concurrency cap for async source fetches
_DEFAULT_FETCH_CONCURRENCY = 10

# Type alias for the progress callback.
ProgressCallback = Optional[Callable[[str, int, int, str], None]]


def _parse_configs(text: str) -> List[str]:
    """Extract deduplicated proxy URIs from raw subscription text."""
    return list(dict.fromkeys(_PROTO_RE.findall(text)))


# ---------------------------------------------------------------------------
# StopController
# ---------------------------------------------------------------------------

class StopController:
    """Thin wrapper around :class:`threading.Event` for pipeline cancellation.

    CLI ``KeyboardInterrupt`` handlers and GUI worker threads both call
    ``controller.stop()``.  The pipeline polls ``controller.event``.

    Usage::

        ctrl = StopController()
        # In a signal handler or GUI button:
        ctrl.stop()
        # In the pipeline:
        if ctrl.is_set():
            break
    """

    def __init__(self) -> None:
        self.event: threading.Event = threading.Event()

    def stop(self) -> None:
        """Signal the pipeline to stop."""
        self.event.set()

    def reset(self) -> None:
        """Clear the stop signal (e.g. before a fresh run)."""
        self.event.clear()

    def is_set(self) -> bool:
        """Return True if stop has been requested."""
        return self.event.is_set()


# ---------------------------------------------------------------------------
# PipelineResult
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """Container for the output of a completed pipeline run.

    Attributes:
        configs:      Structurally deduplicated raw config strings (unsorted).
        health_dicts: Health-check result dicts (one per healthy server).
        scores:       Scored + sorted :class:`~scorer.ServerScore` objects.
        overlap_map:  Per-source overlap ratios from
                      :func:`~normalizer.deduplicate_across_sources`.
        stats:        Miscellaneous counters (fetched, deduped, healthy, scored).
    """

    configs:      List[str]                  = field(default_factory=list)
    health_dicts: List[Dict[str, Any]]        = field(default_factory=list)
    scores:       List[ServerScore]           = field(default_factory=list)
    overlap_map:  Dict[str, float]            = field(default_factory=dict)
    stats:        Dict[str, int]              = field(default_factory=dict)

    @property
    def top_configs(self) -> List[str]:
        """Return config strings sorted by score (best first)."""
        return [s.config for s in self.scores]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class Pipeline:
    """Full discovery → fetch → dedup → health → score pipeline.

    Parameters
    ----------
    sources:
        List of :class:`~sources.SourceEntry` objects to fetch.
        Defaults to all enabled sources from :func:`~sources.get_enabled_sources`.
    check_health:
        Run TCP health checks (Layer 1).  Default: ``True``.
    check_http_probe:
        Run direct HTTP probe (Layer 2).  Default: ``False``.
    check_google_204:
        Run xray SOCKS5 / Google 204 probe (Layer 3).  Default: ``False``.
    timeout:
        Per-server probe timeout in seconds.  Default: ``5.0``.
    min_quality_score:
        Exclude servers scoring below this threshold.  Default: ``0.0``.
    health_batch_size:
        Number of servers per async health-check batch.  Default: ``100``.
    fetch_timeout:
        HTTP timeout for source fetches.  Default: ``15``.
    fetch_concurrency:
        Maximum number of concurrent async source fetches.  Default: ``10``.
        Ignored when httpx is not installed (fallback uses sequential fetch).
    limit:
        Cap the number of configs returned after dedup.  Default: ``None``.
    binary_path:
        Explicit path to the xray binary (Layer 3 only).
    """

    def __init__(
        self,
        sources: Optional[List[SourceEntry]] = None,
        check_health: bool = True,
        check_http_probe: bool = False,
        check_google_204: bool = False,
        timeout: float = 5.0,
        min_quality_score: float = 0.0,
        health_batch_size: int = 100,
        fetch_timeout: int = 15,
        fetch_concurrency: int = _DEFAULT_FETCH_CONCURRENCY,
        limit: Optional[int] = None,
        binary_path: Optional[str] = None,
    ) -> None:
        self.sources          = sources or get_enabled_sources()
        self.check_health     = check_health
        self.check_http_probe = check_http_probe
        self.check_google_204 = check_google_204
        self.timeout          = timeout
        self.min_quality_score = min_quality_score
        self.health_batch_size = health_batch_size
        self.fetch_timeout    = fetch_timeout
        self.fetch_concurrency = fetch_concurrency
        self.limit            = limit
        self.binary_path      = binary_path

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        stop_event: Optional[threading.Event] = None,
        progress_callback: ProgressCallback = None,
    ) -> PipelineResult:
        """Execute the full pipeline and return a :class:`PipelineResult`.

        Args:
            stop_event:        A :class:`threading.Event` that, when set,
                               causes the pipeline to exit at the next
                               cancellation checkpoint.
            progress_callback: Optional callback with signature
                               ``(stage, current, total, message)``.

        Returns:
            :class:`PipelineResult` with configs, scores, and stats.
        """
        _stop = stop_event or threading.Event()  # no-op event if not provided
        result = PipelineResult()
        stats: Dict[str, int] = {"fetched": 0, "deduped": 0, "healthy": 0, "scored": 0}

        # ── Stage 1: Fetch (async when httpx available) ─────────────────────
        servers_by_source = self._fetch_all(_stop, progress_callback)
        stats["fetched"] = sum(len(v) for v in servers_by_source.values())
        if _stop.is_set():
            result.stats = stats
            return result

        # ── Stage 2: Structural dedup ───────────────────────────────────────
        configs, overlap_map = deduplicate_across_sources(servers_by_source)
        if self.limit:
            configs = configs[: self.limit]
        stats["deduped"]   = len(configs)
        result.configs     = configs
        result.overlap_map = overlap_map
        logger.info(
            "[pipeline] Fetch complete: %d raw → %d unique configs.",
            stats["fetched"], stats["deduped"],
        )
        if _stop.is_set():
            result.stats = stats
            return result

        # ── Stage 3: Health checks ──────────────────────────────────────────
        if not self.check_health:
            result.health_dicts = [
                {"config": c, "health_checked": False} for c in configs
            ]
        else:
            result.health_dicts = self._run_health(
                configs, overlap_map, _stop, progress_callback
            )
        stats["healthy"] = len(result.health_dicts)
        if _stop.is_set():
            result.stats = stats
            return result

        # ── Stage 4: Score ──────────────────────────────────────────────────
        self._emit(progress_callback, "score", 0, 1, "Scoring servers…")
        result.scores = score_servers(
            result.health_dicts,
            overlap_map=overlap_map,
            descending=True,
        )
        stats["scored"] = len(result.scores)
        self._emit(progress_callback, "score", 1, 1, "Scoring complete.")
        logger.info(
            "[pipeline] Pipeline complete: %d servers scored.",
            stats["scored"],
        )

        result.stats = stats
        return result

    # ------------------------------------------------------------------
    # Stage 1: Fetch
    # ------------------------------------------------------------------

    def _fetch_all(
        self,
        stop_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> Dict[str, List[str]]:
        """Dispatch to async or sync fetch depending on httpx availability."""
        try:
            import httpx  # noqa: F401
            return asyncio.run(
                self._fetch_all_async(stop_event, progress_callback)
            )
        except ImportError:
            logger.debug(
                "[pipeline] httpx not installed — using sequential fetch fallback."
            )
            return self._fetch_all_sync(stop_event, progress_callback)

    async def _fetch_all_async(
        self,
        stop_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> Dict[str, List[str]]:
        """Fetch all sources concurrently using httpx + asyncio.

        A shared semaphore limits simultaneous connections to
        ``self.fetch_concurrency`` so we don’t flood the network.
        Stop-event is checked before dispatching each task and after
        every completed fetch.
        """
        import httpx

        total     = len(self.sources)
        semaphore = asyncio.Semaphore(self.fetch_concurrency)
        results: Dict[str, List[str]] = {}
        completed = 0

        self._emit(progress_callback, "fetch", 0, total, "Starting async fetch…")

        async def _fetch_one(source: SourceEntry) -> tuple[str, List[str]]:
            """Fetch a single source; return (url, configs)."""
            async with semaphore:
                if stop_event.is_set():
                    return source.url, []
                for attempt in range(2):  # 1 retry on transient error
                    try:
                        async with httpx.AsyncClient(
                            timeout=self.fetch_timeout,
                            follow_redirects=True,
                            headers={"User-Agent": "v2ray-finder/1.0"},
                        ) as client:
                            resp = await client.get(source.url)
                        if resp.status_code == 200:
                            configs = _parse_configs(resp.text)
                            logger.debug(
                                "[pipeline] %s: %d configs (async).",
                                source.label, len(configs),
                            )
                            return source.url, configs
                        else:
                            logger.warning(
                                "[pipeline] %s: HTTP %d.",
                                source.label, resp.status_code,
                            )
                            return source.url, []
                    except Exception as exc:
                        if attempt == 0:
                            logger.debug(
                                "[pipeline] %s: transient error (%s), retrying.",
                                source.label, exc,
                            )
                            await asyncio.sleep(0.5)
                        else:
                            logger.warning(
                                "[pipeline] %s: fetch failed — %s.",
                                source.label, exc,
                            )
                            return source.url, []
            return source.url, []  # unreachable but satisfies type checker

        # Create all tasks up-front; cancel remaining on stop.
        tasks = [
            asyncio.create_task(_fetch_one(src))
            for src in self.sources
            if not stop_event.is_set()
        ]

        for coro in asyncio.as_completed(tasks):
            if stop_event.is_set():
                for t in tasks:
                    t.cancel()
                break
            try:
                url, configs = await coro
                if configs:
                    results[url] = configs
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("[pipeline] Unexpected async fetch error: %s", exc)
            finally:
                completed += 1
                self._emit(
                    progress_callback, "fetch", completed, total,
                    f"Fetched {completed}/{total} sources…",
                )

        self._emit(progress_callback, "fetch", total, total, "Fetch complete.")
        return results

    def _fetch_all_sync(
        self,
        stop_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> Dict[str, List[str]]:
        """Sequential fallback fetch (no httpx required)."""
        import requests as _requests

        servers_by_source: Dict[str, List[str]] = {}
        total = len(self.sources)

        for i, source in enumerate(self.sources):
            if stop_event.is_set():
                break
            self._emit(
                progress_callback, "fetch", i, total,
                f"Fetching {source.label}…",
            )
            try:
                resp = _requests.get(
                    source.url,
                    timeout=self.fetch_timeout,
                    headers={"User-Agent": "v2ray-finder/1.0"},
                    allow_redirects=True,
                )
                if resp.status_code == 200:
                    parsed = _parse_configs(resp.text)
                    servers_by_source[source.url] = parsed
                    logger.debug(
                        "[pipeline] %s: %d configs (sync).",
                        source.label, len(parsed),
                    )
                else:
                    logger.warning(
                        "[pipeline] %s: HTTP %d.",
                        source.label, resp.status_code,
                    )
            except Exception as exc:
                logger.warning("[pipeline] %s: fetch error — %s.", source.label, exc)

        self._emit(progress_callback, "fetch", total, total, "Fetch complete.")
        return servers_by_source

    # ------------------------------------------------------------------
    # Stage 3: Health
    # ------------------------------------------------------------------

    def _run_health(
        self,
        configs: List[str],
        overlap_map: Dict[str, float],
        stop_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> List[Dict[str, Any]]:
        """Run health checks on *configs* and return annotated result dicts."""
        from .health_checker import HealthChecker, filter_healthy_servers
        from .sources import get_enabled_sources

        source_trust_map: Dict[str, int] = {
            s.url: s.trust.value for s in get_enabled_sources()
        }

        checker = HealthChecker(
            timeout=self.timeout,
            min_quality_score=self.min_quality_score,
            check_http_probe=self.check_http_probe,
            check_google_204=self.check_google_204,
            binary_path=self.binary_path,
        )

        total     = len(configs)
        all_health: list = []

        for batch_start in range(0, total, self.health_batch_size):
            if stop_event.is_set():
                break
            batch = configs[batch_start: batch_start + self.health_batch_size]
            self._emit(
                progress_callback, "health",
                batch_start, total,
                f"Health checking "
                f"{batch_start + 1}–{min(batch_start + self.health_batch_size, total)}…",
            )
            try:
                all_health.extend(checker.check_batch(batch))
            except Exception as exc:
                logger.warning("[pipeline] Health batch error: %s", exc)

        self._emit(progress_callback, "health", total, total, "Health checks complete.")

        healthy = filter_healthy_servers(
            all_health, min_quality_score=self.min_quality_score
        )

        result_dicts: List[Dict[str, Any]] = []
        for h in healthy:
            # Best-effort source attribution: pick first source URL that
            # exists in overlap_map and in the trust map.
            src_url   = ""
            src_trust = 1
            for url in overlap_map:
                if url in source_trust_map:
                    src_url   = url
                    src_trust = source_trust_map[url]
                    break

            result_dicts.append({
                "config":         h.config,
                "protocol":       h.protocol,
                "tcp_ok":         h.tcp_ok,
                "http_ok":        h.http_probe_ok,
                "google_204_ok":  h.google_204_ok,
                "latency_ms":     h.latency_ms,
                "health_checked": True,
                "source_url":     src_url,
                "source_trust":   src_trust,
                "overlap_ratio":  overlap_map.get(src_url, 0.0),
            })
        return result_dicts

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _emit(
        cb: ProgressCallback,
        stage: str,
        current: int,
        total: int,
        message: str,
    ) -> None:
        """Fire the progress callback if one was provided."""
        if cb is not None:
            try:
                cb(stage, current, total, message)
            except Exception:
                pass  # never let a callback crash the pipeline
