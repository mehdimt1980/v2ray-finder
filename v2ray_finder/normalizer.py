"""Structural normalization and deduplication for V2Ray server configs.

Moves deduplication from naive string comparison (``dict.fromkeys``) to
a structural fingerprint based on ``(protocol, host, port, credential)``.

Part of the multi-source ingestion pipeline (closes #4 roadmap, faz 3).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass
class NormalizedServer:
    """A parsed, normalised representation of one V2Ray server config."""

    raw_config: str
    protocol: str
    host: str
    port: int
    uuid_or_password: Optional[str]
    source_url: str
    source_type: str
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    tls: bool = False
    country: Optional[str] = None
    extra: Dict = field(default_factory=dict)

    @property
    def structural_key(self) -> str:
        """16-character hex fingerprint for structural deduplication."""
        cred = (self.uuid_or_password or "")[:32]
        raw = f"{self.protocol}:{self.host.lower()}:{self.port}:{cred}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def __repr__(self) -> str:
        return (
            f"<NormalizedServer {self.protocol}://{self.host}:{self.port} "
            f"tls={self.tls} key={self.structural_key}>"
        )


def _safe_b64decode(data: str) -> str:
    data = data.strip()
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    try:
        return base64.b64decode(data).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _parse_vmess(
    config: str, source_url: str, source_type: str
) -> Optional[NormalizedServer]:
    try:
        raw_b64 = config[len("vmess://") :]
        decoded = _safe_b64decode(raw_b64)
        if not decoded:
            return None
        data = json.loads(decoded)
        host = str(data.get("add") or data.get("host") or "").strip()
        port_raw = data.get("port", 0)
        port = int(str(port_raw).split(",")[0]) if port_raw else 0
        uuid = str(data.get("id") or "").strip()
        tls = str(data.get("tls") or "").lower() in ("tls", "reality", "xtls")
        if not host or not port:
            return None
        extra = {k: v for k, v in data.items() if k not in ("add", "port", "id", "tls")}
        return NormalizedServer(
            raw_config=config,
            protocol="vmess",
            host=host,
            port=port,
            uuid_or_password=uuid or None,
            source_url=source_url,
            source_type=source_type,
            tls=tls,
            extra=extra,
        )
    except Exception as exc:
        logger.debug(f"vmess parse failed: {exc}")
        return None


def _parse_vless(
    config: str, source_url: str, source_type: str
) -> Optional[NormalizedServer]:
    try:
        rest = config[len("vless://") :]
        parsed = urllib.parse.urlparse("vless://" + rest)
        host = parsed.hostname or ""
        port = parsed.port or 0
        uuid = parsed.username or ""
        params = dict(urllib.parse.parse_qsl(parsed.query))
        tls = params.get("security", "").lower() in ("tls", "reality", "xtls")
        if not host or not port:
            return None
        return NormalizedServer(
            raw_config=config,
            protocol="vless",
            host=host,
            port=port,
            uuid_or_password=uuid or None,
            source_url=source_url,
            source_type=source_type,
            tls=tls,
            extra=params,
        )
    except Exception as exc:
        logger.debug(f"vless parse failed: {exc}")
        return None


def _parse_trojan(
    config: str, source_url: str, source_type: str
) -> Optional[NormalizedServer]:
    try:
        rest = config[len("trojan://") :]
        parsed = urllib.parse.urlparse("trojan://" + rest)
        host = parsed.hostname or ""
        port = parsed.port or 0
        password = parsed.username or ""
        params = dict(urllib.parse.parse_qsl(parsed.query))
        tls = params.get("security", "tls").lower() in ("tls", "reality", "xtls", "")
        if not host or not port:
            return None
        return NormalizedServer(
            raw_config=config,
            protocol="trojan",
            host=host,
            port=port,
            uuid_or_password=password or None,
            source_url=source_url,
            source_type=source_type,
            tls=tls,
            extra=params,
        )
    except Exception as exc:
        logger.debug(f"trojan parse failed: {exc}")
        return None


def _parse_ss(
    config: str, source_url: str, source_type: str
) -> Optional[NormalizedServer]:
    try:
        rest = config[len("ss://") :]
        rest = rest.split("#")[0]
        sip002 = re.match(r"([A-Za-z0-9+/=]+)@(.+):(\d+)", rest)
        if sip002:
            cred_b64, host, port_s = sip002.groups()
            cred = _safe_b64decode(cred_b64)
            password = cred.split(":", 1)[1] if ":" in cred else cred
            return NormalizedServer(
                raw_config=config,
                protocol="ss",
                host=host,
                port=int(port_s),
                uuid_or_password=password[:32] if password else None,
                source_url=source_url,
                source_type=source_type,
                tls=False,
            )
        decoded = _safe_b64decode(rest)
        m = re.match(r"(.+):(.+)@(.+):(\d+)", decoded)
        if m:
            _, password, host, port_s = m.groups()
            return NormalizedServer(
                raw_config=config,
                protocol="ss",
                host=host,
                port=int(port_s),
                uuid_or_password=password[:32] if password else None,
                source_url=source_url,
                source_type=source_type,
                tls=False,
            )
        return None
    except Exception as exc:
        logger.debug(f"ss parse failed: {exc}")
        return None


_PARSERS = {
    "vmess": _parse_vmess,
    "vless": _parse_vless,
    "trojan": _parse_trojan,
    "ss": _parse_ss,
    "ssr": _parse_ss,
}


def normalize_server(
    config: str,
    source_url: str = "",
    source_type: str = "unknown",
) -> Optional[NormalizedServer]:
    """Parse *config* into a :class:`NormalizedServer`, or ``None`` on failure."""
    config = config.strip()
    for protocol, parser in _PARSERS.items():
        if config.startswith(f"{protocol}://"):
            return parser(config, source_url, source_type)
    return None


def deduplicate_servers(
    servers: Sequence[str],
    source_url: str = "",
    source_type: str = "unknown",
) -> Tuple[List[str], int]:
    """Deduplicate *servers* using structural fingerprinting.

    Returns:
        ``(deduped_configs, duplicates_removed)`` tuple.
    """
    seen_keys: set = set()
    seen_raw: set = set()
    result: List[str] = []
    total = 0

    for raw in servers:
        total += 1
        normalized = normalize_server(raw, source_url, source_type)
        if normalized is not None:
            key = normalized.structural_key
            if key not in seen_keys:
                seen_keys.add(key)
                result.append(raw)
        else:
            stripped = raw.strip()
            if stripped and stripped not in seen_raw:
                seen_raw.add(stripped)
                result.append(stripped)

    duplicates_removed = total - len(result)
    if duplicates_removed > 0:
        logger.debug(
            f"[normalizer] Removed {duplicates_removed} structural duplicates "
            f"from {total} configs ({source_url!r})"
        )
    return result, duplicates_removed


def deduplicate_across_sources(
    servers_by_source: Dict[str, List[str]],
) -> Tuple[List[str], Dict[str, float]]:
    """Deduplicate configs across multiple sources and compute overlap ratios."""
    fingerprint_sources: Dict[str, List[str]] = {}

    for source_url, configs in servers_by_source.items():
        for raw in configs:
            ns = normalize_server(raw, source_url)
            if ns is not None:
                key = ns.structural_key
            else:
                key = hashlib.sha256(raw.strip().encode()).hexdigest()[:16]
            fingerprint_sources.setdefault(key, []).append(source_url)

    seen_keys: set = set()
    unique_configs: List[str] = []
    source_total: Dict[str, int] = {u: 0 for u in servers_by_source}
    source_overlap: Dict[str, int] = {u: 0 for u in servers_by_source}

    for source_url, configs in servers_by_source.items():
        for raw in configs:
            ns = normalize_server(raw, source_url)
            key = (
                ns.structural_key
                if ns
                else hashlib.sha256(raw.strip().encode()).hexdigest()[:16]
            )
            source_total[source_url] = source_total.get(source_url, 0) + 1
            if len(fingerprint_sources.get(key, [])) > 1:
                source_overlap[source_url] = source_overlap.get(source_url, 0) + 1
            if key not in seen_keys:
                seen_keys.add(key)
                unique_configs.append(raw)

    overlap_ratios: Dict[str, float] = {}
    for source_url in servers_by_source:
        total = source_total.get(source_url, 0)
        overlap = source_overlap.get(source_url, 0)
        overlap_ratios[source_url] = round(overlap / total, 4) if total > 0 else 0.0

    logger.info(
        f"[normalizer] Cross-source dedup: {sum(source_total.values())} raw -> "
        f"{len(unique_configs)} unique configs across {len(servers_by_source)} sources"
    )
    return unique_configs, overlap_ratios
