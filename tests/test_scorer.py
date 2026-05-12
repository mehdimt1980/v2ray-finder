"""Unit tests for scorer.py.

Covers:
- _latency_to_score: full curve including boundaries and clamping
- _reachability_to_score: tcp/http/google_204 combinations
- _trust_to_score: 1/2/3 mapping
- ServerScore.total: weighted formula and clamping
- ServerScore.grade: A/B/C/D/F thresholds
- score_server: public API smoke tests
- score_servers: batch sorting and empty input
"""

from __future__ import annotations

import pytest

from v2ray_finder.scorer import (
    ServerScore,
    _latency_to_score,
    _reachability_to_score,
    _trust_to_score,
    score_server,
    score_servers,
    _WEIGHTS,
    _PROTOCOL_SCORES,
)


# ---------------------------------------------------------------------------
# _latency_to_score
# ---------------------------------------------------------------------------


class TestLatencyToScore:
    def test_none_returns_zero(self):
        assert _latency_to_score(None) == 0.0

    def test_zero_returns_zero(self):
        # 0ms means unmeasured / no data — score is 0 by design
        assert _latency_to_score(0) == 0.0

    def test_negative_returns_zero(self):
        assert _latency_to_score(-50) == 0.0

    def test_under_100ms_is_perfect(self):
        assert _latency_to_score(50) == 1.0
        assert _latency_to_score(100) == 1.0

    def test_200ms_in_middle_band(self):
        score = _latency_to_score(200)
        assert 0.6 < score < 1.0

    def test_300ms_boundary(self):
        score = _latency_to_score(300)
        # At 300ms the formula transitions; result should be between 0.5 and 0.9
        assert 0.5 <= score <= 0.9

    def test_1000ms_low_but_positive(self):
        score = _latency_to_score(1000)
        assert 0.0 <= score <= 0.15

    def test_6000ms_floored_at_zero(self):
        score = _latency_to_score(6000)
        assert score == 0.0

    def test_monotonically_decreasing(self):
        """Higher latency → lower or equal score.

        Note: 0ms is excluded because _latency_to_score(0) == 0.0 by design
        (0 means unmeasured). The meaningful range starts at 1ms.
        """
        latencies = [1, 50, 100, 200, 300, 500, 800, 1000, 2000, 5000, 9999]
        scores = [_latency_to_score(l) for l in latencies]
        for i in range(1, len(scores)):
            assert scores[i] <= scores[i - 1] + 1e-9, (
                f"score increased from {latencies[i-1]}ms to {latencies[i]}ms"
            )


# ---------------------------------------------------------------------------
# _reachability_to_score
# ---------------------------------------------------------------------------


class TestReachabilityToScore:
    def test_all_false(self):
        assert _reachability_to_score(False, False, False) == 0.0

    def test_tcp_only(self):
        score = _reachability_to_score(True, False, False)
        assert abs(score - 0.70) < 1e-6

    def test_http_only(self):
        score = _reachability_to_score(False, True, False)
        assert abs(score - 0.30) < 1e-6

    def test_tcp_and_http(self):
        score = _reachability_to_score(True, True, False)
        assert abs(score - 1.00) < 1e-6

    def test_google_204_carries_zero_weight(self):
        """google_204=True should NOT change the score (weight is 0 until xray integration)."""
        without = _reachability_to_score(True, False, False)
        with_204 = _reachability_to_score(True, False, True)
        assert abs(without - with_204) < 1e-9

    def test_all_true(self):
        # Still 1.0 because google_204 weight is zero
        assert abs(_reachability_to_score(True, True, True) - 1.00) < 1e-6


# ---------------------------------------------------------------------------
# _trust_to_score
# ---------------------------------------------------------------------------


