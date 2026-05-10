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
    TimeoutError,
    V2RayFinderError,
)
from .result import Err, Ok, Result
from .sources import get_enabled_sources

logger = logging.getLogger(__name__)

_TOKEN_MIN_LEN = 20
_KNOWN_PREFIXES = ("ghp_", "gho_", "ghs_", "ghu_", "github_pat_")


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
            logger.debug(
                "Malformed X-RateLimit headers — limit=%r remaining=%r reset=%r; skipping update.",
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
    ) -> Result:
        """Search GitHub repositories.

        Returns:
            Ok(list[dict]) on success, Err(V2RayFinderError subclass) on failure.
        """
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
            if resp.status_code == 403:
                msg = ""
                try:
                    msg = resp.json().get("message", "")
                except Exception:
                    pass
                return Err(RateLimitError(f"Rate limit hit: {msg}"))
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
    ) -> Tuple[int, str]:
        """Save server configs to *filename*, one per line.

        Returns:
            (count_saved, filename) tuple.
        """
        servers = self.get_all_servers(
            use_github_search=use_github_search, limit=limit
        )
        with open(filename, "w", encoding="utf-8") as fh:
            for cfg in servers:
                fh.write(cfg + "\n")
        return len(servers), filename
