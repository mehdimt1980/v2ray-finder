"""Server scoring engine for v2ray-finder.

Combines multiple signal dimensions into a single ``total`` score (0.0-1.0)
so callers can rank servers by overall quality.

Part of the multi-source ingestion pipeline (closes #4 roadmap, faz 4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_WEIGHTS: Dict[str, float] = {
    "latency": 0.30,
    "reachability": 0.30,
    "protocol": 0.15,
    "source_trust": 0.15,
    "freshness": 0.05,
    "uniqueness": 0.05,
}

assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

_PROTOCOL_SCORES: Dict[str, float] = {
    "vless": 1.00,
    "trojan": 0.90,
    "ss": 0.80,
    "vmess": 0.70,
    "ssr": 0.50,
}


@dataclass
class ServerScore:
    """Breakdown of all score components for one server config."""

    config: str
    protocol: str
    latency_score: float = 0.0
    reachability_score: float = 0.0
    protocol_score: float = 0.0
    source_trust_score: float = 0.0
    freshness_score: float = 1.0
    uniqueness_score: float = 1.0
    source_url: str = ""
    latency_ms: Optional[float] = None
    health_details: Dict = field(default_factory=dict)

    @property
    def total(self) -> float:
        """Weighted total score in [0.0, 1.0]."""
        raw = (
            self.latency_score * _WEIGHTS["latency"]
            + self.reachability_score * _WEIGHTS["reachability"]
            + self.protocol_score * _WEIGHTS["protocol"]
            + self.source_trust_score * _WEIGHTS["source_trust"]
            + self.freshness_score * _WEIGHTS["freshness"]
            + self.uniqueness_score * _WEIGHTS["uniqueness"]
        )
        return round(min(max(raw, 0.0), 1.0), 4)

    @property
    def grade(self) -> str:
        """Human-readable grade: A / B / C / D / F."""
        t = self.total
        if t >= 0.80:
            return "A"
        if t >= 0.60:
            return "B"
        if t >= 0.40:
            return "C"
        if t >= 0.20:
            return "D"
        return "F"

    def __repr__(self) -> str:
        return (
            f"<ServerScore {self.protocol} total={self.total:.3f} "
            f"grade={self.grade} latency={self.latency_ms}ms>"
        )


def _latency_to_score(latency_ms: Optional[float]) -> float:
    if latency_ms is None or latency_ms <= 0:
        return 0.0
    if latency_ms <= 100:
        return 1.0
    if latency_ms <= 300:
        return 0.9 - (latency_ms - 100) / 200 * 0.3
    if latency_ms <= 1000:
        return 0.6 - (latency_ms - 300) / 700 * 0.5
    return max(0.0, 0.1 - (latency_ms - 1000) / 5000 * 0.1)


def _reachability_to_score(tcp_ok: bool, http_ok: bool, google_204_ok: bool) -> float:
    score = 0.0
    if tcp_ok:
        score += 0.30
    if http_ok:
        score += 0.20
    if google_204_ok:
        score += 0.50
    return round(score, 4)


def _trust_to_score(trust_value: int) -> float:
    return round((trust_value - 1) / 2, 4)


def score_server(
    config: str,
    protocol: str,
    source_url: str = "",
    trust_value: int = 2,
    latency_ms: Optional[float] = None,
    tcp_ok: bool = False,
    http_ok: bool = False,
    google_204_ok: bool = False,
    overlap_ratio: float = 0.0,
    freshness_score: float = 1.0,
) -> ServerScore:
    """Score a single server config and return a :class:`ServerScore`."""
    protocol_norm = protocol.lower().split("//")[0]
    return ServerScore(
        config=config,
        protocol=protocol_norm,
        latency_score=_latency_to_score(latency_ms),
        reachability_score=_reachability_to_score(tcp_ok, http_ok, google_204_ok),
        protocol_score=_PROTOCOL_SCORES.get(protocol_norm, 0.5),
        source_trust_score=_trust_to_score(trust_value),
        freshness_score=freshness_score,
        uniqueness_score=round(1.0 - overlap_ratio * 0.8, 4),
        source_url=source_url,
        latency_ms=latency_ms,
        health_details={
            "tcp_ok": tcp_ok,
            "http_ok": http_ok,
            "google_204_ok": google_204_ok,
        },
    )


def score_servers(
    health_results: List[Dict],
    source_trust_map: Optional[Dict[str, int]] = None,
    overlap_map: Optional[Dict[str, float]] = None,
    freshness_map: Optional[Dict[str, float]] = None,
) -> List[ServerScore]:
    """Score a batch of health-check result dicts, sorted descending by total."""
    if source_trust_map is None:
        source_trust_map = {}
    if overlap_map is None:
        overlap_map = {}
    if freshness_map is None:
        freshness_map = {}

    scores: List[ServerScore] = []
    for h in health_results:
        config = h.get("config", "")
        source_url = h.get("source_url", "")
        sc = score_server(
            config=config,
            protocol=h.get("protocol", "unknown"),
            source_url=source_url,
            trust_value=source_trust_map.get(source_url, 2),
            latency_ms=h.get("latency_ms"),
            tcp_ok=bool(h.get("tcp_ok", False)),
            http_ok=bool(h.get("http_ok", False)),
            google_204_ok=bool(h.get("google_204_ok", False)),
            overlap_ratio=overlap_map.get(source_url, 0.0),
            freshness_score=freshness_map.get(source_url, 1.0),
        )
        scores.append(sc)

    scores.sort(key=lambda s: s.total, reverse=True)
    logger.info(
        f"[scorer] Scored {len(scores)} servers. "
        f"A:{sum(1 for s in scores if s.grade == 'A')} "
        f"B:{sum(1 for s in scores if s.grade == 'B')} "
        f"C:{sum(1 for s in scores if s.grade == 'C')} "
        f"D+F:{sum(1 for s in scores if s.grade in ('D', 'F'))}"
    )
    return scores
