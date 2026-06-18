"""Core V2RayServerFinder implementation."""
from __future__ import annotations

import datetime
import logging
import os
import re
import time
import warnings
from typing import Any, Dict, List, Optional, Tuple

import requests

from .exceptions import (
    AuthenticationError,
    GitHubAPIError,
    GitHubRateLimitError,
    NetworkError,
    ParseError,
    RepositoryNotFoundError,
    TimeoutError,
    V2RayFinderError,
)
from .result import Err, Ok, Result
from .sources import SourceEntry, get_enabled_sources

logger = logging.getLogger(__name__)

_CONFIG_EXTENSIONS = {".txt", ".json", ".yaml", ".yml", ".conf", ".sub", ".base64"}

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _validate_token(token: str) -> bool:
    """Return True only if token is at least 20 chars and alphanumeric/dash/underscore.

    Emits a warning when the token is silently dropped so users can diagnose
    authentication issues without digging into logs.
    """
    if len(token) < 20:
        logger.warning(
            "GitHub token ignored: too short (%d chars, need ≥20). "
            "Check your GITHUB_TOKEN or token= argument.",
            len(token),
        )
        return False
    if not _TOKEN_RE.match(token):
        logger.warning(
            "GitHub token ignored: contains invalid characters. "
            "Only A-Z, a-z, 0-9, '-', '_' are permitted.",
        )
        return False
    return True


