"""Shared latency-to-score conversion curves.

A single authoritative implementation used by scorer.py, health_checker.py,
and xray_connectivity.py — previously triplicated with divergent scales.

Two public helpers are provided:

    latency_to_score_100(ms) -> float in [0, 100]
        Used by health_checker and xray_connectivity (quality_score property).

    latency_to_score_1(ms) -> float in [0, 1]
        Used by scorer.py (_latency_to_score).

Both use the same piecewise-linear UX-tuned thresholds:

    ≤100 ms   → 100 %
    ≤300 ms   → 100 → 70 %
    ≤1000 ms  → 70  → 20 %
    ≤3000 ms  → 20  → 0  %
    >3000 ms  → 0   %
    None / ≤0 → 0   %
"""

from __future__ import annotations

from typing import Optional


def _piecewise(latency_ms: float) -> float:
    """Core piecewise-linear mapping, returns value in [0, 100]."""
    if latency_ms <= 100.0:
        return 100.0
    if latency_ms <= 300.0:
        return 100.0 - (latency_ms - 100.0) * (30.0 / 200.0)
    if latency_ms <= 1000.0:
        return 70.0 - (latency_ms - 300.0) * (50.0 / 700.0)
    if latency_ms <= 3000.0:
        return 20.0 - (latency_ms - 1000.0) * (20.0 / 2000.0)
    return 0.0


def latency_to_score_100(latency_ms: Optional[float]) -> float:
    """Map latency (ms) to a quality score in [0, 100].

    Args:
        latency_ms: Round-trip latency in milliseconds, or None.

    Returns:
        Float in [0.0, 100.0].  None / non-positive values return 0.0.
    """
    if latency_ms is None or latency_ms <= 0:
        return 0.0
    return round(max(0.0, _piecewise(latency_ms)), 1)


def latency_to_score_1(latency_ms: Optional[float]) -> float:
    """Map latency (ms) to a normalised score in [0, 1].

    Args:
        latency_ms: Round-trip latency in milliseconds, or None.

    Returns:
        Float in [0.0, 1.0].  None / non-positive values return 0.0.
    """
    if latency_ms is None or latency_ms <= 0:
        return 0.0
    return round(max(0.0, _piecewise(latency_ms)) / 100.0, 6)
