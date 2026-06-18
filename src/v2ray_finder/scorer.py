"""Server scoring engine for v2ray-finder.

Combines multiple signal dimensions into a single ``total`` score (0.0-1.0)
so callers can rank servers by overall quality.

Dimensions
----------
latency_score        TCP round-trip time, normalised and inverted.
reachability_score   Combination of tcp_ok + http_ok.
google_204_score     Whether the proxy passed the Google 204 real-world check.
protocol_score       Fixed weight per proxy protocol.
source_trust_score   Trustworthiness of the subscription source (1/2/3).
freshness_score      How recently the config was seen.
uniqueness_score     Inverse of overlap with other subscription sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .scoring_curves import latency_to_score_1

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROTOCOL_SCORES: Dict[str, float] = {
    "vless":  1.0,
    "trojan": 0.95,
    "vmess":  0.85,
    "ss":     0.70,
    "ssr":    0.50,
}

_WEIGHTS: Dict[str, float] = {
    "latency":       0.30,
    "reachability":  0.30,
    "protocol":      0.10,
    "source_trust":  0.10,
    "freshness":     0.05,
    "uniqueness":    0.05,
    "google_204":    0.10,
}

# Reachability component weights (TCP + HTTP only; google_204 is a separate dimension)
_REACH_W_TCP  = 0.70
_REACH_W_HTTP = 0.30


# ---------------------------------------------------------------------------
# Internal scoring helpers
# ---------------------------------------------------------------------------

def _latency_to_score(latency_ms: Optional[float]) -> float:
    """Map latency (ms) -> [0, 1].  Delegates to shared scoring_curves."""
    return latency_to_score_1(latency_ms)


# Keep old name as alias for backward compatibility
_latency_score = _latency_to_score


def _reachability_to_score(
    tcp_ok: bool,
    http_ok: bool,
) -> float:
    """Combine TCP + HTTP connectivity signals into a [0, 1] reachability score.

    google_204_ok is now a separate top-level dimension and is NOT included here.
    """
    score = (
        _REACH_W_TCP  * float(tcp_ok)
        + _REACH_W_HTTP * float(http_ok)
    )
    return round(min(max(score, 0.0), 1.0), 6)


def _trust_to_score(trust_level: int) -> float:
    """Map integer trust level (1=low, 2=medium, 3=high) to [0, 1]."""
    mapping = {1: 0.0, 2: 0.5, 3: 1.0}
    return mapping.get(trust_level, 0.0)


def _protocol_score(protocol: str) -> float:
    return _PROTOCOL_SCORES.get(protocol.lower(), 0.5)


# ---------------------------------------------------------------------------
# ServerScore dataclass
# ---------------------------------------------------------------------------

# Sentinel used as a safe default inside sort keys to avoid constructing a
# temporary ServerScore('', '') on every list item.
_ZERO_SCORE: "ServerScore"  # forward-declared; assigned after class definition


@dataclass
class ServerScore:
    """Scoring result for a single server."""

    config:             str
    protocol:           str
    latency_score:      float = 0.0
    reachability_score: float = 0.0
    protocol_score:     float = 0.0
    source_trust_score: float = 0.0
    freshness_score:    float = 0.0
    uniqueness_score:   float = 0.0
    google_204_score:   float = 0.0
    latency_ms:         Optional[float] = None
    health_details:     Dict[str, Any] = field(default_factory=dict)

    @property
    def total(self) -> float:
        raw = (
            _WEIGHTS["latency"]      * self.latency_score
            + _WEIGHTS["reachability"] * self.reachability_score
            + _WEIGHTS["protocol"]     * self.protocol_score
            + _WEIGHTS["source_trust"] * self.source_trust_score
            + _WEIGHTS["freshness"]    * self.freshness_score
            + _WEIGHTS["uniqueness"]   * self.uniqueness_score
            + _WEIGHTS["google_204"]   * self.google_204_score
        )
        return round(min(max(raw, 0.0), 1.0), 4)

    @property
    def grade(self) -> str:
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

    def __repr__(self) -> str:  # pragma: no cover
        lat = f"{self.latency_ms:.0f}ms" if self.latency_ms is not None else "n/a"
        return (
            f"<ServerScore protocol={self.protocol} total={self.total:.4f}"
            f" grade={self.grade} latency={lat}>"
        )


# Assign sentinel after class is defined so the type annotation resolves.
_ZERO_SCORE = ServerScore(config="", protocol="")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_server(
    config: str,
    protocol: str,
    latency_ms: Optional[float] = None,
    tcp_ok: bool = False,
    http_ok: bool = False,
    google_204_ok: bool = False,
    source_trust: int = 1,
    freshness_score: float = 0.0,
    overlap_ratio: float = 0.0,
) -> ServerScore:
    """Score a single server.

    Args:
        config:          Raw config string (vmess://, vless://, ...).
        protocol:        Protocol name. Trailing '://' or '//' stripped automatically.
        latency_ms:      TCP round-trip in milliseconds, or None.
        tcp_ok:          Whether TCP connection succeeded.
        http_ok:         Whether HTTP probe succeeded.
        google_204_ok:   Whether Google 204 check succeeded (now a live dimension).
        source_trust:    Integer 1/2/3 trust level of the subscription source.
        freshness_score: Pre-computed freshness score in [0, 1].
        overlap_ratio:   Fraction of other sources that also contain this config.

    Returns:
        ServerScore instance.
    """
    # Normalise protocol string
    proto = protocol.lower().rstrip("/").rstrip(":")

    ls   = _latency_to_score(latency_ms)
    rs   = _reachability_to_score(tcp_ok, http_ok)
    ps   = _protocol_score(proto)
    ts   = _trust_to_score(source_trust)
    us   = round(max(0.0, 1.0 - overlap_ratio), 6)
    g204 = 1.0 if google_204_ok else 0.0

    return ServerScore(
        config=config,
        protocol=proto,
        latency_ms=latency_ms,
        latency_score=ls,
        reachability_score=rs,
        protocol_score=ps,
        source_trust_score=ts,
        freshness_score=freshness_score,
        uniqueness_score=us,
        google_204_score=g204,
        health_details={
            "tcp_ok": tcp_ok,
            "http_ok": http_ok,
            "google_204_ok": google_204_ok,
        },
    )


def score_servers(
    health_results: List[Dict[str, Any]],
    overlap_map: Optional[Dict[str, float]] = None,
    descending: bool = True,
) -> List[ServerScore]:
    """Score a batch of health-check result dicts and return sorted scores.

    Each dict must contain at minimum:
        ``config``     -- raw config string
        ``protocol``   -- protocol name

    Optional keys:
        ``latency_ms``, ``tcp_ok``, ``http_ok``, ``google_204_ok``,
        ``source_trust``, ``freshness_score``, ``overlap_ratio``,
        ``source_url`` (used with *overlap_map*).

    Args:
        health_results: List of dicts from the health checker.
        overlap_map:    Optional {source_url: overlap_ratio} mapping.
        descending:     True -> best servers first (default).

    Returns:
        List of ServerScore objects sorted by total score.
    """
    if overlap_map is None:
        overlap_map = {}

    scores: List[ServerScore] = []
    for h in health_results:
        source_url    = h.get("source_url", "")
        overlap_ratio = h.get("overlap_ratio", overlap_map.get(source_url, 0.0))
        scores.append(
            score_server(
                config=h.get("config", ""),
                protocol=h.get("protocol", "unknown"),
                latency_ms=h.get("latency_ms"),
                tcp_ok=bool(h.get("tcp_ok", False)),
                http_ok=bool(h.get("http_ok", False)),
                google_204_ok=bool(h.get("google_204_ok", False)),
                source_trust=int(h.get("source_trust", 1)),
                freshness_score=float(h.get("freshness_score", 0.0)),
                overlap_ratio=float(overlap_ratio),
            )
        )
    return sorted(scores, key=lambda s: s.total, reverse=descending)


def sort_by_score(
    scores: List[ServerScore],
    descending: bool = True,
) -> List[ServerScore]:
    """Sort ServerScore objects by their total score."""
    return sorted(scores, key=lambda s: s.total, reverse=descending)


def sort_by_quality(
    health_results: List[Dict[str, Any]],
    descending: bool = True,
    overlap_map: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Score health_results, sort by total score, return enriched original dicts.

    The original dict is enriched with a ``_score`` key containing the
    ServerScore object.
    """
    scored = score_servers(health_results, overlap_map=overlap_map, descending=descending)
    score_by_config = {s.config: s for s in scored}
    result = sorted(
        health_results,
        key=lambda h: score_by_config.get(h.get("config", ""), _ZERO_SCORE).total,
        reverse=descending,
    )
    for item in result:
        item["_score"] = score_by_config.get(item.get("config", ""))
    return result
