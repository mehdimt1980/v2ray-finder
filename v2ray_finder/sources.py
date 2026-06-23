"""Source registry for v2ray-finder — curated and community sources.

Defines every data-source the pipeline knows about: static subscription URLs,
GitHub repos/topics, and meta-collectors.  ``core.py`` consumes this list
instead of the old three-entry ``DIRECT_SOURCES`` constant.

Part of the multi-source ingestion pipeline (closes #4 roadmap, faz 1).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class SourceType(Enum):
    """Category of a data source."""

    STATIC_SUBSCRIPTION = "static_subscription"
    """Direct raw-text subscription URL — most reliable, no extra discovery."""

    GITHUB_REPO = "github_repo"
    """A specific GitHub repository file path."""

    GITHUB_TOPIC = "github_topic"
    """Discover repositories via a GitHub topic tag."""

    META_COLLECTOR = "meta_collector"
    """An aggregator that itself pulls from multiple upstream sources."""


class SourceTrust(Enum):
    """Subjective trust level assigned at registration time.

    Used as one factor in the scoring engine (faz 4).
    HIGH=3, MEDIUM=2, LOW=1.
    """

    HIGH = 3
    MEDIUM = 2
    LOW = 1


@dataclass
class SourceEntry:
    """Describes a single data source.

    Attributes:
        url:         Full URL to fetch (raw text, API endpoint, …).
        source_type: Categorisation of this source.
        trust:       Initial trust level (can be overridden by runtime stats).
        label:       Human-readable name shown in logs / CLI output.
        notes:       Optional free-text notes (update cadence, region, …).
        enabled:     Set False to skip without removing the entry.
        tags:        Free-form tags, e.g. ``["iran", "daily"]``.
    """

    url: str
    source_type: SourceType
    trust: SourceTrust
    label: str
    notes: Optional[str] = None
    enabled: bool = True
    tags: List[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Static curated subscription sources  (previously DIRECT_SOURCES in core.py)
# ─────────────────────────────────────────────────────────────────────────────
STATIC_SOURCES: List[SourceEntry] = [
    # ── Original three ──────────────────────────────────────────────────────
    SourceEntry(
        url="https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/V2Ray-Config-By-EbraSha.txt",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.HIGH,
        label="EbraSha public list",
        notes="Iran-focused, updated regularly",
        tags=["iran", "daily"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Sub1.txt",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.HIGH,
        label="barry-far Sub1",
        tags=["aggregator"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.HIGH,
        label="Epodonios all-configs",
        tags=["aggregator"],
    ),
    # ── Meta-collectors / aggregators ───────────────────────────────────────
    SourceEntry(
        url="https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity.txt",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.HIGH,
        label="V2RayAggregator — Eternity",
        notes="Pulls from 30+ upstream sources, updated hourly",
        tags=["aggregator", "large"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge_base64.txt",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.HIGH,
        label="V2RayAggregator — merged base64",
        tags=["aggregator", "base64"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/mfuu/v2ray/master/clash.yaml",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.MEDIUM,
        label="mfuu/v2ray clash",
        notes="Clash YAML format — parser extracts vmess/vless lines",
        tags=["clash"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.MEDIUM,
        label="NoMoreWalls list",
        tags=["aggregator"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/LalatinaHub/Mineral/master/result/nodes",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.MEDIUM,
        label="LalatinaHub Mineral nodes",
        tags=["aggregator"],
    ),
    # ── Direct subscription repos ────────────────────────────────────────────
    SourceEntry(
        url="https://raw.githubusercontent.com/freefq/free/master/v2",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="freefq/free v2",
        tags=["vmess"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/tbbatbb/Proxy/master/dist/v2ray.config.txt",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="tbbatbb Proxy",
        tags=["vmess", "vless"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="aiboboxx v2rayfree",
        tags=["vmess"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="Pawdroid Free-servers",
        tags=["vmess", "vless"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/AzadNetCH/Clash/main/V2Ray.txt",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="AzadNetCH V2Ray",
        tags=["iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/Leon406/SubCrawler/master/sub/share/vless",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="Leon406 SubCrawler — vless",
        tags=["vless"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/Leon406/SubCrawler/master/sub/share/ss",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="Leon406 SubCrawler — ss",
        tags=["shadowsocks"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/awesome-vpn/awesome-vpn/master/all",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="awesome-vpn all",
        tags=["aggregator"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/YasserDivaR/pr0xy/main/ShadowSocks2022.txt",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="YasserDivaR ShadowSocks2022",
        tags=["shadowsocks", "iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/splitted/mixed",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.HIGH,
        label="soroushmirzaei telegram-collector — mixed",
        notes="Collects from Telegram channels, updated frequently",
        tags=["telegram", "aggregator", "iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/channels/protocols/vmess",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.HIGH,
        label="soroushmirzaei telegram-collector — vmess",
        tags=["telegram", "vmess", "iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/channels/protocols/vless",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.HIGH,
        label="soroushmirzaei telegram-collector — vless",
        tags=["telegram", "vless", "iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/channels/protocols/trojan",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.HIGH,
        label="soroushmirzaei telegram-collector — trojan",
        tags=["telegram", "trojan", "iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/channels/protocols/shadowsocks",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.HIGH,
        label="soroushmirzaei telegram-collector — shadowsocks",
        tags=["telegram", "shadowsocks", "iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/MhdiTaheri/V2rayCollector/main/vless.txt",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.MEDIUM,
        label="MhdiTaheri V2rayCollector — vless",
        tags=["vless", "iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/MhdiTaheri/V2rayCollector/main/vmess.txt",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.MEDIUM,
        label="MhdiTaheri V2rayCollector — vmess",
        tags=["vmess", "iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/MhdiTaheri/V2rayCollector/main/trojan.txt",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.MEDIUM,
        label="MhdiTaheri V2rayCollector — trojan",
        tags=["trojan", "iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/Surfboardv2ray/v2ray-worker-sub/master/Eternity.txt",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="Surfboardv2ray worker-sub Eternity",
        tags=["aggregator"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/tbbatbb/Proxy/master/dist/trojan.config.txt",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="tbbatbb Proxy — trojan",
        tags=["trojan"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/resasanian/Mirza/main/sub",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="resasanian Mirza sub",
        tags=["iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/IranianCypherpunks/sub/main/config",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="IranianCypherpunks sub",
        tags=["iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/vveg26/chromego_merge/main/sub/merged_base64.txt",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.MEDIUM,
        label="chromego_merge merged base64",
        tags=["aggregator", "base64"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/ALIILAPRO/v2rayNG-Config/main/sub.txt",
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.MEDIUM,
        label="ALIILAPRO v2rayNG-Config sub",
        tags=["iran"],
    ),
    SourceEntry(
        url="https://raw.githubusercontent.com/Bardiafa/Free-V2ray-Config/main/ALL_Configs_Sub.txt",
        source_type=SourceType.META_COLLECTOR,
        trust=SourceTrust.MEDIUM,
        label="Bardiafa Free-V2ray-Config — all",
        tags=["aggregator"],
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# GitHub topics used for dynamic repository discovery (faz 1 — topic discovery)
# ─────────────────────────────────────────────────────────────────────────────
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


def get_enabled_sources(
    source_type: Optional[SourceType] = None,
    min_trust: SourceTrust = SourceTrust.LOW,
    tags: Optional[List[str]] = None,
) -> List[SourceEntry]:
    """Return enabled sources filtered by type, trust, and/or tags.

    Args:
        source_type: If provided, only return sources of this type.
        min_trust:   Minimum trust level (inclusive).
        tags:        If provided, return sources that have *any* of these tags.

    Returns:
        Filtered list of :class:`SourceEntry` objects.
    """
    result: List[SourceEntry] = []
    for src in STATIC_SOURCES:
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
