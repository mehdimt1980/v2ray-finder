"""Core module for V2Ray server discovery with improved error handling."""

import logging
import os
import re
import threading
from datetime import datetime
from typing import Dict, Generator, List, Optional, Tuple, Union

import requests

from .cache import CacheManager
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
from .result import Err, Ok, Result
from .sources import STATIC_SOURCES, GITHUB_TOPICS, get_enabled_sources
from .source_registry import SourceRegistry
from .normalizer import deduplicate_servers, deduplicate_across_sources
from .scorer import score_servers

logger = logging.getLogger(__name__)


class V2RayServerFinder:
    """
    V2Ray server finder that aggregates configs from GitHub and curated sources.

    Attributes:
        BASE_URL: GitHub API base URL
        DIRECT_SOURCES: Backward-compatible list of curated subscription URLs
                        (derived from STATIC_SOURCES in sources.py)
    """

    BASE_URL = "https://api.github.com"

    # Backward-compat alias — use STATIC_SOURCES from sources.py for the full catalogue
    DIRECT_SOURCES = [s.url for s in STATIC_SOURCES if s.enabled]

    TOKEN_ENV_VAR = "GITHUB_TOKEN"

    def __init__(
        self,
        token: Optional[str] = None,
        raise_errors: bool = False,
        cache_backend: str = "memory",
        cache_ttl_repos: int = 3600,
        cache_ttl_urls: int = 1800,
        cache_enabled: bool = True,
        # Real-time health check settings
        realtime_health_check: bool = False,
        health_timeout: float = 5.0,
        health_concurrent_limit: int = 50,
        health_enable_google_204: bool = True,
        health_enable_http_check: bool = True,
    ):
        """
        Initialize V2RayServerFinder.

        Args:
            token: Optional GitHub personal access token.
            raise_errors: If True, raise exceptions instead of returning empty results.
            cache_backend: 'memory' (default) or 'disk'.
            cache_ttl_repos: TTL in seconds for GitHub search/repo-files cache.
            cache_ttl_urls: TTL in seconds for URL content cache.
            cache_enabled: Set False to disable caching.
            realtime_health_check: When True, every server is health-checked
                immediately as it is discovered. Only servers that pass
                TCP connectivity are included in results.
            health_timeout: Timeout in seconds for each health check method.
            health_concurrent_limit: Max concurrent async health checks.
            health_enable_google_204: Include Google 204 connectivity check.
            health_enable_http_check: Include HTTP-level reachability check.
        """
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        self.raise_errors = raise_errors
        self._last_rate_limit_info: Optional[Dict] = None
        self._token_source: str = "none"

        self._stop_requested = threading.Event()
        self._lock = threading.Lock()

        self._cache_ttl_repos = cache_ttl_repos
        self._cache_ttl_urls = cache_ttl_urls

        self._cache = CacheManager(
            backend=cache_backend,
            ttl=cache_ttl_repos,
            enabled=cache_enabled,
        )
        logger.debug(
            f"Cache initialised: backend={cache_backend}, "
            f"ttl_repos={cache_ttl_repos}s, ttl_urls={cache_ttl_urls}s, "
            f"enabled={cache_enabled}"
        )

        # Real-time health check config
        self.realtime_health_check = realtime_health_check
        self._health_timeout = health_timeout
        self._health_concurrent_limit = health_concurrent_limit
        self._health_enable_google_204 = health_enable_google_204
        self._health_enable_http_check = health_enable_http_check
        self._health_checker = None  # Lazy init

        # Source registry — tracks per-source runtime stats
        self._source_registry = SourceRegistry()

        if token is None:
            token = os.environ.get(self.TOKEN_ENV_VAR)
            if token:
                self._token_source = "environment"
                logger.debug(
                    f"Using GitHub token from {self.TOKEN_ENV_VAR} environment variable"
                )
        else:
            self._token_source = "parameter"
            logger.warning(
                "Security Warning: GitHub token passed as parameter. "
                f"Consider using {self.TOKEN_ENV_VAR} environment variable instead."
            )

        if token:
            token = self._validate_and_sanitize_token(token)
            if token:
                self.headers["Authorization"] = f"token {token}"
                logger.info(f"GitHub token configured from {self._token_source}")
            else:
                logger.warning(
                    "Invalid token format - proceeding without authentication (rate limit: 60/hour)"
                )
        else:
            logger.info(
                "No GitHub token provided - using unauthenticated access (rate limit: 60/hour)"
            )

    # ------------------------------------------------------------------
    # Health checker lazy init
    # ------------------------------------------------------------------

    def _get_health_checker(self):
        """Lazy-initialise and return the HealthChecker instance."""
        if self._health_checker is None:
            try:
                from .health_checker import HealthChecker
                self._health_checker = HealthChecker(
                    timeout=self._health_timeout,
                    concurrent_limit=self._health_concurrent_limit,
                    enable_google_204=self._health_enable_google_204,
                    enable_http_check=self._health_enable_http_check,
                )
            except ImportError:
                logger.warning("health_checker module not available; skipping health checks")
        return self._health_checker

    def _passes_realtime_check(self, config: str) -> bool:
        """Return True if config passes the real-time health check (fail-open)."""
        checker = self._get_health_checker()
        if checker is None:
            return True
        try:
            health = checker.check_server_now(config)
            ok = health.tcp_ok
            logger.debug(
                f"Real-time health: tcp={health.tcp_ok} http={health.http_ok} "
                f"g204={health.google_204_ok} latency={health.latency_ms:.1f}ms "
                f"-> {'PASS' if ok else 'FAIL'} {config[:60]}"
            )
            return ok
        except Exception as e:
            logger.debug(f"Real-time health check raised: {e} — letting server through")
            return True

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def clear_cache(self) -> bool:
        success = self._cache.clear()
        if success:
            logger.info("Cache cleared")
        return success

    def get_cache_stats(self) -> Dict:
        return self._cache.get_stats()

    # ------------------------------------------------------------------
    # Stop mechanism
    # ------------------------------------------------------------------

    def request_stop(self):
        self._stop_requested.set()
        logger.info("Stop requested - operations will terminate gracefully")

    def reset_stop(self):
        self._stop_requested.clear()

    def should_stop(self) -> bool:
        return self._stop_requested.is_set()

    # ------------------------------------------------------------------
    # Token validation
    # ------------------------------------------------------------------

    def _validate_and_sanitize_token(self, token: str) -> Optional[str]:
        token = token.strip()
        if not token:
            logger.error("Empty token provided")
            return None
        if len(token) < 20:
            logger.error(
                f"Token too short ({len(token)} chars). GitHub tokens are typically 40+ characters."
            )
            return None
        if not re.match(r"^[a-zA-Z0-9_]+$", token):
            logger.error(
                "Token contains invalid characters. GitHub tokens should be alphanumeric."
            )
            return None
        known_prefixes = ["ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"]
        has_known_prefix = any(token.startswith(prefix) for prefix in known_prefixes)
        if not has_known_prefix:
            logger.warning(
                f"Token doesn't start with a known GitHub prefix ({', '.join(known_prefixes)}). "
                "This might be an old token format or invalid token."
            )
        token_preview = f"{token[:4]}...{token[-4:]}" if len(token) > 8 else "****"
        logger.debug(
            f"Token validated: {token_preview} ({len(token)} chars, source: {self._token_source})"
        )
        return token

    # ------------------------------------------------------------------
    # Class-method constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        raise_errors: bool = False,
        cache_backend: str = "memory",
        cache_ttl_repos: int = 3600,
        cache_ttl_urls: int = 1800,
        cache_enabled: bool = True,
        realtime_health_check: bool = False,
        health_timeout: float = 5.0,
        health_enable_google_204: bool = True,
        health_enable_http_check: bool = True,
    ) -> "V2RayServerFinder":
        """Create V2RayServerFinder instance using token from environment variable."""
        return cls(
            token=None,
            raise_errors=raise_errors,
            cache_backend=cache_backend,
            cache_ttl_repos=cache_ttl_repos,
            cache_ttl_urls=cache_ttl_urls,
            cache_enabled=cache_enabled,
            realtime_health_check=realtime_health_check,
            health_timeout=health_timeout,
            health_enable_google_204=health_enable_google_204,
            health_enable_http_check=health_enable_http_check,
        )

    # ------------------------------------------------------------------
    # Rate-limit helpers
    # ------------------------------------------------------------------

    def _check_rate_limit(self, response: requests.Response) -> None:
        if response.status_code == 403 or response.status_code == 429:
            limit = response.headers.get("X-RateLimit-Limit")
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset = response.headers.get("X-RateLimit-Reset")
            self._last_rate_limit_info = {
                "limit": int(limit) if limit else None,
                "remaining": int(remaining) if remaining else None,
                "reset": int(reset) if reset else None,
            }
            if remaining == "0" or response.status_code == 429:
                raise RateLimitError(
                    limit=self._last_rate_limit_info["limit"],
                    remaining=self._last_rate_limit_info["remaining"],
                    reset_time=self._last_rate_limit_info["reset"],
                )
        else:
            limit = response.headers.get("X-RateLimit-Limit")
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset = response.headers.get("X-RateLimit-Reset")
            if limit and remaining:
                try:
                    self._last_rate_limit_info = {
                        "limit": int(limit),
                        "remaining": int(remaining),
                        "reset": int(reset) if reset else None,
                    }
                    if int(remaining) < 10:
                        logger.warning(
                            f"GitHub API rate limit low: {remaining}/{limit} remaining."
                        )
                except (ValueError, TypeError):
                    pass

    def get_rate_limit_info(self) -> Optional[Dict]:
        return self._last_rate_limit_info.copy() if self._last_rate_limit_info else None

    # ------------------------------------------------------------------
    # Core API methods (with caching)
    # ------------------------------------------------------------------

    def search_repos(
        self, keywords: Optional[List[str]] = None, max_results: int = 30
    ) -> Result[List[Dict], V2RayFinderError]:
        if self.should_stop():
            logger.info("Search repos stopped by user request")
            return Ok([])

        if keywords is None:
            keywords = ["v2ray", "free", "config"]

        cache_key = self._cache._make_key("search_repos", sorted(keywords), max_results)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"search_repos cache hit for keywords={keywords}")
            return Ok(cached)

        query = "+".join(keywords)
        url = f"{self.BASE_URL}/search/repositories"
        params = {
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": min(max_results, 100),
        }

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            if response.status_code == 401:
                raise AuthenticationError("Invalid or expired GitHub token")
            elif response.status_code == 404:
                raise GitHubAPIError("GitHub API endpoint not found", status_code=404)
            self._check_rate_limit(response)
            response.raise_for_status()
            data = response.json()

            results = []
            for repo in data.get("items", []):
                if self.should_stop():
                    logger.info(f"Search repos interrupted after {len(results)} repos")
                    break
                results.append(
                    {
                        "name": repo["name"],
                        "full_name": repo["full_name"],
                        "description": repo.get("description", ""),
                        "stars": repo["stargazers_count"],
                        "updated_at": repo["updated_at"],
                        "url": repo["html_url"],
                    }
                )

            logger.info(f"Found {len(results)} repositories matching '{query}'")
            if not self.should_stop():
                self._cache.set(cache_key, results, ttl=self._cache_ttl_repos)
            return Ok(results)

        except RateLimitError as e:
            logger.error(f"GitHub rate limit exceeded: {e}")
            return Err(e)
        except AuthenticationError as e:
            logger.error(f"Authentication failed: {e}")
            return Err(e)
        except GitHubAPIError as e:
            logger.error(str(e))
            return Err(e)
        except requests.exceptions.Timeout as e:
            error = TimeoutError(
                "Request timed out while searching repositories", url=url, timeout=10.0
            )
            logger.error(str(error))
            return Err(error)
        except requests.exceptions.ConnectionError as e:
            error = NetworkError(
                f"Connection error while searching repositories: {e}", url=url
            )
            logger.error(str(error))
            return Err(error)
        except requests.exceptions.RequestException as e:
            error = GitHubAPIError(
                f"GitHub API request failed: {e}",
                status_code=(
                    getattr(response, "status_code", None)
                    if "response" in locals()
                    else None
                ),
            )
            logger.error(str(error))
            return Err(error)
        except Exception as e:
            error = V2RayFinderError(
                f"Unexpected error during repository search: {e}",
                ErrorType.UNKNOWN_ERROR,
            )
            logger.error(str(error), exc_info=True)
            return Err(error)

    def search_repos_or_empty(
        self, keywords: Optional[List[str]] = None, max_results: int = 30
    ) -> List[Dict]:
        result = self.search_repos(keywords, max_results)
        if result.is_ok():
            return result.unwrap()
        else:
            if self.raise_errors:
                raise result.error
            return []

    def get_repo_files(
        self, repo_full_name: str, path: str = ""
    ) -> Result[List[Dict], V2RayFinderError]:
        if self.should_stop():
            return Ok([])

        cache_key = self._cache._make_key("get_repo_files", repo_full_name, path)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return Ok(cached)

        url = f"{self.BASE_URL}/repos/{repo_full_name}/contents/{path}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 404:
                raise RepositoryNotFoundError(repo_full_name)
            elif response.status_code == 401:
                raise AuthenticationError()
            self._check_rate_limit(response)
            response.raise_for_status()
            files = response.json()

            config_files = []
            for file in files if isinstance(files, list) else [files]:
                if self.should_stop():
                    break
                if file.get("type") == "file":
                    name_lower = file["name"].lower()
                    if any(
                        ext in name_lower for ext in [".txt", ".json", "config", "sub"]
                    ):
                        config_files.append(
                            {
                                "name": file["name"],
                                "path": file["path"],
                                "download_url": file.get("download_url"),
                                "size": file["size"],
                            }
                        )

            logger.info(f"Found {len(config_files)} config files in {repo_full_name}")
            if not self.should_stop():
                self._cache.set(cache_key, config_files, ttl=self._cache_ttl_repos)
            return Ok(config_files)

        except (RateLimitError, AuthenticationError, RepositoryNotFoundError) as e:
            logger.error(str(e))
            return Err(e)
        except requests.exceptions.Timeout as e:
            error = TimeoutError(
                f"Request timed out while fetching files from {repo_full_name}",
                url=url, timeout=10.0,
            )
            logger.error(str(error))
            return Err(error)
        except requests.exceptions.ConnectionError as e:
            error = NetworkError(f"Connection error while fetching files: {e}", url=url)
            logger.error(str(error))
            return Err(error)
        except requests.exceptions.RequestException as e:
            error = GitHubAPIError(f"Failed to fetch files from {repo_full_name}: {e}")
            logger.error(str(error))
            return Err(error)
        except Exception as e:
            error = V2RayFinderError(
                f"Unexpected error while fetching files: {e}", ErrorType.UNKNOWN_ERROR
            )
            logger.error(str(error), exc_info=True)
            return Err(error)

    def get_repo_files_or_empty(
        self, repo_full_name: str, path: str = ""
    ) -> List[Dict]:
        result = self.get_repo_files(repo_full_name, path)
        if result.is_ok():
            return result.unwrap()
        else:
            if self.raise_errors:
                raise result.error
            return []

    def _parse_servers(self, content: str) -> List[str]:
        servers = []
        supported_protocols = ["vmess://", "vless://", "trojan://", "ss://", "ssr://"]
        for line in content.split("\n"):
            if self.should_stop():
                break
            line = line.strip()
            if any(line.startswith(p) for p in supported_protocols):
                servers.append(line)
        return servers

    def _get_servers_from_repo(self, repo: Dict) -> List[str]:
        """Fetch all config files from a single repo dict and return server strings."""
        servers: List[str] = []
        files_result = self.get_repo_files(repo["full_name"])
        if files_result.is_err():
            return servers
        for file in files_result.unwrap():
            if self.should_stop():
                break
            if file["download_url"]:
                url_result = self.get_servers_from_url(file["download_url"])
                if url_result.is_ok():
                    servers.extend(url_result.unwrap())
        return servers

    def get_servers_from_url(
        self, url: str, timeout: float = 10.0
    ) -> Result[List[str], V2RayFinderError]:
        if self.should_stop():
            return Ok([])

        cache_key = self._cache._make_key("get_servers_from_url", url)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"get_servers_from_url cache hit for {url}")
            return Ok(cached)

        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            servers = self._parse_servers(response.text)
            servers, dupes = deduplicate_servers(servers, source_url=url)
            logger.info(
                f"Fetched {len(servers)} servers from {url}"
                + (f" ({dupes} structural dupes removed)" if dupes else "")
            )
            self._source_registry.record_success(url, len(servers))
            if not self.should_stop():
                self._cache.set(cache_key, servers, ttl=self._cache_ttl_urls)
            return Ok(servers)
        except requests.exceptions.Timeout as e:
            error = TimeoutError(
                f"Request timed out while fetching from {url}", url=url, timeout=timeout
            )
            logger.error(str(error))
            self._source_registry.record_failure(url)
            return Err(error)
        except requests.exceptions.ConnectionError as e:
            error = NetworkError(f"Connection error: {e}", url=url)
            logger.error(str(error))
            self._source_registry.record_failure(url)
            return Err(error)
        except requests.exceptions.RequestException as e:
            error = NetworkError(f"Failed to fetch from {url}: {e}", url=url)
            logger.error(str(error))
            self._source_registry.record_failure(url)
            return Err(error)
        except Exception as e:
            error = ParseError(f"Error parsing content from {url}: {e}")
            logger.error(str(error), exc_info=True)
            self._source_registry.record_failure(url)
            return Err(error)

    def get_servers_from_url_or_empty(
        self, url: str, timeout: float = 10.0
    ) -> List[str]:
        result = self.get_servers_from_url(url, timeout)
        if result.is_ok():
            return result.unwrap()
        else:
            if self.raise_errors:
                raise result.error
            return []

    # ------------------------------------------------------------------
    # Generator-based discovery pipeline
    # ------------------------------------------------------------------

    def _iter_raw_servers(self, use_github_search: bool = False) -> Generator[str, None, None]:
        """Internal generator — yields raw server config strings as they are found."""
        seen: set = set()

        try:
            for url in self.DIRECT_SOURCES:
                if self.should_stop():
                    return
                result = self.get_servers_from_url(url)
                if result.is_ok():
                    for server in result.unwrap():
                        if self.should_stop():
                            return
                        if server not in seen:
                            seen.add(server)
                            yield server
                else:
                    if self.raise_errors:
                        raise result.error
        except KeyboardInterrupt:
            logger.info("Discovery interrupted via Ctrl+C (known sources)")
            self.request_stop()
            return

        if not use_github_search:
            return

        try:
            search_keywords = ["free-v2ray", "v2ray-config"]
            for keyword in search_keywords:
                if self.should_stop():
                    return
                repos_result = self.search_repos(keywords=[keyword, "v2ray"], max_results=10)
                if repos_result.is_err():
                    if self.raise_errors:
                        raise repos_result.error
                    continue
                for repo in repos_result.unwrap():
                    if self.should_stop():
                        return
                    files_result = self.get_repo_files(repo["full_name"])
                    if files_result.is_err():
                        if self.raise_errors:
                            raise files_result.error
                        continue
                    for file in files_result.unwrap():
                        if self.should_stop():
                            return
                        if file["download_url"]:
                            servers_result = self.get_servers_from_url(file["download_url"])
                            if servers_result.is_ok():
                                for server in servers_result.unwrap():
                                    if self.should_stop():
                                        return
                                    if server not in seen:
                                        seen.add(server)
                                        yield server
                            else:
                                if self.raise_errors:
                                    raise servers_result.error
        except KeyboardInterrupt:
            logger.info("Discovery interrupted via Ctrl+C (GitHub search)")
            self.request_stop()

    def _iter_servers_with_realtime_health(
        self, use_github_search: bool = False
    ) -> Generator[str, None, None]:
        """Generator — yields only servers that pass real-time health checks."""
        total = 0
        passed = 0
        for server in self._iter_raw_servers(use_github_search=use_github_search):
            if self.should_stop():
                break
            total += 1
            if self._passes_realtime_check(server):
                passed += 1
                yield server
            else:
                logger.debug(f"Real-time health FAIL — dropped: {server[:60]}")
        logger.info(f"Real-time health check complete: {passed}/{total} servers passed")

    # ------------------------------------------------------------------
    # High-level discovery methods
    # ------------------------------------------------------------------

    def get_servers_from_github(
        self, search_keywords: Optional[List[str]] = None, max_repos: int = 10
    ) -> List[str]:
        """Search GitHub and extract servers from found repositories."""
        if search_keywords is None:
            search_keywords = ["free-v2ray", "v2ray-config"]

        all_servers: List[str] = []
        errors = []

        try:
            for keyword in search_keywords:
                if self.should_stop():
                    break
                repos_result = self.search_repos(keywords=[keyword, "v2ray"], max_results=max_repos)
                if repos_result.is_err():
                    errors.append(repos_result.error)
                    if self.raise_errors:
                        raise repos_result.error
                    continue
                for repo in repos_result.unwrap()[:max_repos]:
                    if self.should_stop():
                        break
                    files_result = self.get_repo_files(repo["full_name"])
                    if files_result.is_err():
                        errors.append(files_result.error)
                        if self.raise_errors:
                            raise files_result.error
                        continue
                    for file in files_result.unwrap():
                        if self.should_stop():
                            break
                        if file["download_url"]:
                            servers_result = self.get_servers_from_url(file["download_url"])
                            if servers_result.is_ok():
                                all_servers.extend(servers_result.unwrap())
                            else:
                                errors.append(servers_result.error)
                                if self.raise_errors:
                                    raise servers_result.error
        except KeyboardInterrupt:
            logger.info(
                f"GitHub search interrupted via Ctrl+C — returning {len(all_servers)} partial results"
            )
            self.request_stop()

        if errors:
            logger.warning(f"Encountered {len(errors)} errors during GitHub search")

        return list(dict.fromkeys(all_servers))

    def get_servers_from_known_sources(self) -> List[str]:
        """Fetch servers from curated known sources with cross-source deduplication."""
        all_servers: List[str] = []
        errors = []
        try:
            for url in self.DIRECT_SOURCES:
                if self.should_stop():
                    break
                result = self.get_servers_from_url(url)
                if result.is_ok():
                    all_servers.extend(result.unwrap())
                else:
                    errors.append(result.error)
                    if self.raise_errors:
                        raise result.error
        except KeyboardInterrupt:
            logger.info(
                f"Known sources fetch interrupted via Ctrl+C — returning {len(all_servers)} partial results"
            )
            self.request_stop()

        if errors:
            logger.warning(
                f"Failed to fetch from {len(errors)}/{len(self.DIRECT_SOURCES)} sources"
            )

        # Cross-source structural dedup + feed overlap ratios back to registry
        deduped, overlap_map = deduplicate_across_sources({"_combined": all_servers})
        for u, ratio in overlap_map.items():
            self._source_registry.update_overlap(u, ratio)
        return list(deduped)

    def get_all_servers(self, use_github_search: bool = False) -> List[str]:
        """Get all servers from known sources and optionally GitHub search.

        When realtime_health_check=True (set in constructor), every server is
        health-checked immediately as it is discovered.
        """
        if self.realtime_health_check:
            logger.info("Real-time health check enabled — filtering servers during discovery")
            return list(
                self._iter_servers_with_realtime_health(
                    use_github_search=use_github_search
                )
            )

        servers = self.get_servers_from_known_sources()
        if use_github_search and not self.should_stop():
            github_servers = self.get_servers_from_github()
            servers.extend(github_servers)
            servers, _ = deduplicate_servers(servers, source_url="_merged")
        return servers

    def get_servers_sorted(
        self, limit: Optional[int] = None, use_github_search: bool = False
    ) -> List[Dict]:
        servers = self.get_all_servers(use_github_search=use_github_search)
        server_list = []
        for i, server in enumerate(servers, 1):
            if self.should_stop():
                break
            protocol = server.split("://")[0] if "://" in server else "unknown"
            server_list.append(
                {
                    "index": i,
                    "protocol": protocol,
                    "config": server,
                    "fetched_at": datetime.now().isoformat(),
                }
            )
        if limit:
            server_list = server_list[:limit]
        return server_list

    def get_servers_with_health(
        self,
        use_github_search: bool = False,
        check_health: bool = True,
        health_timeout: float = 5.0,
        concurrent_checks: int = 50,
        min_quality_score: float = 0.0,
        filter_unhealthy: bool = False,
        health_batch_size: int = 50,
    ) -> List[Dict]:
        """Get servers with optional batch health checking."""
        servers = self.get_all_servers(use_github_search=use_github_search)

        if self.should_stop() or not check_health:
            return [
                {
                    "config": server,
                    "protocol": server.split("://")[0] if "://" in server else "unknown",
                    "health_checked": False,
                }
                for server in servers
            ]

        try:
            from .health_checker import (
                HealthChecker,
                filter_healthy_servers,
                sort_by_quality,
            )
        except ImportError:
            logger.warning("Health checker not available, returning servers without health info")
            return [
                {
                    "config": server,
                    "protocol": server.split("://")[0] if "://" in server else "unknown",
                    "health_checked": False,
                }
                for server in servers
            ]

        server_tuples = [
            (server, server.split("://")[0] if "://" in server else "unknown")
            for server in servers
        ]

        checker = HealthChecker(
            timeout=health_timeout,
            concurrent_limit=concurrent_checks,
            enable_google_204=self._health_enable_google_204,
            enable_http_check=self._health_enable_http_check,
        )

        logger.info(f"Batch health checking {len(server_tuples)} servers (batch_size={health_batch_size})...")
        health_results = []
        try:
            for i in range(0, len(server_tuples), health_batch_size):
                if self.should_stop():
                    logger.info(f"Health check stopped by user after {len(health_results)} servers")
                    break
                batch = server_tuples[i: i + health_batch_size]
                batch_results = checker.check_servers(batch)
                health_results.extend(batch_results)
        except KeyboardInterrupt:
            logger.info(f"Health check interrupted via Ctrl+C after {len(health_results)} servers")
            self.request_stop()

        if filter_unhealthy or min_quality_score > 0:
            health_results = filter_healthy_servers(
                health_results,
                min_quality_score=min_quality_score,
                exclude_unreachable=filter_unhealthy,
            )

        health_results = sort_by_quality(health_results, descending=True)

        return [
            {
                "config": health.config,
                "protocol": health.protocol,
                "health_checked": True,
                "health_status": health.status.value,
                "latency_ms": health.latency_ms,
                "quality_score": health.quality_score,
                "host": health.host,
                "port": health.port,
                "error": health.error,
                "validation_error": health.validation_error,
                "tcp_ok": health.tcp_ok,
                "http_ok": health.http_ok,
                "google_204_ok": health.google_204_ok,
                "check_methods": health.check_methods,
            }
            for health in health_results
        ]

    # ------------------------------------------------------------------
    # Topic-based discovery (faz 1 dynamic path)
    # ------------------------------------------------------------------

    def get_servers_from_topic_discovery(
        self,
        topics: Optional[List[str]] = None,
        max_repos_per_topic: int = 5,
    ) -> List[str]:
        """Discover servers via GitHub topic search.

        Args:
            topics: GitHub topics to search. Defaults to GITHUB_TOPICS from sources.py.
            max_repos_per_topic: Max repos to inspect per topic.

        Returns:
            Structurally-deduplicated list of server config strings.
        """
        if topics is None:
            topics = GITHUB_TOPICS
        all_servers: List[str] = []
        seen_repos: set = set()
        for topic in topics:
            if self.should_stop():
                break
            try:
                result = self.search_repos(keywords=[topic, "v2ray"], max_results=max_repos_per_topic * 2)
                if result.is_err():
                    continue
                for repo in result.unwrap()[:max_repos_per_topic]:
                    if self.should_stop():
                        break
                    repo_key = repo.get("full_name", "")
                    if not repo_key or repo_key in seen_repos:
                        continue
                    seen_repos.add(repo_key)
                    all_servers.extend(self._get_servers_from_repo(repo))
            except Exception as exc:
                logger.warning(f"Topic discovery failed for {topic!r}: {exc}")

        deduped, _ = deduplicate_across_sources({"_topic": all_servers})
        deduped_list = list(deduped)
        logger.info(
            f"get_servers_from_topic_discovery: {len(deduped_list)} servers "
            f"from {len(seen_repos)} repos across {len(topics)} topics"
        )
        return deduped_list

    # ------------------------------------------------------------------
    # Source registry accessor
    # ------------------------------------------------------------------

    def get_source_registry(self) -> SourceRegistry:
        """Return the live SourceRegistry for this run.

        Useful for inspecting per-source reliability stats after fetching::

            finder = V2RayServerFinder.from_env()
            finder.get_all_servers()
            print(finder.get_source_registry().summary())
        """
        return self._source_registry

    # ------------------------------------------------------------------
    # Scored output (faz 4)
    # ------------------------------------------------------------------

    def get_scored_servers(
        self,
        use_github_search: bool = False,
        check_health: bool = True,
        health_timeout: float = 5.0,
        concurrent_checks: int = 50,
        min_score: float = 0.0,
    ) -> List[Dict]:
        """Fetch, health-check, and score all servers.

        Returns servers ranked by composite quality score (highest first).
        Each dict includes standard health-check fields plus:
        - ``score``: ServerScore object
        - ``total_score``: float 0.0-1.0
        - ``grade``: str (A/B/C/D/F)
        """
        health_results = self.get_servers_with_health(
            use_github_search=use_github_search,
            check_health=check_health,
            health_timeout=health_timeout,
            concurrent_checks=concurrent_checks,
        )
        trust_map = {s.url: s.trust.value for s in STATIC_SOURCES}
        overlap_map = {s.url: s.overlap_ratio for s in self._source_registry.all_stats()}
        scored = score_servers(health_results, source_trust_map=trust_map, overlap_map=overlap_map)

        result_list = []
        for sc in scored:
            if sc.total < min_score:
                continue
            base = next((h for h in health_results if h.get("config") == sc.config), {})
            merged = dict(base)
            merged.update({"score": sc, "total_score": sc.total, "grade": sc.grade})
            result_list.append(merged)

        logger.info(f"get_scored_servers: {len(result_list)} servers (min_score={min_score})")
        return result_list

    # ------------------------------------------------------------------
    # File output
    # ------------------------------------------------------------------

    def save_to_file(
        self,
        filename: str = "v2ray_servers.txt",
        limit: Optional[int] = None,
        use_github_search: bool = False,
        check_health: bool = False,
        filter_unhealthy: bool = False,
        min_quality_score: float = 0.0,
    ) -> Tuple[int, str]:
        if check_health:
            servers_data = self.get_servers_with_health(
                use_github_search=use_github_search,
                check_health=True,
                filter_unhealthy=filter_unhealthy,
                min_quality_score=min_quality_score,
            )
            servers = [s["config"] for s in servers_data]
        else:
            servers = self.get_all_servers(use_github_search=use_github_search)

        if limit:
            servers = servers[:limit]

        with open(filename, "w", encoding="utf-8") as f:
            for server in servers:
                f.write(f"{server}\n")

        logger.info(f"Saved {len(servers)} servers to {filename}")
        return len(servers), filename