class TestTrustToScore:
    def test_trust_1_is_zero(self):
        assert _trust_to_score(1) == 0.0

    def test_trust_2_is_half(self):
        assert abs(_trust_to_score(2) - 0.5) < 1e-6

    def test_trust_3_is_full(self):
        assert abs(_trust_to_score(3) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# ServerScore.total and .grade
# ---------------------------------------------------------------------------


class TestServerScore:
    def _make(self, **kwargs) -> ServerScore:
        defaults = dict(
            config="vmess://x",
            protocol="vmess",
            latency_score=0.0,
            reachability_score=0.0,
            protocol_score=0.0,
            source_trust_score=0.0,
            freshness_score=0.0,
            uniqueness_score=0.0,
        )
        defaults.update(kwargs)
        return ServerScore(**defaults)

    def test_all_zero_total(self):
        s = self._make()
        assert s.total == 0.0

    def test_all_one_total(self):
        s = self._make(
            latency_score=1.0,
            reachability_score=1.0,
            protocol_score=1.0,
            source_trust_score=1.0,
            freshness_score=1.0,
            uniqueness_score=1.0,
        )
        assert s.total == 1.0

    def test_total_clamped_above_one(self):
        s = self._make(
            latency_score=2.0,
            reachability_score=2.0,
            protocol_score=2.0,
            source_trust_score=2.0,
            freshness_score=2.0,
            uniqueness_score=2.0,
        )
        assert s.total <= 1.0

    def test_total_clamped_below_zero(self):
        s = self._make(
            latency_score=-1.0,
            reachability_score=-1.0,
            protocol_score=-1.0,
            source_trust_score=-1.0,
            freshness_score=-1.0,
            uniqueness_score=-1.0,
        )
        assert s.total >= 0.0

    def test_grade_A_at_0_80(self):
        s = self._make(
            latency_score=1.0,
            reachability_score=1.0,
            protocol_score=1.0,
            source_trust_score=1.0,
            freshness_score=1.0,
            uniqueness_score=1.0,
        )
        assert s.grade == "A"

    def test_grade_F_at_zero(self):
        s = self._make()
        assert s.grade == "F"

    def test_grade_boundaries(self):
        """Verify each grade bucket by constructing scores at boundaries."""
        cases = [
            (1.0, "A"),
            (0.80, "A"),
            (0.60, "B"),
            (0.40, "C"),
            (0.20, "D"),
            (0.19, "F"),
            (0.0, "F"),
        ]
        for total_target, expected_grade in cases:
            # Use latency_score as a proxy to hit the target
            latency_weight = _WEIGHTS["latency"]
            latency_score = min(1.0, total_target / latency_weight) if latency_weight > 0 else 0.0
            s = self._make(latency_score=latency_score)
            if s.total >= 0.80:
                assert s.grade == "A"
            elif s.total >= 0.60:
                assert s.grade == "B"
            elif s.total >= 0.40:
                assert s.grade == "C"
            elif s.total >= 0.20:
                assert s.grade == "D"
            else:
                assert s.grade == "F"

    def test_repr_contains_protocol_and_total(self):
        s = self._make(protocol="vless")
        r = repr(s)
        assert "vless" in r
        assert "total=" in r


# ---------------------------------------------------------------------------
# score_server
# ---------------------------------------------------------------------------


class TestScoreServer:
    def test_smoke_all_defaults(self):
        result = score_server(config="vmess://x", protocol="vmess")
        assert isinstance(result, ServerScore)
        assert 0.0 <= result.total <= 1.0

    def test_protocol_score_vless_is_highest(self):
        vless = score_server("v", "vless", tcp_ok=True)
        vmess = score_server("v", "vmess", tcp_ok=True)
        assert vless.total > vmess.total

    def test_known_protocols_have_defined_scores(self):
        for proto in ("vless", "trojan", "ss", "vmess", "ssr"):
            s = score_server("x", proto)
            assert s.protocol_score == _PROTOCOL_SCORES[proto]

    def test_unknown_protocol_falls_back(self):
        s = score_server("x", "shadowsocks")
        assert s.protocol_score == 0.5

    def test_health_details_stored(self):
        s = score_server("x", "vmess", tcp_ok=True, http_ok=False, google_204_ok=True)
        assert s.health_details["tcp_ok"] is True
        assert s.health_details["http_ok"] is False
        assert s.health_details["google_204_ok"] is True

    def test_google_204_silently_ignored_in_total(self):
        without = score_server("x", "vmess", tcp_ok=True, google_204_ok=False)
        with_204 = score_server("x", "vmess", tcp_ok=True, google_204_ok=True)
        assert abs(without.total - with_204.total) < 1e-9

    def test_overlap_ratio_reduces_uniqueness(self):
        no_overlap = score_server("x", "vmess", overlap_ratio=0.0)
        full_overlap = score_server("x", "vmess", overlap_ratio=1.0)
        assert no_overlap.uniqueness_score > full_overlap.uniqueness_score

    def test_protocol_normalised_from_uri(self):
        """Protocol 'vmess//' (accidentally passed as URI) should strip to 'vmess'."""
        s = score_server("x", "vmess//")
        assert s.protocol == "vmess"


# ---------------------------------------------------------------------------
# score_servers (batch)
# ---------------------------------------------------------------------------


class TestScoreServers:
    def _hr(self, config: str, protocol: str, latency_ms: float, tcp_ok: bool) -> dict:
        return {
            "config": config,
            "protocol": protocol,
            "latency_ms": latency_ms,
            "tcp_ok": tcp_ok,
            "http_ok": False,
            "google_204_ok": False,
            "source_url": "http://src",
        }

    def test_empty_returns_empty(self):
        assert score_servers([]) == []

    def test_sorted_descending(self):
        health_results = [
            self._hr("a", "vmess", latency_ms=1000, tcp_ok=False),
            self._hr("b", "vless", latency_ms=50, tcp_ok=True),
            self._hr("c", "trojan", latency_ms=200, tcp_ok=True),
        ]
        scored = score_servers(health_results)
        totals = [s.total for s in scored]
        for i in range(1, len(totals)):
            assert totals[i] <= totals[i - 1] + 1e-9

    def test_overlap_ratio_field_passed(self):
        hr = self._hr("a", "vmess", 100, True)
        hr["overlap_ratio"] = 0.9
        scored = score_servers([hr])
        assert scored[0].uniqueness_score < 1.0
