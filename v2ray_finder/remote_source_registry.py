"""Remote Source Registry loader.

The Android app and Python pipeline can use this module to refresh the trusted
source list from the canonical GitHub registry without requiring a new APK or
package release every time ``registry/sources.json`` changes.

Resolution order:

1. Fresh local remote cache, if still inside TTL.
2. Remote registry from GitHub, if enabled and reachable.
3. Stale local cache, if remote is unavailable.
4. Bundled JSON registry under ``registry/sources.json``.
5. Legacy built-in fallback.

Only active registry statuses, ``official`` and ``trusted``, are returned by
default. Candidate, experimental, quarantine and disabled sources are not used
by normal scans.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

import requests

from .source_registry import ACTIVE_STATUSES, CANDIDATE_STATUSES, SourceRecord, load_source_records
from .sources import SourceEntry, SourceTrust, SourceType

DEFAULT_REMOTE_REGISTRY_URL = (
    "https://raw.githubusercontent.com/mehdimt1980/v2ray-finder/main/registry/sources.json"
)
DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


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


def _cache_dir() -> Path:
    explicit = os.environ.get("V2RAY_FINDER_REGISTRY_CACHE_DIR")
    if explicit:
        return Path(explicit)
    base = Path(os.environ.get("XDG_CACHE_HOME") or tempfile.gettempdir())
    return base / "v2ray-finder"


def remote_cache_path() -> Path:
    explicit = os.environ.get("V2RAY_FINDER_REGISTRY_CACHE")
    if explicit:
        return Path(explicit)
    return _cache_dir() / "remote_sources.json"


def remote_registry_url() -> str:
    return os.environ.get("V2RAY_FINDER_REMOTE_REGISTRY_URL", DEFAULT_REMOTE_REGISTRY_URL).strip()


def remote_registry_ttl_seconds() -> int:
    raw = os.environ.get("V2RAY_FINDER_REMOTE_REGISTRY_TTL", str(DEFAULT_CACHE_TTL_SECONDS))
    try:
        return max(0, int(float(raw)))
    except Exception:
        return DEFAULT_CACHE_TTL_SECONDS


def remote_registry_enabled() -> bool:
    if _truthy(os.environ.get("V2RAY_FINDER_DISABLE_REMOTE_REGISTRY", "")):
        return False
    return bool(remote_registry_url())


def _read_records_from_json_text(text: str) -> List[SourceRecord]:
    raw = json.loads(text)
    if not isinstance(raw, list):
        raise ValueError("remote source registry must be a JSON list")
    records: List[SourceRecord] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        rec = SourceRecord.from_mapping(item)
        if not rec.url or rec.url in seen:
            continue
        seen.add(rec.url)
        records.append(rec)
    return records


def _record_is_active(record: SourceRecord, include_candidates: bool = False) -> bool:
    if not record.enabled:
        return False
    if record.status in ACTIVE_STATUSES:
        return True
    if include_candidates and record.status in CANDIDATE_STATUSES:
        return True
    return False


def records_to_entries(records: Iterable[SourceRecord], *, include_candidates: bool = False) -> List[SourceEntry]:
    out: List[SourceEntry] = []
    seen: set[str] = set()
    for rec in records:
        if rec.url in seen or not _record_is_active(rec, include_candidates=include_candidates):
            continue
        seen.add(rec.url)
        out.append(
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
    return out


def _is_cache_fresh(path: Path, ttl_seconds: int) -> bool:
    if ttl_seconds <= 0:
        return False
    if not path.exists() or path.stat().st_size <= 0:
        return False
    return (time.time() - path.stat().st_mtime) <= ttl_seconds


def load_cached_remote_records(*, allow_stale: bool = False) -> List[SourceRecord]:
    path = remote_cache_path()
    ttl = remote_registry_ttl_seconds()
    if not allow_stale and not _is_cache_fresh(path, ttl):
        return []
    try:
        return _read_records_from_json_text(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def fetch_remote_records(*, timeout: float = 8.0) -> List[SourceRecord]:
    url = remote_registry_url()
    if not url:
        return []
    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": "v2ray-finder-remote-registry/1.0",
            "Accept": "application/json,text/plain,*/*",
            "Cache-Control": "no-cache",
        },
    )
    response.raise_for_status()
    records = _read_records_from_json_text(response.text)
    path = remote_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return records


def load_bundled_records() -> List[SourceRecord]:
    try:
        return load_source_records(include_candidates=False)
    except Exception:
        return []


def get_remote_registry_diagnostics() -> Dict[str, Any]:
    path = remote_cache_path()
    return {
        "enabled": remote_registry_enabled(),
        "url": remote_registry_url(),
        "cache_path": str(path),
        "cache_exists": path.exists(),
        "cache_fresh": _is_cache_fresh(path, remote_registry_ttl_seconds()),
        "cache_ttl_seconds": remote_registry_ttl_seconds(),
    }


def get_sources_with_remote_registry(
    *,
    include_candidates: bool = False,
    timeout: float = 8.0,
) -> List[SourceEntry]:
    """Return active sources with remote registry refresh and safe fallback."""
    records: List[SourceRecord] = []

    if remote_registry_enabled():
        records = load_cached_remote_records(allow_stale=False)
        if not records:
            try:
                records = fetch_remote_records(timeout=timeout)
            except Exception:
                records = load_cached_remote_records(allow_stale=True)

    if not records:
        records = load_bundled_records()

    entries = records_to_entries(records, include_candidates=include_candidates)
    if entries:
        return entries

    try:
        from .sources import _legacy_static_sources

        return [src for src in _legacy_static_sources() if getattr(src, "enabled", True)]
    except Exception:
        return []
