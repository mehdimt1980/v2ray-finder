"""Tests for V1-C1: correct per-config source attribution in Pipeline.

The bug: _build_config_source_map previously used unconditional assignment
    config_source[cfg] = url
with sources sorted in descending trust order.  Because the loop iterated
high-trust → low-trust and always overwrote, the *last* (lowest-trust)
source won for any shared config — the opposite of the intended behaviour.

The fix: use setdefault so the first (highest-trust) assignment is kept.

Tests in this file verify:
1. High-trust source wins over low-trust for a shared config.
2. Non-shared configs each carry their own source's trust.
3. overlap_ratio per server reflects its actual source.
4. The unchecked path (check_health=False) also carries correct attribution.
5. Single-source baseline — no collision, attribution trivially correct.
6. Unknown config (not in any source) falls back to empty url + trust 1.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from v2ray_finder.pipeline import Pipeline, PipelineResult
from v2ray_finder.sources import SourceEntry, SourceTrust


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SHARED  = "vmess://AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
HIGH_ONLY = "vmess://BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=="
LOW_ONLY  = "vmess://CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC=="

URL_HIGH = "http://high.example/sub"
URL_LOW  = "http://low.example/sub"


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
        src_low  = _src(URL_LOW,  SourceTrust.LOW)
        stub = {
            URL_HIGH: [SHARED, HIGH_ONLY],
            URL_LOW:  [SHARED, LOW_ONLY],
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
        src_low  = _src(URL_LOW,  SourceTrust.LOW)
        stub = {
            URL_HIGH: [SHARED, HIGH_ONLY],
            URL_LOW:  [SHARED, LOW_ONLY],
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
        src_low  = _src(URL_LOW,  SourceTrust.LOW)
        stub = {
            URL_HIGH: [SHARED, HIGH_ONLY],
            URL_LOW:  [SHARED, LOW_ONLY],
        }
        p = _make_pipeline([src_high, src_low], stub)
        result = p.run()

        # overlap_map is keyed by source URL; each config's overlap_ratio must
        # equal result.overlap_map[its source_url], not some other source.
        hd_map = {d["config"]: d for d in result.health_dicts}
        for cfg, d in hd_map.items():
            expected_overlap = result.overlap_map.get(d["source_url"], 0.0)
            self.assertAlmostEqual(
                d["overlap_ratio"], expected_overlap, places=6,
                msg=f"overlap_ratio mismatch for {cfg[:40]}",
            )


# ---------------------------------------------------------------------------
# 4. Unchecked path (check_health=False) also carries correct attribution
# ---------------------------------------------------------------------------

class TestUncheckedPathAttributionCorrect(unittest.TestCase):

    def test_unchecked_shared_config_high_trust_wins(self):
        src_high = _src(URL_HIGH, SourceTrust.HIGH)
        src_low  = _src(URL_LOW,  SourceTrust.LOW)
        stub = {
            URL_HIGH: [SHARED, HIGH_ONLY],
            URL_LOW:  [SHARED, LOW_ONLY],
        }
        p = _make_pipeline([src_high, src_low], stub, check_health=False)
        result = p.run()
        hd_map = {d["config"]: d for d in result.health_dicts}

        self.assertEqual(hd_map[SHARED]["source_url"],   URL_HIGH)
        self.assertEqual(hd_map[SHARED]["source_trust"], SourceTrust.HIGH.value)

    def test_unchecked_non_shared_carries_own_source(self):
        src_high = _src(URL_HIGH, SourceTrust.HIGH)
        src_low  = _src(URL_LOW,  SourceTrust.LOW)
        stub = {
            URL_HIGH: [HIGH_ONLY],
            URL_LOW:  [LOW_ONLY],
        }
        p = _make_pipeline([src_high, src_low], stub, check_health=False)
        result = p.run()
        hd_map = {d["config"]: d for d in result.health_dicts}

        self.assertEqual(hd_map[HIGH_ONLY]["source_url"],   URL_HIGH)
        self.assertEqual(hd_map[LOW_ONLY]["source_url"],    URL_LOW)


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
            self.assertEqual(d["source_url"],   URL_HIGH)
            self.assertEqual(d["source_trust"], SourceTrust.HIGH.value)


# ---------------------------------------------------------------------------
# 6. Unknown config falls back gracefully
# ---------------------------------------------------------------------------

class TestUnknownConfigFallback(unittest.TestCase):
    """_build_config_source_map returns '' for configs not in any source.

    This can happen if a config was injected via a test stub that bypasses
    servers_by_source.  The pipeline must not raise and must default to
    source_url='' and source_trust=1.
    """

    def test_unknown_config_fallback_values(self):
        src = _src(URL_HIGH, SourceTrust.HIGH)
        # Fetch stub returns a config that is NOT in the servers_by_source
        # dict passed to _build_config_source_map.  We simulate this by
        # letting the pipeline run normally with an empty source so the
        # map is empty, then checking _make_unchecked_dict directly.
        p = Pipeline(sources=[src], check_health=False)
        p._fetch_all_sync = lambda stop, cb: {}

        unknown_cfg = "vmess://ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ=="
        d = p._make_unchecked_dict(unknown_cfg, {}, {})
        self.assertEqual(d["source_url"],   "")
        self.assertEqual(d["source_trust"], 1)
        self.assertAlmostEqual(d["overlap_ratio"], 0.0)


# ---------------------------------------------------------------------------
# 7. Equal-trust tie-breaking: first-wins (stable)
# ---------------------------------------------------------------------------

class TestEqualTrustFirstWins(unittest.TestCase):
    """When two sources have identical trust, the first source in iteration
    order (as returned by sorted(..., reverse=True)) wins.
    Both have trust=MEDIUM so we just assert *one* of them wins consistently.
    """

    def test_equal_trust_attribution_is_stable(self):
        URL_A = "http://alpha.example/sub"
        URL_B = "http://beta.example/sub"
        src_a = _src(URL_A, SourceTrust.MEDIUM)
        src_b = _src(URL_B, SourceTrust.MEDIUM)
        stub = {
            URL_A: [SHARED],
            URL_B: [SHARED],
        }
        p = _make_pipeline([src_a, src_b], stub, check_health=False)
        result = p.run()
        hd = next(d for d in result.health_dicts if d["config"] == SHARED)
        # Either source is acceptable; what must NOT happen is an exception
        # or an empty source_url.
        self.assertIn(hd["source_url"], (URL_A, URL_B))
        self.assertEqual(hd["source_trust"], SourceTrust.MEDIUM.value)

        # Run a second time and assert the attribution is the same (stable).
        result2 = p.run()
        hd2 = next(d for d in result2.health_dicts if d["config"] == SHARED)
        self.assertEqual(hd["source_url"], hd2["source_url"])


if __name__ == "__main__":
    unittest.main()
