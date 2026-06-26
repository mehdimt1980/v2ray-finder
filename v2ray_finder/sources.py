"""Source definitions and remote-registry backed source loading.

The default source list is resolved through ``remote_source_registry`` when
``get_enabled_sources`` is called:

1. fresh remote cache;
2. remote GitHub registry;
3. stale remote cache;
4. bundled JSON registry;
5. legacy built-in fallback.
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


def _legacy_static_sources() -> List[SourceEntry]:
    """Minimal emergency fallback if remote and bundled registries fail."""
    return [
        SourceEntry(
            url="https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/V2Ray-Config-By-EbraSha.txt",
            source_type=SourceType.STATIC_SUBSCRIPTION,
            trust=SourceTrust.HIGH,
            label="EbraSha public list",
            notes="Emergency built-in fallback",
            tags=["iran", "daily", "fallback"],
        ),
        SourceEntry(
            url="https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Sub1.txt",
            source_type=SourceType.STATIC_SUBSCRIPTION,
            trust=SourceTrust.HIGH,
            label="barry-far Sub1",
            tags=["aggregator", "fallback"],
        ),
        SourceEntry(
            url="https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
            source_type=SourceType.STATIC_SUBSCRIPTION,
            trust=SourceTrust.HIGH,
            label="Epodonios all-configs",
            tags=["aggregator", "fallback"],
        ),
    ]


def get_enabled_sources(
    source_type: Optional[SourceType] = None,
    min_trust: SourceTrust = SourceTrust.LOW,
    tags: Optional[List[str]] = None,
    include_candidates: bool = False,
) -> List[SourceEntry]:
    """Return enabled sources filtered by type, trust, and/or tags.

    The returned list is resolved from the remote source registry when possible.
    Candidate/experimental sources are excluded unless ``include_candidates`` is
    explicitly set.
    """
    try:
        from .remote_source_registry import get_sources_with_remote_registry

        candidates = get_sources_with_remote_registry(include_candidates=include_candidates)
    except Exception:
        candidates = _legacy_static_sources()

    result: List[SourceEntry] = []
    for src in candidates:
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


# Compatibility name for old imports. It must not fetch the remote registry at
# import time. Call ``get_enabled_sources()`` for fresh remote/bundled data.
STATIC_SOURCES: List[SourceEntry] = _legacy_static_sources()
