"""Tests for V1-C1: correct per-config source attribution in Pipeline.

The bug: _build_config_source_map previously used unconditional assignment
    config_source[cfg] = url
with sources sorted in descending trust order.  Because the loop iterated
high-trust → low-trust and always overwrote, the *last* (lowest-trust)
source won for any shared config — the opposite of the intended behaviour.

The fix: use setdefault so the first (highest-trust) assignment is kept.

V1-C1 additional fixes in this file:
- Equal-trust tie-breaking is now deterministic: sort key is (-trust, url),
  so among equal-trust sources the lexicographically smallest URL always wins.
- Unknown configs (not in any source) receive source_trust=0, not 1 (MEDIUM),
  and a WARNING is emitted.
- PipelineResult.source_attribution exposes a per-source config count and
  trust distribution summary.

Tests in this file verify:
1. High-trust source wins over low-trust for a shared config.
2. Non-shared configs each carry their own source's trust.
3. overlap_ratio per server reflects its actual source.
4. The unchecked path (check_health=False) also carries correct attribution.
5. Single-source baseline — no collision, attribution trivially correct.
6. Unknown config falls back to source_url='' and source_trust=0 (not 1).
7. Equal-trust tie-breaking is deterministic: smallest URL wins.
8. Fallback emits a WARNING log entry.
9. source_attribution summary counts and trust distribution are correct.
"""

from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

from v2ray_finder.pipeline import Pipeline, PipelineResult
from v2ray_finder.sources import SourceEntry, SourceTrust

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SHARED = "vmess://AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
HIGH_ONLY = "vmess://BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=="
LOW_ONLY = "vmess://CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC=="

URL_HIGH = "http://high.example/sub"
URL_LOW = "http://low.example/sub"


def _src(url: str, trust: SourceTrust) -> SourceEntry:
    return SourceEntry(url=url, trust=trust, enabled=True)


def _make_pipeline(sources, stub: dict, check_health: bool = False) -> Pipeline:
    p = Pipeline(sources=sources, check_health=check_health)
    p._fetch_all_sync = lambda stop, cb: stub
    return p


# ---------------------------------------------------------------------------
# 1. High-trust wins for shared config
# ---------------------------------------------------------------------------


class TestHighTrustWinsForSharedConfig(unittest.TestCase):

    def setUp(self):
        src_high = _src(URL_HIGH, SourceTrust.HIGH)
        src_low = _src(URL_LOW, SourceTrust.LOW)
        stub = {
            URL_HIGH: [SHARED, HIGH_ONLY],
            URL_LOW: [SHARED, LOW_ONLY],
        }
        self.p = _make_pipeline([src_high, src_low], stub)
        self.result = self.p.run()

    def _dict_for(self, config: str):
        return next(d for d in self.result.health_dicts if d["config"] == config)

    def test_shared_config_attributed_to_high_trust_source(self):
        d = self._dict_for(SHARED)
        self.assertEqual(d["source_url"], URL_HIGH)

    def test_shared_config_carries_high_trust_value(self):
        d = self._dict_for(SHARED)
        self.assertEqual(d["source_trust"], SourceTrust.HIGH.value)

    def test_low_trust_source_not_attributed_to_shared_config(self):
        d = self._dict_for(SHARED)
        self.assertNotEqual(d["source_url"], URL_LOW)


# ---------------------------------------------------------------------------
# 2. Non-shared configs carry their own source
# ---------------------------------------------------------------------------


class TestNonSharedConfigsCarryOwnSource(unittest.TestCase):

    def setUp(self):
        src_high = _src(URL_HIGH, SourceTrust.HIGH)
        src_low = _src(URL_LOW, SourceTrust.LOW)
        stub = {
            URL_HIGH: [SHARED, HIGH_ONLY],
            URL_LOW: [SHARED, LOW_ONLY],
        }
        p = _make_pipeline([src_high, src_low], stub)
        result = p.run()
        self.hd = {d["config"]: d for d in result.health_dicts}

    def test_high_only_config_attributed_to_high_source(self):
        self.assertEqual(self.hd[HIGH_ONLY]["source_url"], URL_HIGH)
        self.assertEqual(self.hd[HIGH_ONLY]["source_trust"], SourceTrust.HIGH.value)

    def test_low_only_config_attributed_to_low_source(self):
        self.assertEqual(self.hd[LOW_ONLY]["source_url"], URL_LOW)
        self.assertEqual(self.hd[LOW_ONLY]["source_trust"], SourceTrust.LOW.value)


