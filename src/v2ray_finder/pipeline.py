"""Pipeline orchestrator for v2ray-finder.

Provides a single :class:`Pipeline` entry point that owns the full
discovery → fetch → dedup → health → score → output chain.

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

Source caching (V2-C1)
----------------------
The pipeline has built-in TTL source caching via :class:`~cache.CacheManager`.
Each source URL’s raw response text is cached under a key derived from the URL.
On cache hit the network fetch is skipped entirely.  Caching is opt-in::

    pipeline = Pipeline(cache_enabled=True)
    pipeline = Pipeline(cache_enabled=True, cache_backend="disk", cache_ttl=1800)
    pipeline = Pipeline(cache_manager=my_cm)

Serialization (V3-A1)
---------------------
:meth:`PipelineResult.to_dict` and :meth:`PipelineResult.to_json` produce
stable, round-trip-safe representations::

    result = pipeline.run()
    print(result.to_json())

Layer-3 cache stats (V1-Q4)
----------------------------
When ``check_google_204=True`` the Layer-3 result cache stats are surfaced
in ``PipelineResult.stats["layer3_cache"]``::

    result = pipeline.run()
    print(result.stats["layer3_cache"])  # {hits, misses, size, hit_rate}

Call ``pipeline.clear_caches()`` to reset the Layer-3 result cache between
runs without reconstructing the pipeline.

Stub-ability
------------
Tests may replace :meth:`_fetch_all_sync` on an instance::

    p = Pipeline(sources=[src], check_health=False)
    p._fetch_all_sync = lambda stop, cb: {src.url: ["vmess://..."]}
    result = p.run()

Example
-------
::

    from v2ray_finder.pipeline import Pipeline, StopController

    stop = StopController()
    pipeline = Pipeline(check_health=True, check_google_204=True, cache_enabled=True)
    result = pipeline.run(stop_event=stop.event)
    print(result.stats.get("layer3_cache"))
    print(result.to_json(indent=2))
    for score in result.scores[:10]:
        print(score.grade, score.config[:80])
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from .async_fetcher import AsyncFetcher, FetchResult
from .cache import CacheManager
from .normalizer import deduplicate_across_sources
from .scorer import ServerScore, score_servers
from .sources import SourceEntry, get_enabled_sources

logger = logging.getLogger(__name__)

_PROTO_RE = re.compile(
    r"(?:vmess|vless|trojan|ss|ssr)://[A-Za-z0-9+/=_\-@:.?&#%]+",
    re.IGNORECASE,
)

_GITHUB_HOSTS: frozenset = frozenset({
    "api.github.com",
    "raw.githubusercontent.com",
})

_DEFAULT_FETCH_CONCURRENCY       = 10
_DEFAULT_MAX_CONFIGS_PER_SOURCE  = 5_000
_DEFAULT_MAX_TOTAL_CONFIGS       = 50_000
_DEFAULT_CACHE_TTL               = 3_600

ProgressCallback = Optional[Callable[[str, int, int, str], None]]


def _is_github_url(url: str) -> bool:
    try:
        return urlparse(url).hostname in _GITHUB_HOSTS
    except Exception:
        return False


def _parse_configs(text: str) -> List[str]:
    return list(dict.fromkeys(_PROTO_RE.findall(text)))


# ---------------------------------------------------------------------------
# StopController
# ---------------------------------------------------------------------------

class StopController:
    """Thin wrapper around :class:`threading.Event` for pipeline cancellation."""

    def __init__(self) -> None:
        self.event: threading.Event = threading.Event()

    def stop(self) -> None:
        self.event.set()

    def reset(self) -> None:
        self.event.clear()

    def is_set(self) -> bool:
        return self.event.is_set()


# ---------------------------------------------------------------------------
# PipelineResult
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """Container for the output of a completed pipeline run."""

    configs:      List[str]             = field(default_factory=list)
    health_dicts: List[Dict[str, Any]]  = field(default_factory=list)
    scores:       List[ServerScore]     = field(default_factory=list)
    overlap_map:  Dict[str, float]      = field(default_factory=dict)
    stats:        Dict[str, Any]        = field(default_factory=dict)

    @property
    def top_configs(self) -> List[str]:
        return [s.config for s in self.scores]

    # V3-A1: serialisation -------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation of this result.

        Keys
        ----
        stats    -- pipeline run statistics (fetched, deduped, healthy, ...).
                    Includes ``layer3_cache`` when Layer 3 ran (V1-Q4).
        servers  -- list of :meth:`~scorer.ServerScore.to_dict` dicts,
                    ordered by score (best first).
        configs  -- raw config strings in score order (convenience duplicate).
        """
        servers = [s.to_dict() for s in self.scores]
        return {
            "stats":   self.stats,
            "servers": servers,
            "configs": [s["config"] for s in servers] if servers else self.configs,
        }

    def to_json(self, indent: int = 2) -> str:
        """Return a JSON string of :meth:`to_dict`."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @property
    def failed_sources(self) -> Dict[str, str]:
        """V1-D2: sources that failed during fetch, keyed by URL."""
        errors = self.stats.get("errors")
        if isinstance(errors, dict):
            return errors
        return {}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class Pipeline:
    """Full discovery → fetch → dedup → health → score pipeline."""

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
        github_token: Optional[str] = None,
        max_configs_per_source: int = _DEFAULT_MAX_CONFIGS_PER_SOURCE,
        max_total_configs: Optional[int] = _DEFAULT_MAX_TOTAL_CONFIGS,
        cache_enabled: bool = False,
        cache_backend: str = "memory",
        cache_ttl: int = _DEFAULT_CACHE_TTL,
        cache_dir: Optional[str] = None,
        cache_manager: Optional[CacheManager] = None,
    ) -> None:
        self.sources                = sources or get_enabled_sources()
        self.check_health           = check_health
        self.check_http_probe       = check_http_probe
        self.check_google_204       = check_google_204
        self.timeout                = timeout
        self.min_quality_score      = min_quality_score
        self.health_batch_size      = health_batch_size
        self.fetch_timeout          = fetch_timeout
        self.fetch_concurrency      = fetch_concurrency
        self.limit                  = limit
        self.binary_path            = binary_path
        self.github_token           = github_token
        self.max_configs_per_source = max_configs_per_source
        self.max_total_configs      = max_total_configs

        if cache_manager is not None:
            self._cache: Optional[CacheManager] = cache_manager
        elif cache_enabled:
            self._cache = CacheManager(
                backend=cache_backend,
                ttl=cache_ttl,
                cache_dir=cache_dir,
                enabled=True,
            )
        else:
            self._cache = None

        self._source_trust_map: Dict[str, int] = {
            s.url: s.trust.value for s in self.sources
        }

        # Shared HealthChecker — created once and reused across run() calls.
        # This keeps the Layer-3 RealConnectivityChecker (and its result cache)
        # alive between runs so clear_caches() can reach it (V1-Q4).
        self._health_checker: Optional[Any] = None

    # ------------------------------------------------------------------
    # V1-Q4: cache management
    # ------------------------------------------------------------------

    def clear_caches(self) -> None:
        """Clear all in-pipeline caches between runs.

        Clears:
        - Source-text TTL cache (:class:`~cache.CacheManager`) if enabled.
        - Layer-3 result cache (``RealConnectivityChecker._cache``) if
          ``check_google_204=True`` and a checker was previously created.
        """
        if self._cache is not None:
            try:
                self._cache.clear()
            except Exception as exc:
                logger.debug("[pipeline] Source cache clear failed: %s", exc)

        if self._health_checker is not None:
            checker = getattr(self._health_checker, "_layer3_checker", None)
            if checker is not None:
                try:
                    checker.clear_result_cache()
                    logger.debug("[pipeline] Layer-3 result cache cleared.")
                except Exception as exc:
                    logger.debug("[pipeline] Layer-3 cache clear failed: %s", exc)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        stop_event: Optional[threading.Event] = None,
        progress_callback: ProgressCallback = None,
    ) -> PipelineResult:
        """Execute the full pipeline and return a :class:`PipelineResult`."""
        _stop = stop_event or threading.Event()
        result = PipelineResult()
        stats: Dict[str, Any] = {
            "fetched": 0, "deduped": 0, "healthy": 0, "scored": 0,
            "dropped_per_source": 0, "dropped_global": 0,
            "cache_hits": 0, "cache_misses": 0,
            "errors": {},
        }

        # Stage 1: Fetch
        servers_by_source = self._fetch_all(_stop, progress_callback)

        if self._cache is not None:
            cs = self._cache.get_stats()
            stats["cache_hits"]   = cs.get("hits",   0)
            stats["cache_misses"] = cs.get("misses", 0)

        for url in list(servers_by_source.keys()):
            if isinstance(servers_by_source[url], str):
                stats["errors"][url] = servers_by_source.pop(url)
                continue
            full = servers_by_source[url]
            if len(full) > self.max_configs_per_source:
                dropped = len(full) - self.max_configs_per_source
                servers_by_source[url] = full[: self.max_configs_per_source]
                stats["dropped_per_source"] += dropped
                logger.warning(
                    "[pipeline] %s: capped at %d configs (%d dropped).",
                    url, self.max_configs_per_source, dropped,
                )

        stats["fetched"] = sum(len(v) for v in servers_by_source.values())
        if _stop.is_set():
            result.stats = stats
            return result

        # Stage 2: Structural dedup
        configs, overlap_map = deduplicate_across_sources(servers_by_source)

        if self.max_total_configs is not None and len(configs) > self.max_total_configs:
            dropped_global = len(configs) - self.max_total_configs
            configs = configs[: self.max_total_configs]
            stats["dropped_global"] = dropped_global
            logger.warning(
                "[pipeline] Global cap: kept %d configs, dropped %d after dedup.",
                self.max_total_configs, dropped_global,
            )

        if self.limit:
            configs = configs[: self.limit]

        stats["deduped"]   = len(configs)
        result.configs     = configs
        result.overlap_map = overlap_map
        if _stop.is_set():
            result.stats = stats
            return result

        config_source_map = self._build_config_source_map(servers_by_source)

        # Stage 3: Health checks
        if not self.check_health:
            result.health_dicts = [
                self._make_unchecked_dict(c, config_source_map, overlap_map)
                for c in configs
            ]
        else:
            result.health_dicts = self._run_health(
                configs, config_source_map, overlap_map, _stop, progress_callback
            )
        stats["healthy"] = len(result.health_dicts)

        # V1-Q4: capture Layer-3 cache stats after health checks
        if self.check_google_204 and self._health_checker is not None:
            l3 = getattr(self._health_checker, "_layer3_checker", None)
            if l3 is not None:
                try:
                    stats["layer3_cache"] = l3.cache_stats
                except Exception:
                    pass

        if _stop.is_set():
            result.stats = stats
            return result

        # Stage 4: Score
        self._emit(progress_callback, "score", 0, 1, "Scoring servers…")
        result.scores = score_servers(
            result.health_dicts,
            overlap_map=overlap_map,
            descending=True,
        )
        stats["scored"] = len(result.scores)
        self._emit(progress_callback, "score", 1, 1, "Scoring complete.")

        result.stats = stats
        return result

    # ------------------------------------------------------------------
    # Source attribution
    # ------------------------------------------------------------------

    def _build_config_source_map(
        self,
        servers_by_source: Dict[str, List[str]],
    ) -> Dict[str, str]:
        config_source: Dict[str, str] = {}
        for url in sorted(
            servers_by_source.keys(),
            key=lambda u: self._source_trust_map.get(u, 1),
        ):
            for cfg in servers_by_source[url]:
                config_source[cfg] = url
        return config_source

    def _make_unchecked_dict(
        self,
        config: str,
        config_source_map: Dict[str, str],
        overlap_map: Dict[str, float],
    ) -> Dict[str, Any]:
        src_url   = config_source_map.get(config, "")
        src_trust = self._source_trust_map.get(src_url, 1)
        proto = config.split("://")[0].lower() if "://" in config else "unknown"
        return {
            "config":         config,
            "protocol":       proto,
            "health_checked": False,
            "source_url":     src_url,
            "source_trust":   src_trust,
            "overlap_ratio":  overlap_map.get(src_url, 0.0),
        }

    # ------------------------------------------------------------------
    # Stage 1: Fetch
    # ------------------------------------------------------------------

    def _fetch_all(
        self,
        stop_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> Dict[str, Any]:
        return self._fetch_all_sync(stop_event, progress_callback)

    def _fetch_all_sync(
        self,
        stop_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> Dict[str, Any]:
        """Fetch all sources with TTL cache support and GitHub rate-limit handling."""
        github_urls     = [s.url for s in self.sources if _is_github_url(s.url)]
        non_github_urls = [s.url for s in self.sources if not _is_github_url(s.url)]
        total           = len(self.sources)

        self._emit(progress_callback, "fetch", 0, total, "Starting fetch…")

        base_headers   = {"User-Agent": "v2ray-finder/1.0"}
        github_headers = dict(base_headers)
        if self.github_token:
            github_headers["Authorization"] = f"token {self.github_token}"

        servers_by_source: Dict[str, Any] = {}
        completed = 0

        def _try_cache(url: str):
            if self._cache is None:
                return False, None
            key    = self._cache._make_key("source", url)
            cached = self._cache.get(key)
            if cached is not None:
                return True, _parse_configs(cached)
            return False, None

        def _store_cache(url: str, text: str) -> None:
            if self._cache is not None:
                self._cache.set(self._cache._make_key("source", url), text)

        # Non-GitHub sources
        urls_to_fetch_ng: List[str] = []
        for url in non_github_urls:
            hit, configs = _try_cache(url)
            if hit:
                servers_by_source[url] = configs
                completed += 1
                self._emit(progress_callback, "fetch", completed, total,
                           f"Cache hit {completed}/{total}…")
            else:
                urls_to_fetch_ng.append(url)

        if urls_to_fetch_ng and not stop_event.is_set():
            fetcher = AsyncFetcher(
                max_concurrent=self.fetch_concurrency,
                timeout=float(self.fetch_timeout),
                headers=base_headers,
            )
            for fr in fetcher.fetch_many(urls_to_fetch_ng):
                if stop_event.is_set():
                    break
                if fr.success and fr.content:
                    _store_cache(fr.url, fr.content)
                    self._process_fetch_result(fr, servers_by_source)
                elif not fr.success:
                    servers_by_source[fr.url] = fr.error or "fetch failed"
                completed += 1
                self._emit(progress_callback, "fetch", completed, total,
                           f"Fetched {completed}/{total} sources…")

        # GitHub sources
        urls_to_fetch_gh: List[str] = []
        for url in github_urls:
            hit, configs = _try_cache(url)
            if hit:
                servers_by_source[url] = configs
                completed += 1
                self._emit(progress_callback, "fetch", completed, total,
                           f"Cache hit {completed}/{total}…")
            else:
                urls_to_fetch_gh.append(url)

        if urls_to_fetch_gh and not stop_event.is_set():
            github_fetcher = AsyncFetcher(
                max_concurrent=min(self.fetch_concurrency, 5),
                timeout=float(self.fetch_timeout),
                headers=github_headers,
            )
            github_rate_limited = False
            for fr in github_fetcher.fetch_many(urls_to_fetch_gh):
                if stop_event.is_set():
                    break
                if github_rate_limited:
                    logger.debug("[pipeline] Skipping %s (GitHub rate-limited).", fr.url)
                elif fr.status_code in (403, 429):
                    logger.warning(
                        "[pipeline] GitHub rate limit on %s (HTTP %d).",
                        fr.url, fr.status_code,
                    )
                    github_rate_limited = True
                    servers_by_source[fr.url] = f"rate_limited:{fr.status_code}"
                else:
                    if fr.success and fr.content:
                        _store_cache(fr.url, fr.content)
                        self._process_fetch_result(fr, servers_by_source)
                    elif not fr.success:
                        servers_by_source[fr.url] = fr.error or "fetch failed"
                completed += 1
                self._emit(progress_callback, "fetch", completed, total,
                           f"Fetched {completed}/{total} sources…")

        self._emit(progress_callback, "fetch", total, total, "Fetch complete.")
        return servers_by_source

    @staticmethod
    def _process_fetch_result(
        fr: FetchResult,
        servers_by_source: Dict[str, Any],
    ) -> None:
        if fr.success and fr.content:
            parsed = _parse_configs(fr.content)
            if parsed:
                servers_by_source[fr.url] = parsed
                logger.debug("[pipeline] %s: %d configs.", fr.url, len(parsed))
        else:
            logger.warning("[pipeline] %s: fetch failed — %s.", fr.url, fr.error)

    # ------------------------------------------------------------------
    # Stage 3: Health
    # ------------------------------------------------------------------

    def _run_health(
        self,
        configs: List[str],
        config_source_map: Dict[str, str],
        overlap_map: Dict[str, float],
        stop_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> List[Dict[str, Any]]:
        from .health_checker import HealthChecker, filter_healthy_servers

        # Reuse existing checker so Layer-3 cache persists across batches
        # and is accessible via clear_caches() / stats (V1-Q4).
        if self._health_checker is None:
            self._health_checker = HealthChecker(
                timeout=self.timeout,
                min_quality_score=self.min_quality_score,
                check_http_probe=self.check_http_probe,
                check_google_204=self.check_google_204,
                binary_path=self.binary_path,
            )
        checker = self._health_checker

        total      = len(configs)
        all_health: list = []

        for batch_start in range(0, total, self.health_batch_size):
            if stop_event.is_set():
                break
            batch = configs[batch_start: batch_start + self.health_batch_size]
            self._emit(
                progress_callback, "health", batch_start, total,
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
            src_url   = config_source_map.get(h.config, "")
            src_trust = self._source_trust_map.get(src_url, 1)
            proto = h.config.split("://")[0].lower() if "://" in h.config else getattr(h, "protocol", "unknown")
            result_dicts.append({
                "config":         h.config,
                "protocol":       proto,
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
        if cb is not None:
            try:
                cb(stage, current, total, message)
            except Exception:
                pass