class V2RayServerFinder:
    """Main entry point for discovering v2ray / clash proxy configs.

    Args:
        github_token:   Optional GitHub personal-access token for higher
                        rate limits when searching repositories.
        token:          Alias for github_token (either name accepted).
        raise_errors:   If True, ``*_or_empty`` helpers re-raise on error.
                        Default is False (return empty list / Result.err).
        health_timeout: Per-server TCP timeout used by health-check helpers.
        check_google_204: Include a Google-204 liveness check in health checks.
    """

    # ---------------------------------------------------------------------- #
    # Construction
    # ---------------------------------------------------------------------- #

    def __init__(
        self,
        github_token: Optional[str] = None,
        token: Optional[str] = None,
        raise_errors: bool = False,
        health_timeout: float = 5.0,
        check_google_204: bool = False,
    ) -> None:
        self._raise_errors    = raise_errors
        self._health_timeout  = health_timeout
        self._check_google_204 = check_google_204
        self._stop_requested  = False
        # Initialized as None; only populated after a successful header parse
        self._last_rate_limit_info: Optional[Dict[str, Any]] = None

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "v2ray-finder/1.0 (github.com/alisadeghiaghili/v2ray-finder)",
            # Tests expect the v3+json media type
            "Accept":     "application/vnd.github.v3+json",
        })

        # Resolve token: explicit param wins, then env var
        effective_token = token or github_token or os.environ.get("GITHUB_TOKEN")
        if effective_token and _validate_token(effective_token):
            self._session.headers["Authorization"] = f"token {effective_token}"

    # ---------------------------------------------------------------------- #
    # Stop / cancellation
    # ---------------------------------------------------------------------- #

    def request_stop(self) -> None:
        """Signal all running discovery loops to exit cleanly."""
        self._stop_requested = True

    def should_stop(self) -> bool:
        return self._stop_requested

    def reset_stop(self) -> None:
        self._stop_requested = False

    @property
    def headers(self) -> Dict[str, str]:
        """Return current session headers as a plain dict."""
        return dict(self._session.headers)

    @classmethod
    def from_env(cls, **kwargs) -> "V2RayServerFinder":
        """Construct a finder using GITHUB_TOKEN environment variable.

        Note: ``token`` is not a valid keyword argument here; use
        ``github_token`` if you need to pass a token explicitly alongside
        other kwargs without triggering a TypeError.
        """
        # Prevent a caller who also passes token= from silently winning over
        # the env-var resolution done in __init__.
        kwargs.pop("token", None)
        return cls(github_token=os.environ.get("GITHUB_TOKEN"), **kwargs)

    def get_rate_limit_info(self) -> Optional[Dict[str, Any]]:
        """Return the last observed rate-limit headers, or None if not yet seen."""
        return self._last_rate_limit_info

    # ---------------------------------------------------------------------- #
    # Rate-limit tracking
    # ---------------------------------------------------------------------- #

    def _check_rate_limit(self, response: requests.Response) -> None:
        """Inspect GitHub rate-limit headers and warn when approaching the limit."""
        limit_raw     = response.headers.get("X-RateLimit-Limit")
        remaining_raw = response.headers.get("X-RateLimit-Remaining")
        reset_raw     = response.headers.get("X-RateLimit-Reset")

        if limit_raw is None and remaining_raw is None:
            return

        try:
            limit     = int(limit_raw)     if limit_raw     is not None else None
            remaining = int(remaining_raw) if remaining_raw is not None else None
            reset     = int(reset_raw)     if reset_raw     is not None else None
        except (TypeError, ValueError):
            logger.debug(
                "Malformed X-RateLimit headers — limit=%r"
                " remaining=%r reset=%r; skipping update.",
                limit_raw, remaining_raw, reset_raw,
            )
            # Do NOT update state when parsing fails
            return

        # Only update state on a successful parse
        self._last_rate_limit_info = {
            "limit": limit,
            "remaining": remaining,
            "reset": reset,
        }

        if remaining is None:
            return

        if remaining == 0:
            reset_dt = (
                datetime.datetime.fromtimestamp(reset, tz=datetime.timezone.utc)
                if reset is not None else None
            )
            raise GitHubRateLimitError(
                limit=limit or 0,
                remaining=0,
                reset_at=reset_dt,
            )

        if limit and remaining < limit * 0.1:
            logger.warning(
                "GitHub rate-limit low: %d/%d remaining (resets at %s).",
                remaining,
                limit,
                datetime.datetime.fromtimestamp(reset, tz=datetime.timezone.utc)
                if reset else "unknown",
            )

    # ---------------------------------------------------------------------- #
    # Low-level HTTP helpers
    # ---------------------------------------------------------------------- #

    def _get(
        self,
        url: str,
        *,
        timeout: int = 15,
        stream: bool = False,
    ) -> Result:
        """Perform a GET request; return Ok(response) or Err(V2RayFinderError)."""
        try:
            resp = self._session.get(url, timeout=timeout, stream=stream)
            self._check_rate_limit(resp)
            resp.raise_for_status()
            return Ok(resp)
        except GitHubRateLimitError as exc:
            return Err(exc)
        except requests.exceptions.ConnectionError as exc:
            return Err(NetworkError(str(exc)))
        except requests.exceptions.Timeout as exc:
            return Err(NetworkError(f"Timeout fetching {url}: {exc}"))
        except requests.exceptions.HTTPError as exc:
            return Err(NetworkError(f"HTTP {exc.response.status_code} for {url}"))
        except requests.exceptions.RequestException as exc:
            return Err(NetworkError(str(exc)))

    # ---------------------------------------------------------------------- #
    # GitHub search
    # ---------------------------------------------------------------------- #

    def search_repos(
        self,
        query: str = "v2ray config",
        per_page: int = 10,
        timeout: int = 15,
    ) -> Result:
        """Search GitHub repositories by *query*.

        Returns:
            Ok(list[dict]) on success, Err(GitHubAPIError) on failure.
        """
        url    = "https://api.github.com/search/repositories"
        params = {"q": query, "per_page": per_page, "sort": "updated"}
        try:
            resp = self._session.get(url, params=params, timeout=timeout)

            # Check authentication failures BEFORE calling _check_rate_limit,
            # so a missing/wrong token is not misreported as a rate-limit error.
            if resp.status_code in (401, 403):
                return Err(AuthenticationError("GitHub authentication failed."))

            self._check_rate_limit(resp)

            if resp.status_code == 422:
                return Err(GitHubAPIError(f"Invalid search query: {query!r}"))
            resp.raise_for_status()
            data = resp.json()
            return Ok(data.get("items", []))
        except (GitHubRateLimitError, AuthenticationError, GitHubAPIError) as exc:
            return Err(exc)
        except requests.exceptions.Timeout as exc:
            return Err(TimeoutError(str(exc)))
        except requests.exceptions.ConnectionError as exc:
            return Err(NetworkError(str(exc)))
        except requests.exceptions.RequestException as exc:
            return Err(GitHubAPIError(str(exc)))

    def search_repos_or_empty(
        self,
        query: str = "v2ray config",
        per_page: int = 10,
        timeout: int = 15,
    ) -> List[Dict[str, Any]]:
        """Like search_repos but returns [] on error (unless raise_errors=True)."""
        result = self.search_repos(query=query, per_page=per_page, timeout=timeout)
        if result.is_err():
            if self._raise_errors:
                raise result.error
            logger.debug("search_repos_or_empty failed: %s", result.error)
            return []
        return result.unwrap()

    # ---------------------------------------------------------------------- #
    # Repository file listing
    # ---------------------------------------------------------------------- #

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
            Only files whose extension is in ``_CONFIG_EXTENSIONS`` are returned.
            Err(V2RayFinderError subclass) on any failure.
        """
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        try:
            resp = requests.get(
                url,
                headers=dict(self._session.headers),
                timeout=timeout,
            )
            self._check_rate_limit(resp)
            if resp.status_code == 404:
                return Err(RepositoryNotFoundError(repo))
            if resp.status_code == 401:
                return Err(AuthenticationError("Authentication required for this repo."))
            resp.raise_for_status()
            items = resp.json()
            if isinstance(items, list):
                filtered = [
                    item for item in items
                    if item.get("type") == "file"
                    and os.path.splitext(item.get("name", ""))[1].lower()
                    in _CONFIG_EXTENSIONS
                ]
                return Ok(filtered)
            # Single file response
            if isinstance(items, dict):
                name = items.get("name", "")
                if os.path.splitext(name)[1].lower() in _CONFIG_EXTENSIONS:
                    return Ok([items])
                return Ok([])
            return Ok([])
        except (RepositoryNotFoundError, AuthenticationError, GitHubRateLimitError) as exc:
            return Err(exc)
        except requests.exceptions.Timeout as exc:
            return Err(TimeoutError(f"Timeout fetching repo {repo}: {exc}"))
        except requests.exceptions.ConnectionError as exc:
            return Err(NetworkError(str(exc)))
        except requests.exceptions.RequestException as exc:
            return Err(GitHubAPIError(str(exc)))
        except Exception as exc:
            return Err(V2RayFinderError(str(exc)))

    def get_repo_files_or_empty(
        self,
        repo: str,
        path: str = "",
        timeout: int = 15,
    ) -> List[Dict[str, Any]]:
        """Like get_repo_files but returns [] on error (unless raise_errors=True)."""
        result = self.get_repo_files(repo=repo, path=path, timeout=timeout)
        if result.is_err():
            if self._raise_errors:
                raise result.error
            logger.debug("get_repo_files_or_empty failed for %r: %s", repo, result.error)
            return []
        return result.unwrap()

    # ---------------------------------------------------------------------- #
    # Config-string fetching
    # ---------------------------------------------------------------------- #

    def get_servers_from_url(
        self,
        url: str,
        timeout: int = 15,
    ) -> Result:
        """Fetch raw config strings from a subscription URL.

        Returns:
            Ok(list[str]) — deduplicated list of proxy URI strings.
            Err(V2RayFinderError) on network / parse failure.
        """
        try:
            resp = requests.get(
                url,
                headers=dict(self._session.headers),
                timeout=timeout,
            )
            if resp.status_code != 200:
                return Err(NetworkError(f"HTTP {resp.status_code} for {url}"))
            servers = self._parse_servers(resp.text)
            return Ok(servers)
        except requests.exceptions.Timeout as exc:
            return Err(TimeoutError(f"Timeout fetching {url}: {exc}"))
        except requests.exceptions.RequestException as exc:
            return Err(NetworkError(str(exc)))
        except Exception as exc:
            return Err(ParseError(f"Failed to parse response from {url}: {exc}"))

    def get_servers_from_url_or_empty(
        self,
        url: str,
        timeout: int = 15,
    ) -> List[str]:
        """Like get_servers_from_url but returns [] on error (unless raise_errors=True)."""
        result = self.get_servers_from_url(url=url, timeout=timeout)
        if result.is_err():
            if self._raise_errors:
                raise result.error
            logger.debug("get_servers_from_url_or_empty failed for %r: %s", url, result.error)
            return []
        return result.unwrap()

    # ---------------------------------------------------------------------- #
    # GitHub repo discovery
    # ---------------------------------------------------------------------- #

    def get_servers_from_github(
        self,
        search_keywords: Optional[List[str]] = None,
        max_repos: int = 10,
        timeout: int = 15,
        progress_callback=None,
    ) -> List[str]:
        """Search GitHub and return raw config strings from discovered repos.

        Args:
            search_keywords: Keywords to use for GitHub search (default: v2ray presets).
            max_repos:       Maximum number of repos to scan.
            timeout:         Per-request timeout.
            progress_callback: Optional callable(current, total, message).

        Returns:
            Flat list of raw config strings (vmess://, vless://, etc.).
        """
        keywords = search_keywords or ["v2ray config", "v2ray subscription", "clash config"]
        all_servers: List[str] = []

        for keyword in keywords:
            if self.should_stop():
                break
            try:
                result = self.search_repos(query=keyword, per_page=max_repos)
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt in get_servers_from_github (search) — stopping.")
                self.request_stop()
                break
            if result.is_err():
                if self._raise_errors:
                    raise result.error
                logger.warning("search_repos failed for %r: %s", keyword, result.error)
                continue

            repos = result.unwrap()
            for i, repo in enumerate(repos):
                if self.should_stop():
                    break
                full_name = repo.get("full_name", "")
                if not full_name:
                    continue

                if progress_callback:
                    progress_callback(i, len(repos), f"Scanning {full_name}")

                files_result = self.get_repo_files(full_name, timeout=timeout)
                if files_result.is_err():
                    continue

                for file_info in files_result.unwrap():
                    if self.should_stop():
                        break
                    dl_url = file_info.get("download_url")
                    if not dl_url:
                        continue
                    _, ext = os.path.splitext(file_info.get("name", ""))
                    if ext.lower() not in _CONFIG_EXTENSIONS:
                        continue
                    try:
                        url_result = self.get_servers_from_url(dl_url, timeout=timeout)
                    except KeyboardInterrupt:
                        logger.info("KeyboardInterrupt in get_servers_from_github (url) — stopping.")
                        self.request_stop()
                        return all_servers
                    if url_result.is_ok():
                        all_servers.extend(url_result.unwrap())

        return all_servers

    # ---------------------------------------------------------------------- #
    # Known static subscription sources
    # ---------------------------------------------------------------------- #

    def get_servers_from_known_sources(
        self,
        timeout: int = 15,
        progress_callback=None,
    ) -> Dict[str, List[str]]:
        """Fetch v2ray configs from built-in known subscription URLs.

        Returns:
            Dict mapping source URL → list of raw config strings for that
            source.  Callers that only need a flat list can call
            ``list(itertools.chain.from_iterable(result.values()))``.
        """
        sources = get_enabled_sources()
        servers_by_source: Dict[str, List[str]] = {}
        total = len(sources)

        for i, source in enumerate(sources):
            if self.should_stop():
                break
            if progress_callback:
                progress_callback(i, total, f"Fetching {source.label}")
            try:
                result = self.get_servers_from_url(source.url, timeout=timeout)
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt in get_servers_from_known_sources — stopping.")
                self.request_stop()
                break
            if result.is_ok():
                servers_by_source[source.url] = result.unwrap()
            else:
                if self._raise_errors:
                    raise result.error
                logger.warning("Failed to fetch source %r: %s", source.label, result.error)

        return servers_by_source

    # ---------------------------------------------------------------------- #
    # Unified high-level API
    # ---------------------------------------------------------------------- #

    def get_all_servers(
        self,
        use_github_search: bool = False,
        limit: Optional[int] = None,
    ) -> Tuple[List[str], Dict[str, float]]:
        """Fetch and deduplicate servers from all enabled sources.

        Uses structural fingerprinting (SHA-256 of protocol+host+port+cred)
        via :func:`normalizer.deduplicate_across_sources` to remove duplicates
        that are textually different but structurally identical.

        Args:
            use_github_search: Also search GitHub repos for configs.
            limit:             Maximum number of servers to return.

        Returns:
            ``(configs, overlap_map)`` where *configs* is a deduplicated list
            of raw config strings and *overlap_map* is a dict mapping each
            source URL to its overlap ratio (fraction of its configs that also
            appear in at least one other source).  Pass *overlap_map* to
            ``scorer.score_servers`` for the uniqueness dimension.
        """
        from .normalizer import deduplicate_across_sources

        servers_by_source = self.get_servers_from_known_sources()

        if use_github_search:
            github_servers = self.get_servers_from_github()
            if github_servers:
                servers_by_source["__github__"] = github_servers

        configs, overlap_map = deduplicate_across_sources(servers_by_source)

        if limit:
            configs = configs[:limit]
        return configs, overlap_map

    def save_to_file(
        self,
        filename: str,
        limit: Optional[int] = None,
        use_github_search: bool = False,
        check_health: bool = False,
    ) -> tuple:
        """Fetch servers and write them to a file.

        Args:
            filename:          Output file path.
            limit:             Maximum number of servers to write.
            use_github_search: Also search GitHub repos for configs.
            check_health:      Run health checks before writing.

        Returns:
            Tuple of (count_written, filename).
        """
        if check_health:
            raw, overlap_map = self.get_all_servers(use_github_search=use_github_search)
            health_results = self.get_servers_with_health(raw, overlap_map=overlap_map)
            configs = [r["config"] for r in health_results]
        else:
            configs, _ = self.get_all_servers(use_github_search=use_github_search)
        if limit:
            configs = configs[:limit]
        with open(filename, "w", encoding="utf-8") as fh:
            for cfg in configs:
                fh.write(cfg + "\n")
        return len(configs), filename

    # ---------------------------------------------------------------------- #
    # Health-checked discovery
    # ---------------------------------------------------------------------- #

    def get_servers_with_health(
        self,
        servers: Optional[List[str]] = None,
        timeout: float = 5.0,
        min_quality_score: float = 0.0,
        progress_callback=None,
        check_health: bool = True,
        use_github_search: bool = False,
        limit: Optional[int] = None,
        health_batch_size: int = 100,
        overlap_map: Optional[Dict[str, float]] = None,
        **kwargs,
    ):
        """Run health checks on a list of config strings.

        Args:
            servers:           List of raw config strings. If None, fetched via
                               get_all_servers(use_github_search, limit).
            timeout:           Per-server TCP timeout.
            min_quality_score: Filter out servers below this score.
            progress_callback: Optional callable(current, total, message).
            check_health:      When False, skip health checks and return dicts
                               with health_checked=False immediately.
            use_github_search: Passed to get_all_servers when servers is None.
            limit:             Passed to get_all_servers when servers is None.
            health_batch_size: Number of servers per health-check batch.
            overlap_map:       Optional {source_url: overlap_ratio} from
                               get_all_servers; used to populate overlap_ratio
                               on each result dict for scoring.

        Returns:
            List of dicts — health-checked results or plain
            {config, health_checked: False} when check_health=False or
            should_stop() is True.
        """
        resolved_overlap_map: Dict[str, float] = overlap_map or {}

        if servers is None:
            servers, resolved_overlap_map = self.get_all_servers(
                use_github_search=use_github_search,
                limit=limit,
            )

        if not check_health or self.should_stop():
            return [{"config": cfg, "health_checked": False} for cfg in servers]

        # Build a quick lookup: config -> source_url, source_trust
        # so we can annotate each result with scoring metadata.
        source_lookup = self._build_source_lookup()

        try:
            from .health_checker import HealthChecker, filter_healthy_servers
        except (ImportError, ModuleNotFoundError):
            logger.warning("health_checker module unavailable — returning unchecked servers.")
            return [{"config": cfg, "health_checked": False} for cfg in servers]

        checker = HealthChecker(
            timeout=timeout,
            min_quality_score=min_quality_score,
        )

        if progress_callback:
            progress_callback(0, len(servers), "Starting health checks…")

        batch_size = health_batch_size
        all_results = []

        for batch_start in range(0, len(servers), batch_size):
            if self.should_stop():
                break
            batch = servers[batch_start:batch_start + batch_size]
            try:
                batch_results = checker.check_batch(batch)
                all_results.extend(batch_results)
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt during health check batch — stopping.")
                self.request_stop()
                break

            if progress_callback:
                progress_callback(
                    min(batch_start + batch_size, len(servers)),
                    len(servers),
                    "Health checks in progress…",
                )

        if progress_callback:
            progress_callback(len(servers), len(servers), "Health checks complete.")

        healthy = filter_healthy_servers(all_results, min_quality_score=min_quality_score)

        # Annotate each result dict with source metadata for scorer
        result_dicts = []
        for h in healthy:
            src_url, src_trust = source_lookup.get(h.config, ("", 1))
            overlap = resolved_overlap_map.get(src_url, 0.0)
            d = {
                "config":        h.config,
                "protocol":      h.protocol,
                "tcp_ok":        h.tcp_ok,
                "http_ok":       h.http_probe_ok,
                "google_204_ok": h.google_204_ok,
                "latency_ms":    h.latency_ms,
                "health_checked": True,
                "source_url":    src_url,
                "source_trust":  src_trust,
                "overlap_ratio": overlap,
            }
            result_dicts.append(d)
        return result_dicts

    # ---------------------------------------------------------------------- #
    # Combined pipeline helpers
    # ---------------------------------------------------------------------- #

    def get_servers_with_metadata(
        self,
        servers: Optional[List[str]] = None,
        timeout: float = 5.0,
        min_quality_score: float = 0.0,
        limit: Optional[int] = None,
        use_github_search: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch servers and return list of dicts with basic metadata.

        Each dict contains: index, config, protocol, fetched_at.
        This method does NOT run health checks; use get_servers_with_health
        followed by scorer.sort_by_quality for a fully scored list.
        """
        import datetime as _dt

        if servers is None:
            servers, _ = self.get_all_servers(
                use_github_search=use_github_search,
                limit=limit,
            )

        now = _dt.datetime.utcnow().isoformat()
        _PROTO_PREFIXES = ("vmess://", "vless://", "trojan://", "ss://", "ssr://")
        result = []
        for i, cfg in enumerate(servers):
            proto = next(
                (p.rstrip("://") for p in _PROTO_PREFIXES if cfg.startswith(p)),
                "unknown",
            )
            result.append({
                "index": i + 1,
                "config": cfg,
                "protocol": proto,
                "fetched_at": now,
            })
        return result

    def get_servers_sorted(
        self,
        servers: Optional[List[str]] = None,
        timeout: float = 5.0,
        min_quality_score: float = 0.0,
        limit: Optional[int] = None,
        use_github_search: bool = False,
    ) -> List[Dict[str, Any]]:
        """Deprecated alias for get_servers_with_metadata.

        .. deprecated::
            Use :meth:`get_servers_with_metadata` instead.
        """
        warnings.warn(
            "get_servers_sorted is deprecated and does not sort. "
            "Use get_servers_with_metadata for plain metadata, or "
            "get_servers_with_health + scorer.sort_by_quality for a scored list.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_servers_with_metadata(
            servers=servers,
            timeout=timeout,
            min_quality_score=min_quality_score,
            limit=limit,
            use_github_search=use_github_search,
        )

    # ---------------------------------------------------------------------- #
    # Internal helpers
    # ---------------------------------------------------------------------- #

    def _build_source_lookup(self) -> Dict[str, Tuple[str, int]]:
        """Return a dict mapping each known source URL to (url, trust_level).

        Used to annotate health-check results with source metadata for scoring.
        """
        sources = get_enabled_sources()
        return {s.url: (s.url, s.trust) for s in sources}

    # ---------------------------------------------------------------------- #
    # Parsing helpers
    # ---------------------------------------------------------------------- #

    _PROTO_RE = re.compile(
        r"(?:vmess|vless|trojan|ss|ssr)://[A-Za-z0-9+/=_\-@:.?&#%]+",
        re.IGNORECASE,
    )

    def _parse_servers(self, text: str) -> List[str]:
        """Extract all proxy URIs from raw text (deduplicated, order-preserved)."""
        return list(dict.fromkeys(self._PROTO_RE.findall(text)))