# ---------------------------------------------------------------------------
# 3. overlap_ratio reflects actual source
# ---------------------------------------------------------------------------


class TestOverlapRatioReflectsActualSource(unittest.TestCase):
    """overlap_ratio for each config must come from its attributed source URL."""

    def test_overlap_ratio_matches_source(self):
        src_high = _src(URL_HIGH, SourceTrust.HIGH)
        src_low = _src(URL_LOW, SourceTrust.LOW)
        stub = {
            URL_HIGH: [SHARED, HIGH_ONLY],
            URL_LOW: [SHARED, LOW_ONLY],
        }
        p = _make_pipeline([src_high, src_low], stub)
        result = p.run()

        hd_map = {d["config"]: d for d in result.health_dicts}
        for cfg, d in hd_map.items():
            expected_overlap = result.overlap_map.get(d["source_url"], 0.0)
            self.assertAlmostEqual(
                d["overlap_ratio"],
                expected_overlap,
                places=6,
                msg=f"overlap_ratio mismatch for {cfg[:40]}",
            )


# ---------------------------------------------------------------------------
# 4. Unchecked path (check_health=False) also carries correct attribution
# ---------------------------------------------------------------------------


class TestUncheckedPathAttributionCorrect(unittest.TestCase):

    def test_unchecked_shared_config_high_trust_wins(self):
        src_high = _src(URL_HIGH, SourceTrust.HIGH)
        src_low = _src(URL_LOW, SourceTrust.LOW)
        stub = {
            URL_HIGH: [SHARED, HIGH_ONLY],
            URL_LOW: [SHARED, LOW_ONLY],
        }
        p = _make_pipeline([src_high, src_low], stub, check_health=False)
        result = p.run()
        hd_map = {d["config"]: d for d in result.health_dicts}

        self.assertEqual(hd_map[SHARED]["source_url"], URL_HIGH)
        self.assertEqual(hd_map[SHARED]["source_trust"], SourceTrust.HIGH.value)

    def test_unchecked_non_shared_carries_own_source(self):
        src_high = _src(URL_HIGH, SourceTrust.HIGH)
        src_low = _src(URL_LOW, SourceTrust.LOW)
        stub = {
            URL_HIGH: [HIGH_ONLY],
            URL_LOW: [LOW_ONLY],
        }
        p = _make_pipeline([src_high, src_low], stub, check_health=False)
        result = p.run()
        hd_map = {d["config"]: d for d in result.health_dicts}

        self.assertEqual(hd_map[HIGH_ONLY]["source_url"], URL_HIGH)
        self.assertEqual(hd_map[LOW_ONLY]["source_url"], URL_LOW)


# ---------------------------------------------------------------------------
# 5. Single-source baseline
# ---------------------------------------------------------------------------


class TestSingleSourceBaseline(unittest.TestCase):

    def test_single_source_attribution_trivially_correct(self):
        src = _src(URL_HIGH, SourceTrust.HIGH)
        stub = {URL_HIGH: [SHARED, HIGH_ONLY]}
        p = _make_pipeline([src], stub, check_health=False)
        result = p.run()
        for d in result.health_dicts:
            self.assertEqual(d["source_url"], URL_HIGH)
            self.assertEqual(d["source_trust"], SourceTrust.HIGH.value)


# ---------------------------------------------------------------------------
# 6. Unknown config falls back to source_url='' and source_trust=0 (V1-C1 fix)
# ---------------------------------------------------------------------------


class TestUnknownConfigFallback(unittest.TestCase):
    """_build_config_source_map returns '' for configs not in any source.

    V1-C1 fix: such configs must get source_trust=0 (not 1/MEDIUM) so the
    scorer does not silently reward them with a positive trust value.
    """

    def test_unknown_config_fallback_values(self):
        src = _src(URL_HIGH, SourceTrust.HIGH)
        p = Pipeline(sources=[src], check_health=False)
        p._fetch_all_sync = lambda stop, cb: {}

        unknown_cfg = "vmess://ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ=="
        d = p._make_unchecked_dict(unknown_cfg, {}, {})
        self.assertEqual(d["source_url"], "")
        # V1-C1 fix: trust must be 0, not 1
        self.assertEqual(d["source_trust"], 0)
        self.assertAlmostEqual(d["overlap_ratio"], 0.0)


# ---------------------------------------------------------------------------
# 7. Equal-trust tie-breaking: smallest URL wins (deterministic)
# ---------------------------------------------------------------------------


