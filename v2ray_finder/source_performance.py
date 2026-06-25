"""Per-source performance scoring for v2ray-finder.

This module turns one scan run into a compact report about which subscription
sources actually produced useful configs.  It is intentionally independent from
Android so the same engine can later be used by CLI, tests, and scheduled source
maintenance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .sources import SourceEntry


@dataclass
class SourceRunStats:
    """Performance snapshot for one source in one scan run."""

    url: str
    label: str = ""
    trust: int = 1
    tags: List[str] = field(default_factory=list)
    source_type: str = ""
    fetch_ok: bool = True
    fetch_error_type: str = ""
    fetch_error_message: str = ""

    # Counts visible in the current pipeline output.
    tcp_candidates: int = 0
    tcp_ok_count: int = 0
    scored_count: int = 0
    xray_checked_count: int = 0
    xray_ok_count: int = 0

    # Latency summary over the best available latency values for successful rows.
    avg_latency_ms: Optional[float] = None
    best_latency_ms: Optional[float] = None

    # Diagnostic samples, capped for UI readability.
    error_samples: List[str] = field(default_factory=list)

    # Normalized 0..100 score for ranking sources.
    source_score: float = 0.0

    @property
    def tcp_success_rate(self) -> float:
        if self.tcp_candidates <= 0:
            return 0.0
        return self.tcp_ok_count / self.tcp_candidates

    @property
    def xray_success_rate(self) -> float:
        if self.xray_checked_count <= 0:
            return 0.0
        return self.xray_ok_count / self.xray_checked_count

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["tcp_success_rate"] = round(self.tcp_success_rate, 4)
        data["xray_success_rate"] = round(self.xray_success_rate, 4)
        return data


def _source_meta(sources: Iterable[SourceEntry]) -> Dict[str, SourceRunStats]:
    out: Dict[str, SourceRunStats] = {}
    for src in sources:
        out[src.url] = SourceRunStats(
            url=src.url,
            label=src.label,
            trust=int(src.trust.value),
            tags=list(src.tags),
            source_type=getattr(src.source_type, "value", str(src.source_type)),
        )
    return out


def _ensure(stats: Dict[str, SourceRunStats], url: str) -> SourceRunStats:
    if url not in stats:
        stats[url] = SourceRunStats(url=url, label=url, trust=0, fetch_ok=True)
    return stats[url]


def _latency_score(best_latency_ms: Optional[float]) -> float:
    if best_latency_ms is None:
        return 0.0
    if best_latency_ms <= 200:
        return 1.0
    if best_latency_ms <= 800:
        return 0.75
    if best_latency_ms <= 2000:
        return 0.45
    if best_latency_ms <= 5000:
        return 0.15
    return 0.0


def _append_error(row: SourceRunStats, message: str, limit: int = 5) -> None:
    message = (message or "").strip()
    if not message:
        return
    if len(message) > 240:
        message = message[:237] + "..."
    if message not in row.error_samples and len(row.error_samples) < limit:
        row.error_samples.append(message)


def _finalize_score(row: SourceRunStats) -> None:
    trust_score = {0: 0.0, 1: 0.25, 2: 0.60, 3: 1.0}.get(row.trust, 0.25)
    latency_score = _latency_score(row.best_latency_ms)

    if row.xray_checked_count > 0:
        score = (
            0.55 * row.xray_success_rate
            + 0.20 * row.tcp_success_rate
            + 0.15 * latency_score
            + 0.10 * trust_score
        )
    else:
        # Before real xray checks are available, use TCP and trust as a softer signal.
        score = 0.60 * row.tcp_success_rate + 0.20 * latency_score + 0.20 * trust_score

    if not row.fetch_ok:
        score -= 0.35
    if row.tcp_candidates == 0 and row.xray_checked_count == 0:
        score -= 0.10
    if row.xray_checked_count > 0 and row.xray_ok_count == 0:
        score -= 0.15

    row.source_score = round(max(0.0, min(1.0, score)) * 100.0, 1)


def build_source_performance(
    *,
    sources: Iterable[SourceEntry],
    health_dicts: Iterable[Mapping[str, Any]],
    fetch_errors: Optional[Mapping[str, Mapping[str, Any]]] = None,
    real_results: Optional[Iterable[Any]] = None,
) -> List[Dict[str, Any]]:
    """Build a sorted per-source performance report for one scan.

    Args:
        sources: Source registry entries used in the run.
        health_dicts: Pipeline health rows.  These carry ``source_url``,
            ``tcp_ok``, ``google_204_ok`` and latency information.
        fetch_errors: Structured fetch errors from ``PipelineResult.failed_sources``.
        real_results: Optional Layer-3 xray results from Android's second-stage
            verifier.  Newer results expose ``validation_ok`` and
            ``confidence_score``; older results expose ``google_204_ok``.

    Returns:
        List of JSON-safe dicts sorted by source quality and usefulness.
    """
    stats = _source_meta(sources)
    config_to_source: Dict[str, str] = {}
    latency_values: Dict[str, List[float]] = {}

    for h in health_dicts:
        url = str(h.get("source_url") or "")
        cfg = str(h.get("config") or "")
        if cfg and url:
            config_to_source[cfg] = url
        if not url:
            continue
        row = _ensure(stats, url)
        row.tcp_candidates += 1
        if bool(h.get("tcp_ok", False)):
            row.tcp_ok_count += 1
        row.scored_count += 1
        if bool(h.get("google_204_ok", False)):
            row.xray_checked_count += 1
            row.xray_ok_count += 1
        latency = h.get("latency_ms")
        if latency is not None:
            try:
                latency_values.setdefault(url, []).append(float(latency))
            except Exception:
                pass

    if real_results:
        for rr in real_results:
            cfg = str(getattr(rr, "config", "") or "")
            url = config_to_source.get(cfg, "")
            if not url:
                continue
            row = _ensure(stats, url)
            row.xray_checked_count += 1
            ok = bool(getattr(rr, "validation_ok", getattr(rr, "google_204_ok", False)))
            if ok:
                row.xray_ok_count += 1
            latency = getattr(rr, "latency_ms", None)
            if latency is not None:
                try:
                    latency_values.setdefault(url, []).append(float(latency))
                except Exception:
                    pass
            if not ok:
                proto = str(getattr(rr, "protocol", "") or "?")
                err = str(getattr(rr, "error", "") or "real validation failed")
                _append_error(row, f"{proto}: {err}")

    if fetch_errors:
        for url, payload in fetch_errors.items():
            row = _ensure(stats, str(url))
            row.fetch_ok = False
            if isinstance(payload, Mapping):
                row.fetch_error_type = str(payload.get("error_type") or "unknown_error")
                row.fetch_error_message = str(payload.get("message") or payload)
            else:
                row.fetch_error_type = "unknown_error"
                row.fetch_error_message = str(payload)
            _append_error(row, row.fetch_error_message)

    rows: List[SourceRunStats] = []
    for url, row in stats.items():
        vals = latency_values.get(url, [])
        if vals:
            row.avg_latency_ms = round(sum(vals) / len(vals), 1)
            row.best_latency_ms = round(min(vals), 1)
        _finalize_score(row)
        if row.tcp_candidates > 0 or row.xray_checked_count > 0 or not row.fetch_ok:
            rows.append(row)

    rows.sort(
        key=lambda r: (
            -r.source_score,
            -r.xray_ok_count,
            -r.tcp_ok_count,
            r.avg_latency_ms if r.avg_latency_ms is not None else 999999.0,
            r.label or r.url,
        )
    )
    return [r.to_dict() for r in rows]
