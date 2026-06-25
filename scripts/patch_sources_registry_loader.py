#!/usr/bin/env python3
"""Replace v2ray_finder/sources.py with the JSON-registry backed loader.

This helper is intentionally idempotent.  It exists because source data now lives
in registry/sources.json and registry/candidate_sources.json; the Python module
should only define the public SourceEntry/SourceType/SourceTrust API and load
records from the registry.
"""

from __future__ import annotations

from pathlib import Path

TARGET = Path("v2ray_finder/sources.py")

NEW_CONTENT = '''"""Source definitions and registry-backed source loading for v2ray-finder.

Source metadata lives in JSON files under ``registry/``.  This module keeps only
the public dataclasses/enums and converts JSON registry records into
``SourceEntry`` objects consumed by the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class SourceType(Enum):
    """Category of a data source."""

    STATIC_SUBSCRIPTION = "static_subscription"
    GITHUB_REPO = "github_repo"
    GITHUB_TOPIC = "github_topic"
    META_COLLECTOR = "meta_collector"


class SourceTrust(Enum):
    """Subjective trust level assigned at registration time."""

    HIGH = 3
    MEDIUM = 2
    LOW = 1


@dataclass
class SourceEntry:
    """Describes a single data source."""

    url: str
    source_type: SourceType
    trust: SourceTrust
    label: str
    notes: Optional[str] = None
    enabled: bool = True
    tags: List[str] = field(default_factory=list)


GITHUB_TOPICS: List[str] = [
    "v2ray-config",
    "v2ray-subscriber",
    "free-v2ray",
    "v2ray-vmess",
    "xray-config",
    "v2ray-vless",
    "shadowsocks-config",
    "v2ray-configs",
    "free-proxy",
    "proxy-list",
]


def _trust_from_string(value: str) -> SourceTrust:
    value = (value or "low").strip().lower()
    if value in {"high", "3"}:
        return SourceTrust.HIGH
    if value in {"medium", "med", "2"}:
        return SourceTrust.MEDIUM
    return SourceTrust.LOW


def _type_from_string(value: str) -> SourceType:
    value = (value or "static_subscription").strip().lower()
    for item in SourceType:
        if item.value == value:
            return item
    return SourceType.STATIC_SUBSCRIPTION


def _registry_sources(include_candidates: bool = False) -> List[SourceEntry]:
    from .source_registry import load_source_records

    entries: List[SourceEntry] = []
    for rec in load_source_records(include_candidates=include_candidates):
        entries.append(
            SourceEntry(
                url=rec.url,
                source_type=_type_from_string(rec.source_type),
                trust=_trust_from_string(rec.trust),
                label=rec.label,
                notes=rec.notes or None,
                enabled=rec.enabled,
                tags=list(rec.tags),
            )
        )
    return entries


STATIC_SOURCES: List[SourceEntry] = _registry_sources(include_candidates=False)


def get_enabled_sources(
    source_type: Optional[SourceType] = None,
    min_trust: SourceTrust = SourceTrust.LOW,
    tags: Optional[List[str]] = None,
    include_candidates: bool = False,
) -> List[SourceEntry]:
    """Return enabled sources filtered by type, trust and/or tags.

    By default only ``official`` and ``trusted`` registry records are used.
    Candidate/experimental sources are excluded from normal scans unless
    ``include_candidates=True`` is passed explicitly.
    """
    result: List[SourceEntry] = []
    for src in _registry_sources(include_candidates=include_candidates):
        if not src.enabled:
            continue
        if src.trust.value < min_trust.value:
            continue
        if source_type is not None and src.source_type != source_type:
            continue
        if tags is not None and not any(t in src.tags for t in tags):
            continue
        result.append(src)
    return result
'''


def main() -> int:
    TARGET.write_text(NEW_CONTENT, encoding="utf-8")
    print(f"Patched {TARGET} to use JSON source registry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