class TestEqualTrustFirstWins(unittest.TestCase):
    """V1-C1 fix: when two sources have identical trust, the sort key is
    (-trust, url), so the lexicographically smallest URL always wins.
    This is deterministic regardless of dict insertion order.
    """

    # URL_A < URL_B lexicographically → URL_A must win
    URL_A = "http://alpha.example/sub"
    URL_B = "http://beta.example/sub"

    def _run(self) -> dict:
        src_a = _src(self.URL_A, SourceTrust.MEDIUM)
        src_b = _src(self.URL_B, SourceTrust.MEDIUM)
        stub = {
            self.URL_A: [SHARED],
            self.URL_B: [SHARED],
        }
        p = _make_pipeline([src_a, src_b], stub, check_health=False)
        result = p.run()
        return next(d for d in result.health_dicts if d["config"] == SHARED)

    def test_smaller_url_wins_on_equal_trust(self):
        hd = self._run()
        # URL_A ("alpha") < URL_B ("beta") → URL_A must win
        self.assertEqual(hd["source_url"], self.URL_A)
        self.assertEqual(hd["source_trust"], SourceTrust.MEDIUM.value)

    def test_equal_trust_attribution_is_stable_across_runs(self):
        hd1 = self._run()
        hd2 = self._run()
        self.assertEqual(hd1["source_url"], hd2["source_url"])


# ---------------------------------------------------------------------------
# 8. Fallback emits a WARNING log entry
# ---------------------------------------------------------------------------


class TestFallbackWarningLogged(unittest.TestCase):
    """_make_unchecked_dict must emit a WARNING when a config has no source."""

    def test_warning_emitted_for_unknown_config(self):
        src = _src(URL_HIGH, SourceTrust.HIGH)
        p = Pipeline(sources=[src], check_health=False)

        unknown_cfg = "vmess://ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ=="
        with self.assertLogs("v2ray_finder.pipeline", level="WARNING") as cm:
            p._make_unchecked_dict(unknown_cfg, {}, {})

        self.assertTrue(
            any("attribution unknown" in msg for msg in cm.output),
            msg=f"Expected 'attribution unknown' in log output, got: {cm.output}",
        )


# ---------------------------------------------------------------------------
# 9. source_attribution summary
# ---------------------------------------------------------------------------


class TestSourceAttributionSummary(unittest.TestCase):
    """PipelineResult.source_attribution must return correct counts and trust."""

    def test_summary_counts_per_source(self):
        src_high = _src(URL_HIGH, SourceTrust.HIGH)
        src_low = _src(URL_LOW, SourceTrust.LOW)
        stub = {
            URL_HIGH: [SHARED, HIGH_ONLY],
            URL_LOW: [SHARED, LOW_ONLY],
        }
        p = _make_pipeline([src_high, src_low], stub, check_health=False)
        result = p.run()

        summary = result.source_attribution
        by_source = summary["by_source"]

        # SHARED → HIGH, HIGH_ONLY → HIGH, LOW_ONLY → LOW
        self.assertEqual(by_source[URL_HIGH]["config_count"], 2)
        self.assertEqual(by_source[URL_HIGH]["source_trust"], SourceTrust.HIGH.value)
        self.assertEqual(by_source[URL_LOW]["config_count"], 1)
        self.assertEqual(by_source[URL_LOW]["source_trust"], SourceTrust.LOW.value)

    def test_trust_distribution_correct(self):
        src_high = _src(URL_HIGH, SourceTrust.HIGH)
        src_low = _src(URL_LOW, SourceTrust.LOW)
        stub = {
            URL_HIGH: [SHARED, HIGH_ONLY],
            URL_LOW: [LOW_ONLY],
        }
        p = _make_pipeline([src_high, src_low], stub, check_health=False)
        result = p.run()

        dist = result.source_attribution["trust_distribution"]
        # SHARED → HIGH(3), HIGH_ONLY → HIGH(3), LOW_ONLY → LOW(1)
        self.assertEqual(dist.get(SourceTrust.HIGH.value, 0), 2)
        self.assertEqual(dist.get(SourceTrust.LOW.value, 0), 1)

    def test_unattributed_count_for_empty_source_url(self):
        """Configs with source_url='' must appear in unattributed_count."""
        result = PipelineResult()
        result.health_dicts = [
            {"config": "vmess://A", "source_url": "", "source_trust": 0},
            {"config": "vmess://B", "source_url": URL_HIGH, "source_trust": 3},
        ]
        summary = result.source_attribution
        self.assertEqual(summary["unattributed_count"], 1)
        self.assertEqual(summary["by_source"][URL_HIGH]["config_count"], 1)


if __name__ == "__main__":
    unittest.main()
