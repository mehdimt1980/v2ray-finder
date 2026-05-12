"""Server scoring engine for v2ray-finder.

Combines multiple signal dimensions into a single ``total`` score (0.0-1.0)
so callers can rank servers by overall quality.

Dimensions
----------
latency_score       TCP round-trip time, normalised and inverted.
reliability_score   Fraction of successful checks.
uniqueness_score    Inverse of overlap with other subscription sources.
protocol_score      Fixed weight per proxy protocol.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# Per-protocol quality weight (higher = more desirable)
_PROTOCOL_WEIGHTS: Dict[str, float] = {
    "vless":   1.0,
    "vmess":   0.9,
    "trojan":  0.95,
    "ss":      0.8,
    "ssr":     0.6,
    "unknown": 0.5,
}

# Latency thresholds (ms)
_LATENCY_EXCELLENT = 100.0
_LATENCY_GOOD      = 300.0
_LATENCY_FAIR      = 800.0
_LATENCY_MAX       = 3000.0


def _latency_score(latency_ms: Optional[float]) -> float:
    """Map latency → [0, 1]; None / negative → 0."""
    if latency_ms is None or latency_ms < 0:
        return 0.0
    if latency_ms <= _LATENCY_EXCELLENT:
        return 1.0
    if latency_ms >= _LATENCY_MAX:
        return 0.0
    # Piecewise linear decay
    if latency_ms <= _LATENCY_GOOD:
        t = (latency_ms - _LATENCY_EXCELLENT) / (_LATENCY_GOOD - _LATENCY_EXCELLENT)
        return 1.0 - 0.3 * t
    if latency_ms <= _LATENCY_FAIR:
        t = (latency_ms - _LATENCY_GOOD) / (_LATENCY_FAIR - _LATENCY_GOOD)
        return 0.7 - 0.3 * t
    t = (latency_ms - _LATENCY_FAIR) / (_LATENCY_MAX - _LATENCY_FAIR)
    return 0.4 - 0.4 * t


# Alias expected by tests
_latency_to_score = _latency_score


def _protocol_score(protocol: str) -> float:
    return _PROTOCOL_WEIGHTS.get(protocol.lower(), 0.5)


@dataclass
class ServerScore:
    """Scoring result for a single server."""

    config:           str
    protocol:         str
    latency_ms:       Optional[float]
    latency_score:    float
    reliability_score: float
    uniqueness_score: float
    protocol_score:   float
    total:            float
    grade:            str

    def __repr__(self) -> str:  # pragma: no cover
        lat = f"{self.latency_ms:.0f}ms" if self.latency_ms is not None else "n/a"
        return (
            f"<ServerScore {self.protocol} total={self.total:.3f}"
            f" grade={self.grade} latency={lat}>"
        )


def _grade(total: float) -> str:
    if total >= 0.90:
        return "A+"
    if total >= 0.80:
        return "A"
    if total >= 0.70:
        return "B"
    if total >= 0.60:
        return "C"
    if total >= 0.50:
        return "D"
    return "F"


def _compute_total(
    latency_score:    float,
    reliability_score: float,
    uniqueness_score: float,
    protocol_score:   float,
    *,
    w_latency:     float = 0.40,
    w_reliability: float = 0.30,
    w_uniqueness:  float = 0.20,
    w_protocol:    float = 0.10,
) -> float:
    raw = (
        w_latency     * latency_score
        + w_reliability * reliability_score
        + w_uniqueness  * uniqueness_score
        + w_protocol    * protocol_score
    )
    return round(min(max(raw, 0.0), 1.0), 4)


def score_server(
    config:           str,
    protocol:         str,
    latency_ms:       Optional[float],
    is_healthy:       bool,
    overlap_ratio:    float = 0.0,
) -> ServerScore:
    """Score a single server.

    Args:
        config:        Raw config string (vmess://, vless://, …).
        protocol:      Protocol name (vless, vmess, trojan, ss, ssr).
        latency_ms:    TCP round-trip in milliseconds, or None if unavailable.
        is_healthy:    Whether the server passed health checks.
        overlap_ratio: Fraction of other sources that also contain this server.
                       0.0 = unique, 1.0 = present in every source.

    Returns:
        :class:`ServerScore` instance.
    """
    ls = _latency_score(latency_ms)
    rs = 1.0 if is_healthy else 0.0
    us = round(1.0 - overlap_ratio * 0.8, 4)
    ps = _protocol_score(protocol)
    total = _compute_total(ls, rs, us, ps)
    return ServerScore(
        config=config,
        protocol=protocol,
        latency_ms=latency_ms,
        latency_score=ls,
        reliability_score=rs,
        uniqueness_score=us,
        protocol_score=ps,
        total=total,
        grade=_grade(total),
    )


def score_servers(
    health_results: List[Dict[str, Any]],
    overlap_map: Optional[Dict[str, float]] = None,
) -> List[ServerScore]:
    """Score a batch of health-check result dicts.

    Each dict in *health_results* must contain at minimum:
        ``config``      — raw config string
        ``protocol``    — protocol name
        ``latency_ms``  — latency in ms or None
        ``is_healthy``  — bool

    Optional per-dict key:
        ``overlap_ratio`` — overrides the value from *overlap_map*.

    Args:
        health_results: List of dicts from the health checker.
        overlap_map:    Optional ``{source_url: ratio}`` mapping.

    Returns:
        List of :class:`ServerScore` objects (same order as input).
    """
    if overlap_map is None:
        overlap_map = {}

    scores: List[ServerScore] = []
    for h in health_results:
        config     = h.get("config", "")
        protocol   = h.get("protocol", "unknown")
        latency_ms = h.get("latency_ms")
        is_healthy = bool(h.get("is_healthy", False))
        source_url = h.get("source_url", "")
        scores.append(
            score_server(
                config=config,
                protocol=protocol,
                latency_ms=latency_ms,
                is_healthy=is_healthy,
                overlap_ratio=h.get("overlap_ratio", overlap_map.get(source_url, 0.0)),
            )
        )
    return scores


def sort_by_score(
    scores: List[ServerScore],
    descending: bool = True,
) -> List[ServerScore]:
    """Sort :class:`ServerScore` objects by their total score."""
    return sorted(scores, key=lambda s: s.total, reverse=descending)


def sort_by_quality(
    health_results: List[Dict[str, Any]],
    descending: bool = True,
    overlap_map: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Score *health_results*, sort by total score, return original dicts.

    The original dict is enriched with a ``_score`` key containing the
    :class:`ServerScore` object.

    Args:
        health_results: List of health-check result dicts.
        descending:     True → best servers first.
        overlap_map:    Optional source-overlap mapping.

    Returns:
        Sorted list of the original dicts (with added ``_score`` field).
    """
    scored = score_servers(health_results, overlap_map=overlap_map)
    paired = sorted(
        zip(health_results, scored),
        key=lambda pair: pair[1].total,
        reverse=descending,
    )
    result = []
    for h, s in paired:
        enriched = dict(h)
        enriched["_score"] = s
        result.append(enriched)
    return result
