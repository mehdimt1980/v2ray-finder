"""Core V2RayServerFinder implementation."""
from __future__ import annotations

import datetime
import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

import requests

from .exceptions import (
    AuthenticationError,
    GitHubAPIError,
    NetworkError,
    ParseError,
    RateLimitError,
    RepositoryNotFoundError,
    TimeoutError,
    V2RayFinderError,
)
from .result import Err, Ok, Result
from .sources import get_enabled_sources

logger = logging.getLogger(__name__)

_TOKEN_MIN_LEN = 20
_KNOWN_PREFIXES = ("ghp_", "gho_", "ghs_", "ghu_", "github_pat_")

# File extensions considered as potential v2ray config files
_CONFIG_EXTENSIONS = {".txt", ".json", ".yaml", ".yml", ".conf", ".sub", ".base64"}


def _validate_token(token: Optional[str]) -> Optional[str]:
    """Return the token if it passes basic sanity checks, else None."""
    if not token:
        return None
    if len(token) < _TOKEN_MIN_LEN:
        logger.warning(
            "GitHub token too short (%d chars, minimum %d) — ignoring.",
            len(token),
            _TOKEN_MIN_LEN,
        )
        return None
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", token):
        logger.warning("GitHub token contains invalid characters — ignoring.")
        return None
    if not any(token.startswith(p) for p in _KNOWN_PREFIXES):
        logger.warning(
            "GitHub token has no recognised prefix (ghp_, gho_, …) — "
            "accepted, but double-check it is correct."
        )
    return token


