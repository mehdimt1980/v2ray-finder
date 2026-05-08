"""V2Ray server finder - Search and collect V2Ray configs from GitHub"""

__version__ = "0.4.0"
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

__all__ = [
    "V2RayServerFinder",
    "HealthChecker",
    "ServerHealth",
    "HealthStatus",
    "ServerValidator",
    "filter_healthy_servers",
    "sort_by_quality",
    "NormalizedServer",
    "normalize_server",
    "deduplicate_servers",
    "deduplicate_across_sources",
    "ServerScore",
    "score_server",
    "score_servers",
    "SourceRegistry",
    "SourceStats",
    "STATIC_SOURCES",
    "GITHUB_TOPICS",
    "SourceEntry",
    "SourceType",
    "SourceTrust",
    "get_enabled_sources",
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
    "Result",
    "Ok",
    "Err",
]
