"""V2Ray server finder - Search and collect V2Ray configs from GitHub"""

__version__ = "0.5.0"
__author__ = "Ali Sadeghi Aghili"
__email__ = "alisadeghiaghili@gmail.com"

from .core import V2RayServerFinder
from .exceptions import (
    AuthenticationError,
    ErrorType,
    GitHubAPIError,
    NetworkError,
    ParseError,
    RateLimitError,
    RepositoryNotFoundError,
    TimeoutError,
    V2RayFinderError,
    ValidationError,
)
from .health_checker import (
    HealthChecker,
    HealthStatus,
    ServerHealth,
    ServerValidator,
    filter_healthy_servers,
    sort_by_quality,
)
from .normalizer import (
    NormalizedServer,
    deduplicate_across_sources,
    deduplicate_servers,
    normalize_server,
)
from .result import Err, Ok, Result
from .scorer import ServerScore, score_server, score_servers
from .source_registry import SourceRegistry, SourceStats
from .sources import (
    GITHUB_TOPICS,
    STATIC_SOURCES,
    SourceEntry,
    SourceTrust,
    SourceType,
    get_enabled_sources,
)

# xray real-connectivity layer (optional — gracefully absent if aiohttp-socks
# or the xray binary is not installed)
try:
    from .xray_connectivity import RealConnectivityChecker, RealHealthResult, find_free_port
    from .xray_runner import XrayBinaryManager
    from .xray_config_adapter import ConfigAdapter
except ImportError:
    pass

__all__ = [
    # Core
    "V2RayServerFinder",
    # Health checker (TCP/HTTP)
    "HealthChecker",
    "ServerHealth",
    "HealthStatus",
    "ServerValidator",
    "filter_healthy_servers",
    "sort_by_quality",
    # xray real-connectivity
    "RealConnectivityChecker",
    "RealHealthResult",
    "XrayBinaryManager",
    "ConfigAdapter",
    "find_free_port",
    # Normalizer
    "NormalizedServer",
    "normalize_server",
    "deduplicate_servers",
    "deduplicate_across_sources",
    # Scorer
    "ServerScore",
    "score_server",
    "score_servers",
    # Source registry
    "SourceRegistry",
    "SourceStats",
    # Sources
    "STATIC_SOURCES",
    "GITHUB_TOPICS",
    "SourceEntry",
    "SourceType",
    "SourceTrust",
    "get_enabled_sources",
    # Exceptions
    "V2RayFinderError",
    "ErrorType",
    "NetworkError",
    "TimeoutError",
    "GitHubAPIError",
    "RateLimitError",
    "AuthenticationError",
    "RepositoryNotFoundError",
    "ParseError",
    "ValidationError",
    # Result
    "Result",
    "Ok",
    "Err",
]