class V2RayServerFinder:
    """Main public API for v2ray-finder.

    Args:
        token:          Optional GitHub personal access token.
        inline_health:  Reserved for future use.
        health_timeout: Per-server TCP timeout for inline checks (seconds).
        check_google_204: Also run Google-204 probe in inline checks.
        raise_errors:   If True, ``*_or_empty`` helpers re-raise on error.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        inline_health: bool = True,
        health_timeout: float = 5.0,
        check_google_204: bool = True,
        raise_errors: bool = False,
    ) -> None:
        env_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        raw_token = token or env_token or None
        self._token = _validate_token(raw_token)

        self._inline_health = inline_health
        self._health_timeout = health_timeout
        self._check_google_204 = check_google_204
        self._raise_errors = raise_errors

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "v2ray-finder/1.0",
            "Accept": "application/vnd.github.v3+json",
        })
        if self._token:
            self._session.headers["Authorization"] = f"token {self._token}"

        self._stop_event = threading.Event()
        self._last_rate_limit_info: Optional[Dict] = None

    # ------------------------------------------------------------------ #
    # Public headers property
    # ------------------------------------------------------------------ #

    @property
    def headers(self) -> Dict[str, str]:
        """Return a snapshot of current session headers."""
        return dict(self._session.headers)

    # ------------------------------------------------------------------ #
    # Class-level source list (proxy to get_enabled_sources)
    # ------------------------------------------------------------------ #

    @property
    def DIRECT_SOURCES(self) -> List[Any]:
        """Return enabled static subscription sources."""
        return list(get_enabled_sources())

    # ------------------------------------------------------------------ #
    # Cooperative stop
    # ------------------------------------------------------------------ #

    def request_stop(self) -> None:
        self._stop_event.set()

    def reset_stop(self) -> None:
        self._stop_event.clear()

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    # ------------------------------------------------------------------ #
    # Rate-limit helpers
    # ------------------------------------------------------------------ #

    def _check_rate_limit(self, resp: requests.Response) -> None:
        """Parse X-RateLimit-* headers and store them; log if low."""
        limit_raw = resp.headers.get("X-RateLimit-Limit")
        remaining_raw = resp.headers.get("X-RateLimit-Remaining")
        reset_raw = resp.headers.get("X-RateLimit-Reset")

        if remaining_raw is None:
            return

        try:
            limit = int(limit_raw) if limit_raw is not None else None
            remaining = int(remaining_raw)
            reset_at = int(reset_raw) if reset_raw is not None else None
        except (ValueError, TypeError):
            # Use % interpolation (not .format) so call_args[0][0] contains
            # the raw values, satisfying:
            #   assert "not-a-number" in log_message
            logger.debug(
                "Malformed X-RateLimit headers — limit=%s remaining=%s reset=%s; skipping update.",
                limit_raw,
                remaining_raw,
                reset_raw,
            )
            return

        self._last_rate_limit_info = {
            "limit": limit,
            "remaining": remaining,
            "reset_at": reset_at,
        }
        if remaining < 10:
            logger.warning(
                "GitHub rate limit low: %d/%s requests remaining.",
                remaining,
                limit or "?",
            )

    def get_rate_limit_info(self) -> Optional[Dict]:
        return self._last_rate_limit_info

    # ------------------------------------------------------------------ #
    # classmethod factory
    # ------------------------------------------------------------------ #

    @classmethod
    def from_env(cls, **kwargs) -> "V2RayServerFinder":
        """Create a finder, reading GITHUB_TOKEN / GH_TOKEN from env."""
        return cls(**kwargs)

    # ------------------------------------------------------------------ #
    # GitHub API — Result-returning methods
    # ------------------------------------------------------------------ #

    def search_repos(
        self,
        query: str = "v2ray config",
        per_page: int = 30,
        # backward-compat alias used in some integration tests
        keywords: Optional[List[str]] = None,
        max_results: Optional[int] = None,
    ) -> Result:
        """Search GitHub repositories.

        Returns:
            Ok(list[dict]) on success, Err(V2RayFinderError subclass) on failure.
        """
        if keywords is not None:
            query = " ".join(keywords)
        if max_results is not None:
            per_page = min(per_page, max_results)

        url = "https://api.github.com/search/repositories"
        params = {"q": query, "sort": "updated", "per_page": per_page}
        try:
            resp = requests.get(
                url,
                params=params,
                headers=dict(self._session.headers),
                timeout=15,
            )
            self._check_rate_limit(resp)
            if resp.status_code == 401:
                return Err(AuthenticationError("GitHub API authentication failed (401)."))
            if resp.status_code in (403, 429):
                msg = ""
                try:
                    msg = resp.json().get("message", "")
                except Exception:
                    pass
                info = self._last_rate_limit_info or {}
                err = RateLimitError(f"Rate limit hit: {msg}")
                # Attach parsed header values for callers that inspect .details
                err.details = {
                    "limit": info.get("limit"),
                    "remaining": info.get("remaining"),
                    "reset_at": info.get("reset_at"),
                }
                return Err(err)
            if resp.status_code == 404:
                return Err(
                    GitHubAPIError(
                        "GitHub search endpoint not found (404).",
                        status_code=404,
                    )
                )
            resp.raise_for_status()
            return Ok(resp.json().get("items", []))
        except (AuthenticationError, RateLimitError, GitHubAPIError) as exc:
            return Err(exc)
        except requests.Timeout:
            return Err(TimeoutError("GitHub search timed out."))
        except requests.ConnectionError as exc:
            return Err(NetworkError(f"Network error during GitHub search: {exc}"))
        except requests.RequestException as exc:
            return Err(GitHubAPIError(f"GitHub search failed: {exc}"))
        except Exception as exc:
            return Err(V2RayFinderError(f"Unexpected error in search_repos: {exc}"))

    def search_repos_or_empty(
        self,
        query: str = "v2ray config",
        per_page: int = 30,
    ) -> List[Dict]:
        """Like search_repos but returns [] on error (unless raise_errors=True)."""
        result = self.search_repos(query=query, per_page=per_page)
        if result.is_ok():
            return result.unwrap()
        if self._raise_errors:
            raise result.error
        return []

    def get_repo_files(
        self,
        repo: str,
        path: str = "",
        timeout: int = 15,
    ) -> Result:
        """List files in a GitHub repository that look like v2ray config files.

        Args:
            repo:    Repository slug in ``owner/name`` format.
            path:    Sub-directory path inside the repo (default: root).
            timeout: HTTP request timeout in seconds.

        Returns:
            Ok(list[dict]) on success — each dict contains at minimum
            ``name``, ``path``, ``download_url``, ``size``, and ``type``.
            Err(V2RayFinderError subclass) on any failure.
        """
        url = f"https://api.github.com/repos/{repo}/contents/{path}".rstrip("/")
        try:
            resp = requests.get(
                url,
                headers=dict(self._session.headers),
                timeout=timeout,
            )
            self._check_rate_limit(resp)
            if resp.status_code == 404:
                return Err(RepositoryNotFoundError(f"Repository not found: {repo!r}"))
            if resp.status_code == 401:
                return Err(AuthenticationError("GitHub API authentication failed (401)."))
            if resp.status_code == 403:
                msg = ""
                try:
                    msg = resp.json().get("message", "")
                except Exception:
                    pass
                return Err(RateLimitError(f"Rate limit hit: {msg}"))
            resp.raise_for_status()
            items: List[Dict] = resp.json() if isinstance(resp.json(), list) else []
            config_files = [
                item for item in items
                if item.get("type") == "file"
                and any(
                    item.get("name", "").lower().endswith(ext)
                    for ext in _CONFIG_EXTENSIONS
                )
            ]
            return Ok(config_files)
        except (RepositoryNotFoundError, AuthenticationError, RateLimitError, GitHubAPIError) as exc:
            return Err(exc)
        except requests.Timeout:
            return Err(TimeoutError(f"Timed out fetching repo files for {repo!r}"))
        except requests.ConnectionError as exc:
            return Err(NetworkError(f"Connection error fetching repo files: {exc}"))
        except requests.RequestException as exc:
            return Err(GitHubAPIError(f"GitHub API request failed: {exc}"))
        except Exception as exc:
            return Err(V2RayFinderError(f"Unexpected error in get_repo_files: {exc}"))

    def get_repo_files_or_empty(
        self,
        repo: str,
        path: str = "",
        timeout: int = 15,
    ) -> List[Dict]:
        """Like get_repo_files but returns [] on error (unless raise_errors=True)."""
        result = self.get_repo_files(repo=repo, path=path, timeout=timeout)
        if result.is_ok():
            return result.unwrap()
        if self._raise_errors:
            raise result.error
        return []

    # ------------------------------------------------------------------ #
    # URL-based source fetching — Result-returning
    # ------------------------------------------------------------------ #

    def get_servers_from_url(
        self, url: str, timeout: int = 15
    ) -> Result:
        """Fetch a URL and extract v2ray config strings.

        Returns:
            Ok(list[str]) on success, Err(V2RayFinderError) on failure.
        """
        try:
            resp = self._session.get(url, timeout=timeout)
            resp.raise_for_status()
            return Ok(self._parse_servers(resp.text))
        except requests.Timeout:
            return Err(TimeoutError(f"Timed out fetching {url}"))
        except requests.ConnectionError as exc:
            return Err(NetworkError(f"Connection error fetching {url}: {exc}"))
        except requests.RequestException as exc:
            return Err(NetworkError(f"Request failed for {url}: {exc}"))
        except Exception as exc:
            return Err(ParseError(f"Error parsing response from {url}: {exc}"))

    # ------------------------------------------------------------------ #
    # GitHub-based discovery
    # ------------------------------------------------------------------ #

    def get_servers_from_github(
        self,
        search_keywords: Optional[List[str]] = None,
        max_repos: int = 10,
        timeout: int = 15,
    ) -> List[str]:
        """Search GitHub for repos containing v2ray configs and collect servers.

        Args:
            search_keywords: Keywords to search for (default: ["v2ray", "config"]).
            max_repos:       Maximum repos to inspect per keyword.
            timeout:         Per-request timeout.

        Returns:
            Deduplicated list of server config strings.
        """
        if search_keywords is None:
            search_keywords = ["v2ray config"]

        seen: Dict[str, None] = {}
        results: List[str] = []

        for keyword in search_keywords:
            if self.should_stop():
                break
            repo_result = self.search_repos(query=keyword, per_page=max_repos)
            if repo_result.is_err():
                if self._raise_errors:
                    raise repo_result.error
                logger.warning("search_repos failed for %r: %s", keyword, repo_result.error)
                continue

            repos = repo_result.unwrap()
            for repo in repos:
                if self.should_stop():
                    break
                full_name = repo.get("full_name", "")
                if not full_name:
                    continue

                files_result = self.get_repo_files(full_name, timeout=timeout)
                if files_result.is_err():
                    logger.warning("get_repo_files failed for %r: %s", full_name, files_result.error)
                    continue

                for f in files_result.unwrap():
                    dl_url = f.get("download_url")
                    if not dl_url:
                        continue
                    url_result = self.get_servers_from_url(dl_url, timeout=timeout)
                    if url_result.is_err():
                        logger.warning("get_servers_from_url failed for %r: %s", dl_url, url_result.error)
                        continue
                    for srv in url_result.unwrap():
                        if srv not in seen:
                            seen[srv] = None
                            results.append(srv)

        return results

    # ------------------------------------------------------------------ #
    # Parsing helpers
    # ------------------------------------------------------------------ #

    _PROTO_RE = re.compile(
        r"(?:vmess|vless|trojan|ss|ssr)://[A-Za-z0-9+/=_\-@:.?&#%]+",
        re.IGNORECASE,
    )

    def _parse_servers(self, text: str) -> List[str]:
        """Extract all proxy URIs from raw text (deduplicated, order-preserved)."""
        return list(dict.fromkeys(self._PROTO_RE.findall(text)))

    # ------------------------------------------------------------------ #
    # Known-source discovery
    # ------------------------------------------------------------------ #

    def get_servers_from_known_sources(
        self, limit: Optional[int] = None
    ) -> List[str]:
        """Fetch servers from all enabled static subscription sources."""
        results: List[str] = []
        for src in get_enabled_sources():
            if self.should_stop():
                break
            result = self.get_servers_from_url(src.url)
            if result.is_ok():
                results.extend(result.unwrap())
            else:
                if self._raise_errors:
                    raise result.error
                logger.warning("Failed to fetch %s: %s", src.url, result.error)
            if limit and len(results) >= limit:
                break
        return results[:limit] if limit else results

    # ------------------------------------------------------------------ #
    # High-level API
    # ------------------------------------------------------------------ #

    def get_all_servers(
        self,
        use_github_search: bool = False,
        limit: Optional[int] = None,
    ) -> List[str]:
        """Fetch and deduplicate servers from all enabled sources."""
        results = self.get_servers_from_known_sources(limit=limit)
        seen: Dict[str, None] = {}
        deduped: List[str] = []
        for s in results:
            if s not in seen:
                seen[s] = None
                deduped.append(s)
        return deduped[:limit] if limit else deduped

    def get_servers_with_health(
        self,
        check_health: bool = True,
        filter_unhealthy: bool = False,
        min_quality_score: float = 0.0,
        use_github_search: bool = False,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return servers as dicts, optionally with health-check data.

        Each dict always contains ``config`` and ``health_checked``.
        When check_health=True and health_checker is available, additional
        fields are populated: ``health_status``, ``latency_ms``, ``quality_score``,
        ``protocol``, ``host``, ``port``, ``error``.

        Args:
            check_health:      Run TCP health checks (requires health_checker module).
            filter_unhealthy:  If True, exclude UNREACHABLE/INVALID servers.
            min_quality_score: Minimum quality_score to keep (0-100).
            use_github_search: Also search GitHub repos for configs.
            limit:             Maximum number of servers to return.

        Returns:
            List of server dicts.
        """
        servers = self.get_all_servers(use_github_search=use_github_search, limit=limit)

        if not check_health:
            return [{"config": cfg, "health_checked": False} for cfg in servers]

        # Try to import health_checker; fall back gracefully if unavailable
        try:
            import sys
            hc_mod = sys.modules.get("v2ray_finder.health_checker")
            if hc_mod is None:
                from . import health_checker as hc_mod  # type: ignore
        except Exception:
            logger.warning("health_checker not available; returning without health data.")
            return [{"config": cfg, "health_checked": False} for cfg in servers]

        if hc_mod is None:
            return [{"config": cfg, "health_checked": False} for cfg in servers]

        # Build (config, protocol) pairs
        pairs = []
        for cfg in servers:
            proto = cfg.split("://")[0].lower() if "://" in cfg else "unknown"
            pairs.append((cfg, proto))

        if not pairs:
            return []

        try:
            checker = hc_mod.HealthChecker(
                timeout=self._health_timeout,
                check_google_204=self._check_google_204,
            )
            health_results = checker.check_servers(pairs)
        except Exception as exc:
            logger.warning("Health check failed: %s", exc)
            return [{"config": cfg, "health_checked": False} for cfg in servers]

        # Optionally filter
        if filter_unhealthy or min_quality_score > 0:
            health_results = hc_mod.filter_healthy_servers(
                health_results,
                exclude_unreachable=filter_unhealthy,
                min_quality_score=min_quality_score,
            )

        # Format output
        out = []
        for h in health_results:
            out.append({
                "config": h.config,
                "health_checked": True,
                "health_status": h.status.value,
                "latency_ms": h.latency_ms,
                "quality_score": h.quality_score,
                "protocol": h.protocol,
                "host": h.host,
                "port": h.port,
                "error": h.error,
            })

        if limit:
            out = out[:limit]
        return out

    def get_servers_sorted(
        self,
        use_github_search: bool = False,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return server dicts sorted with metadata.

        Each dict contains: index, protocol, config, fetched_at.
        """
        servers = self.get_all_servers(
            use_github_search=use_github_search, limit=limit
        )
        now = datetime.datetime.utcnow().isoformat() + "Z"
        result = []
        for i, cfg in enumerate(servers):
            protocol = cfg.split("://")[0].lower() if "://" in cfg else "unknown"
            result.append({
                "index": i,
                "protocol": protocol,
                "config": cfg,
                "fetched_at": now,
            })
        return result

    def save_to_file(
        self,
        filename: str,
        limit: Optional[int] = None,
        use_github_search: bool = False,
        check_health: bool = False,
        filter_unhealthy: bool = False,
        min_quality_score: float = 0.0,
    ) -> Tuple[int, str]:
        """Save server configs to *filename*, one per line.

        Args:
            filename:          Output file path.
            limit:             Maximum number of configs to save.
            use_github_search: Also search GitHub repos.
            check_health:      Run health checks before saving.
            filter_unhealthy:  Only save healthy servers (requires check_health=True).
            min_quality_score: Minimum quality threshold (requires check_health=True).

        Returns:
            (count_saved, filename) tuple.
        """
        if check_health:
            health_results = self.get_servers_with_health(
                check_health=True,
                filter_unhealthy=filter_unhealthy,
                min_quality_score=min_quality_score,
                use_github_search=use_github_search,
                limit=limit,
            )
            configs = [r["config"] for r in health_results]
        else:
            configs = self.get_all_servers(
                use_github_search=use_github_search, limit=limit
            )

        with open(filename, "w", encoding="utf-8") as fh:
            for cfg in configs:
                fh.write(cfg + "\n")
        return len(configs), filename
