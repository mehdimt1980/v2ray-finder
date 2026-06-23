"""SourceRegistry — tracks per-source runtime statistics.

Part of the multi-source ingestion pipeline (closes #4 roadmap).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SourceStats:
    """Runtime statistics for a single source URL."""

    url: str
    fetch_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_fetched: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_server_count: int = 0
    total_servers_found: int = 0
    overlap_ratio: float = 0.0
    tags: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.fetch_count == 0:
            return 0.0
        return round(self.success_count / self.fetch_count, 4)

    @property
    def avg_servers_per_fetch(self) -> float:
        if self.fetch_count == 0:
            return 0.0
        return round(self.total_servers_found / self.fetch_count, 1)


class SourceRegistry:
    """Central registry that accumulates runtime stats for every source URL."""

    def __init__(self) -> None:
        self._stats: Dict[str, SourceStats] = {}

    def get(self, url: str) -> SourceStats:
        """Return existing stats or create a new entry for *url*."""
        if url not in self._stats:
            self._stats[url] = SourceStats(url=url)
        return self._stats[url]

    def record_success(self, url: str, server_count: int) -> None:
        """Record a successful fetch that yielded *server_count* servers."""
        s = self.get(url)
        now = datetime.now(timezone.utc)
        s.fetch_count += 1
        s.success_count += 1
        s.last_fetched = now
        s.last_success = now
        s.last_server_count = server_count
        s.total_servers_found += server_count
        logger.debug(f"[SourceRegistry] success {url!r} -> {server_count} servers")

    def record_failure(self, url: str) -> None:
        """Record a failed fetch for *url*."""
        s = self.get(url)
        s.fetch_count += 1
        s.failure_count += 1
        s.last_fetched = datetime.now(timezone.utc)
        logger.debug(f"[SourceRegistry] failure {url!r}")

    def update_overlap(self, url: str, ratio: float) -> None:
        """Update the overlap ratio for *url*."""
        self.get(url).overlap_ratio = ratio

    def all_stats(self) -> List[SourceStats]:
        """Return all tracked stats, sorted by total servers found descending."""
        return sorted(
            self._stats.values(), key=lambda s: s.total_servers_found, reverse=True
        )

    def summary(self) -> str:
        """Human-readable summary table."""
        lines = ["SourceRegistry summary:", "-" * 60]
        for s in self.all_stats():
            lines.append(
                f"  {s.url[:50]:<50} "
                f"ok={s.success_count}/{s.fetch_count} "
                f"servers={s.total_servers_found} "
                f"overlap={s.overlap_ratio:.2f}"
            )
        return "\n".join(lines)
