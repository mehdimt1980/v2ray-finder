"""Tests for V1-Q4: layer3_cache stats in PipelineResult + clear_caches()."""
from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, patch

from v2ray_finder.pipeline import Pipeline, PipelineResult, StopController
from v2ray_finder.sources import SourceEntry, SourceTrust


VMESS = "vmess://eyJhZGQiOiIxMjcuMC4wLjEiLCJwb3J0IjoiODA4MCIsImlkIjoiZmFrZS11dWlkIn0="


def _make_source(url: str = "http://fake.example/sub") -> SourceEntry:
    return SourceEntry(url=url, trust=SourceTrust.MEDIUM, enabled=True)


def _pipeline_with_stub(configs=None, check_google_204=False) -> Pipeline:
    src = _make_source()
    p = Pipeline(
        sources=[src],
        check_health=False,
        check_google_204=check_google_204,
    )
    stub_result = {src.url: configs or [VMESS]}
    p._fetch_all_sync = lambda stop, cb: stub_result
    return p


# ---------------------------------------------------------------------------
# layer3_cache absent when check_google_204=False
# ---------------------------------------------------------------------------

class TestLayer3CacheAbsent(unittest.TestCase):

    def test_no_layer3_cache_key_without_google_204(self):
        p = _pipeline_with_stub(check_google_204=False)
        result = p.run()
        self.assertNotIn("layer3_cache", result.stats)

    def test_no_layer3_cache_when_health_disabled(self):
        p = _pipeline_with_stub(check_google_204=False)
        result = p.run()
        self.assertNotIn("layer3_cache", result.stats)


# ---------------------------------------------------------------------------
# layer3_cache present when check_google_204=True
# ---------------------------------------------------------------------------

class TestLayer3CachePresent(unittest.TestCase):

    def _run_with_mock_l3(self, cache_stats_ret=None):
        """Run a pipeline with check_google_204=True and a mocked layer3 checker."""
        if cache_stats_ret is None:
            cache_stats_ret = {"hits": 3, "misses": 7, "size": 4, "hit_rate": 30.0}

        src = _make_source()
        p = Pipeline(
            sources=[src],
            check_health=False,
            check_google_204=True,
        )
        p._fetch_all_sync = lambda stop, cb: {src.url: [VMESS]}

        # Inject a fake HealthChecker with a fake _layer3_checker
        fake_l3 = MagicMock()
        fake_l3.cache_stats = cache_stats_ret
        fake_checker = MagicMock()
        fake_checker._layer3_checker = fake_l3
        p._health_checker = fake_checker
        # check_health=False skips _run_health, so we force the stats injection
        # by temporarily enabling health to exercise the stats path
        p.check_health = True
        # Stub check_batch to return empty list (no real health checks)
        fake_checker.check_batch.return_value = []

        result = p.run()
        return result, fake_l3

    def test_layer3_cache_key_present(self):
        result, _ = self._run_with_mock_l3()
        self.assertIn("layer3_cache", result.stats)

    def test_layer3_cache_stats_values(self):
        expected = {"hits": 3, "misses": 7, "size": 4, "hit_rate": 30.0}
        result, _ = self._run_with_mock_l3(expected)
        self.assertEqual(result.stats["layer3_cache"], expected)

    def test_layer3_cache_stats_in_to_dict(self):
        result, _ = self._run_with_mock_l3()
        d = result.to_dict()
        self.assertIn("layer3_cache", d["stats"])

    def test_layer3_cache_hit_rate_type(self):
        result, _ = self._run_with_mock_l3({"hits": 0, "misses": 0, "size": 0, "hit_rate": 0.0})
        self.assertIsInstance(result.stats["layer3_cache"]["hit_rate"], float)


# ---------------------------------------------------------------------------
# clear_caches()
# ---------------------------------------------------------------------------

class TestClearCaches(unittest.TestCase):

    def test_clear_caches_no_error_when_nothing_set(self):
        p = Pipeline(sources=[_make_source()], check_health=False)
        p.clear_caches()  # must not raise

    def test_clear_caches_calls_source_cache_clear(self):
        from v2ray_finder.cache import CacheManager
        src = _make_source()
        p = Pipeline(sources=[src], check_health=False, cache_enabled=True)
        mock_cache = MagicMock(spec=CacheManager)
        p._cache = mock_cache
        p.clear_caches()
        mock_cache.clear.assert_called_once()

    def test_clear_caches_calls_layer3_clear(self):
        p = Pipeline(sources=[_make_source()], check_health=False)
        fake_l3 = MagicMock()
        fake_checker = MagicMock()
        fake_checker._layer3_checker = fake_l3
        p._health_checker = fake_checker
        p.clear_caches()
        fake_l3.clear_result_cache.assert_called_once()

    def test_clear_caches_no_layer3_checker(self):
        p = Pipeline(sources=[_make_source()], check_health=False)
        fake_checker = MagicMock()
        fake_checker._layer3_checker = None
        p._health_checker = fake_checker
        p.clear_caches()  # must not raise

    def test_clear_caches_no_health_checker(self):
        p = Pipeline(sources=[_make_source()], check_health=False)
        p._health_checker = None
        p.clear_caches()  # must not raise

    def test_clear_caches_handles_exception_gracefully(self):
        p = Pipeline(sources=[_make_source()], check_health=False)
        fake_l3 = MagicMock()
        fake_l3.clear_result_cache.side_effect = RuntimeError("boom")
        fake_checker = MagicMock()
        fake_checker._layer3_checker = fake_l3
        p._health_checker = fake_checker
        p.clear_caches()  # must not raise


# ---------------------------------------------------------------------------
# _health_checker reuse across run() calls
# ---------------------------------------------------------------------------

class TestHealthCheckerReuse(unittest.TestCase):

    def test_health_checker_created_once_across_runs(self):
        """The same HealthChecker instance is reused on repeated run() calls."""
        from v2ray_finder.health_checker import HealthChecker

        src = _make_source()
        p = Pipeline(sources=[src], check_health=True)
        p._fetch_all_sync = lambda stop, cb: {src.url: [VMESS]}

        with patch(
            "v2ray_finder.pipeline.HealthChecker",
            wraps=HealthChecker,
        ) as mock_hc_cls:
            mock_hc_cls.return_value = MagicMock()
            mock_hc_cls.return_value.check_batch.return_value = []

            p.run()
            p.run()

            # HealthChecker should be instantiated exactly once
            self.assertEqual(mock_hc_cls.call_count, 1)


if __name__ == "__main__":
    unittest.main()
