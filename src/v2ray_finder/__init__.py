"""v2ray-finder: Fetch and aggregate V2Ray server configurations from GitHub."""

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
from .sources import SourceEntry, SourceType, SourceTrust

try:
    from .health_checker import (
        HealthChecker,
        ServerHealth,
        HealthStatus,
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

__version__ = "0.6.0"

__all__ = [
    # Core
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
    from .xray_connectivity import (
        RealConnectivityChecker,
        RealHealthResult,
        _ResultCache,
        find_free_port,
    )
    from .xray_runner import (
        XrayBinaryManager,
        XrayBinaryNotFoundError,
        XrayRunner,
        _COMMON_INSTALL_DIRS,
    )
    from .xray_config_adapter import ConfigAdapter, UnsupportedProtocolError
except ImportError:
    pass
