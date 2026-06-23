"""v2ray-finder: Fetch and aggregate V2Ray server configurations from GitHub.

Quick-start
-----------
The simplest way to get a list of live configs in one call::

    import v2ray_finder

    configs = v2ray_finder.find_servers(limit=50)
    for cfg in configs:
        print(cfg)

For full control, instantiate :class:`Pipeline` directly::

    from v2ray_finder import Pipeline, StopController

    stop     = StopController()
    pipeline = Pipeline(check_health=True, github_token="ghp_...")
    result   = pipeline.run(stop_event=stop.event)
    for score in result.scores[:20]:
        print(score.grade, score.config[:80])
"""

from __future__ import annotations

from typing import List, Optional

from .core import V2RayServerFinder
from .exceptions import (
    AuthenticationError,
    ConfigParseError,
    ErrorType,
    GitHubAPIError,
    ParseError,
    RateLimitError,
    V2RayFinderError,
)
from .normalizer import (
    NormalizedServer,
    deduplicate_across_sources,
    deduplicate_servers,
    normalize_server,
)
from .result import Err, Ok, Result
from .source_registry import SourceRegistry, SourceStats
from .sources import SourceEntry, SourceTrust, SourceType

try:
    from .health_checker import (
        HealthChecker,
        HealthStatus,
        ServerHealth,
        ServerValidator,
        filter_healthy_servers,
        sort_by_quality,
    )
except ImportError:
    pass

# Pipeline orchestrator (always available — no optional deps beyond requests)
try:
    from .pipeline import Pipeline, PipelineResult, StopController
except ImportError:  # pragma: no cover
    pass

__version__ = "1.0.0"


# ---------------------------------------------------------------------------
# High-level convenience API  (V1-A3)
# ---------------------------------------------------------------------------


def find_servers(
    *,
    check_health: bool = True,
    check_google_204: bool = False,
    timeout: float = 5.0,
    min_quality_score: float = 0.0,
    limit: Optional[int] = None,
    github_token: Optional[str] = None,
    max_configs_per_source: int = 5_000,
    max_total_configs: Optional[int] = 50_000,
    binary_path: Optional[str] = None,
) -> List[str]:
    """Fetch, deduplicate, health-check, and score V2Ray configs in one call.

    This is the recommended entry point for library users who want working
    configs without managing :class:`Pipeline` directly.

    All parameters are keyword-only.

    Parameters
    ----------
    check_health:
        Run TCP health checks (Layer 1).  Keeps only reachable servers.
        Default: ``True``.
    check_google_204:
        Run xray SOCKS5 / Google 204 probe (Layer 3).  Slower but
        ground-truth.  Default: ``False``.
    timeout:
        Per-server probe timeout in seconds.  Default: ``5.0``.
    min_quality_score:
        Drop servers scoring below this threshold (0–100).
        Default: ``0.0`` (keep all).
    limit:
        Return at most *limit* configs, highest-scored first.
        Default: ``None`` (return all).
    github_token:
        Optional GitHub personal-access token.  Raises the API rate
        limit from 60 to 5 000 requests/hour when provided.
    max_configs_per_source:
        Maximum configs retained per source after parsing.
        Default: ``5_000``.
    max_total_configs:
        Maximum configs retained globally after dedup, before health
        checks.  Pass ``None`` to disable.  Default: ``50_000``.
    binary_path:
        Explicit path to the xray binary (Layer 3 only).

    Returns
    -------
    List[str]
        Config strings sorted by quality score (best first).  Returns an
        empty list if no configs were found or all were filtered out.

    Examples
    --------
    Fetch up to 100 healthy configs::

        configs = v2ray_finder.find_servers(limit=100)

    Fetch with a GitHub token and strict quality filter::

        configs = v2ray_finder.find_servers(
            github_token="ghp_...",
            min_quality_score=60.0,
            limit=50,
        )
    """
    pipeline = Pipeline(
        check_health=check_health,
        check_google_204=check_google_204,
        timeout=timeout,
        min_quality_score=min_quality_score,
        limit=limit,
        github_token=github_token,
        max_configs_per_source=max_configs_per_source,
        max_total_configs=max_total_configs,
        binary_path=binary_path,
    )
    result = pipeline.run()
    return result.top_configs or result.configs


__all__ = [
    # High-level API
    "find_servers",
    # Core (legacy)
    "V2RayServerFinder",
    # Exceptions
    "V2RayFinderError",
    "GitHubAPIError",
    "RateLimitError",
    "AuthenticationError",
    "ConfigParseError",
    "ParseError",
    "ErrorType",
    # Normalizer
    "NormalizedServer",
    "normalize_server",
    "deduplicate_servers",
    "deduplicate_across_sources",
    # Result monad
    "Ok",
    "Err",
    "Result",
    # Sources
    "SourceRegistry",
    "SourceStats",
    "SourceEntry",
    "SourceType",
    "SourceTrust",
    # Health checker (optional)
    "HealthChecker",
    "ServerHealth",
    "HealthStatus",
    "ServerValidator",
    "filter_healthy_servers",
    "sort_by_quality",
    # Pipeline
    "Pipeline",
    "PipelineResult",
    "StopController",
]

# xray real-connectivity layer (optional)
try:
    from .xray_config_adapter import ConfigAdapter, UnsupportedProtocolError
    from .xray_connectivity import (
        RealConnectivityChecker,
        RealHealthResult,
        _ResultCache,
        find_free_port,
    )
    from .xray_runner import (
        _COMMON_INSTALL_DIRS,
        XrayBinaryManager,
        XrayBinaryNotFoundError,
        XrayRunner,
    )
except ImportError:
    pass
