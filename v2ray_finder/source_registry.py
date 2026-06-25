"""Source registry utilities.

This module has two responsibilities:

1. Keep the older in-memory ``SourceRegistry`` runtime statistics helper.
2. Load and save JSON-backed source registry records from ``registry/*.json``.

The JSON registry makes source management explicit: trusted sources are active,
candidate sources are quarantined for onboarding, and disabled/quarantine
sources never enter the default scan.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

REGISTRY_ROOT = Path(__file__).resolve().parent.parent / "registry"
TRUSTED_REGISTRY = REGISTRY_ROOT / "sources.json"
CANDIDATE_REGISTRY = REGISTRY_ROOT / "candidate_sources.json"

ACTIVE_STATUSES = {"official", "trusted"}
CANDIDATE_STATUSES = {"candidate", "experimental"}
INACTIVE_STATUSES = {"quarantine", "disabled"}
VALID_STATUSES = ACTIVE_STATUSES | CANDIDATE_STATUSES | INACTIVE_STATUSES
_URL_ID_RE = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# Runtime source stats, retained for backward compatibility.
# ---------------------------------------------------------------------------


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
        logger.debug("[SourceRegistry] success %r -> %d servers", url, server_count)

    def record_failure(self, url: str) -> None:
        """Record a failed fetch for *url*."""
        s = self.get(url)
        s.fetch_count += 1
        s.failure_count += 1
        s.last_fetched = datetime.now(timezone.utc)
        logger.debug("[SourceRegistry] failure %r", url)

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


# ---------------------------------------------------------------------------
# JSON-backed source records.
# ---------------------------------------------------------------------------


@dataclass
class SourceRecord:
    """JSON-safe registry record before conversion to SourceEntry."""

    id: str
    label: str
    url: str
    source_type: str = "static_subscription"
    trust: str = "low"
    status: str = "candidate"
    enabled: bool = True
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    protocols: List[str] = field(default_factory=list)
    region: str = ""
    added_at: str = ""
    last_reviewed_at: str = ""

    @classmethod
    def from_mapping(cls, data: Dict[str, Any]) -> "SourceRecord":
        url = str(data.get("url") or "").strip()
        label = str(data.get("label") or data.get("id") or url).strip()
        source_id = str(data.get("id") or make_source_id(label or url)).strip()
        status = str(data.get("status") or "candidate").strip().lower()
        if status not in VALID_STATUSES:
            status = "candidate"
        tags = data.get("tags") or []
        protocols = data.get("protocols") or []
        return cls(
            id=source_id,
            label=label,
            url=url,
            source_type=str(data.get("source_type") or "static_subscription").strip(),
            trust=str(data.get("trust") or "low").strip().lower(),
            status=status,
            enabled=bool(data.get("enabled", True)),
            tags=[str(t).strip() for t in tags if str(t).strip()],
            notes=str(data.get("notes") or "").strip(),
            protocols=[str(p).strip().lower() for p in protocols if str(p).strip()],
            region=str(data.get("region") or "").strip(),
            added_at=str(data.get("added_at") or "").strip(),
            last_reviewed_at=str(data.get("last_reviewed_at") or "").strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "url": self.url,
            "source_type": self.source_type,
            "trust": self.trust,
            "status": self.status,
            "enabled": self.enabled,
            "tags": list(self.tags),
        }
        optional = {
            "notes": self.notes,
            "protocols": self.protocols,
            "region": self.region,
            "added_at": self.added_at,
            "last_reviewed_at": self.last_reviewed_at,
        }
        for key, value in optional.items():
            if value:
                data[key] = value
        return data


def make_source_id(value: str) -> str:
    base = _URL_ID_RE.sub("-", value.lower()).strip("-")
    return base[:80] or "source"


def load_json_records(path: Path) -> List[SourceRecord]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Source registry must contain a list: {path}")
    records: List[SourceRecord] = []
    seen_urls: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        rec = SourceRecord.from_mapping(item)
        if not rec.url or rec.url in seen_urls:
            continue
        records.append(rec)
        seen_urls.add(rec.url)
    return records


def load_source_records(
    *,
    include_candidates: bool = False,
    include_inactive: bool = False,
    registry_paths: Optional[Sequence[Path]] = None,
) -> List[SourceRecord]:
    """Load records from trusted and candidate registries.

    By default only active statuses, ``official`` and ``trusted``, are returned.
    Candidate and inactive sources remain available for onboarding and review,
    but do not enter the main scan unless explicitly requested.
    """
    paths = list(registry_paths or (TRUSTED_REGISTRY, CANDIDATE_REGISTRY))
    records: List[SourceRecord] = []
    seen_urls: set[str] = set()
    for path in paths:
        for rec in load_json_records(path):
            if rec.url in seen_urls:
                continue
            seen_urls.add(rec.url)
            allowed = rec.status in ACTIVE_STATUSES
            if include_candidates and rec.status in CANDIDATE_STATUSES:
                allowed = True
            if include_inactive and rec.status in INACTIVE_STATUSES:
                allowed = True
            if allowed and rec.enabled:
                records.append(rec)
    return records


def save_records(path: Path, records: Iterable[SourceRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [r.to_dict() for r in records]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_candidate(record: SourceRecord, path: Path = CANDIDATE_REGISTRY) -> bool:
    """Append a candidate if its URL is not already present.

    Returns True if the file changed, False if the URL already existed.
    """
    records = load_json_records(path)
    if any(r.url == record.url for r in records):
        return False
    record.status = record.status if record.status in CANDIDATE_STATUSES else "candidate"
    records.append(record)
    save_records(path, records)
    return True
