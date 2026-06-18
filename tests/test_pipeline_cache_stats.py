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
        """layer3_cache must not appear when check_google_204=False."""
        p = _pipeline_with_stub(check_google_204=False)
        result = p.run()
        self.assertNotIn("layer3_cache", result.stats)

    def test_no_layer3_cache_when_google_204_true_but_health_skipped(self):
        """layer3_cache must not appear when check_health=False even if
        check_google_204=True, because _run_health is never called and
        _health_checker is never instantiated."""
        src = _make_source()
        p = Pipeline(
            sources=[src],
            check_health=False,   # skips _run_health entirely
            check_google_204=True,
        )
        p._fetch_all_sync = lambda stop, cb: {src.url: [VMESS]}
        result = p.run()
        # _health_checker is None → the stats injection branch is skipped
        self.assertNotIn("layer3_cache", result.stats)


# ---------------------------------------------------------------------------
# layer3_cache present when check_google_204=True and health runs
# ---------------------------------------------------------------------------

class TestLayer3CachePresent(unittest.TestCase):

    def _run_with_mock_l3(self, cache_stats_ret=None):
        """Run a pipeline with check_health=True, check_google_204=True and a
        mocked HealthChecker whose _layer3_checker exposes fake cache stats."""
        if cache_stats_ret is None:
            cache_stats_ret = {"hits": 3, "misses": 7, "size": 4, "hit_rate": 30.0}

        src = _make_source()
        p = Pipeline(
            sources=[src],
            check_health=True,
            check_google_204=True,
        )
        p._fetch_all_sync = lambda stop, cb: {src.url: [VMESS]}

        # Build a fake HealthChecker with _layer3_checker carrying our stats.
        fake_l3 = MagicMock()
        fake_l3.cache_stats = cache_stats_ret
        fake_checker = MagicMock()
        fake_checker._layer3_checker = fake_l3
        fake_checker.check_batch.return_value = []

        # Inject the pre-built fake so _run_health reuses it instead of
        # constructing a real one (the reuse branch: if self._health_checker
        # is not None, skip instantiation).
        p._health_checker = fake_checker

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
        """The same HealthChecker instance is reused on repeated run() calls.

        Strategy: patch HealthChecker at its *definition* site
        (v2ray_finder.health_checker.HealthChecker) so the local import
        inside _run_health picks up the mock regardless of import caching.
        The mock's return_value is a pre-built fake that satisfies the
        interface expected by _run_health.
        """
        src = _make_source()
        p = Pipeline(sources=[src], check_health=True)
        p._fetch_all_sync = lambda stop, cb: {src.url: [VMESS]}

        fake_checker_instance = MagicMock()
        fake_checker_instance.check_batch.return_value = []
        # _layer3_checker must be set so stats injection doesn't crash
        fake_checker_instance._layer3_checker = None

        with patch(
            "v2ray_finder.health_checker.HealthChecker",
            return_value=fake_checker_instance,
        ) as mock_hc_cls:
            p.run()
            p.run()

            # HealthChecker constructor called exactly once:
            # second run() reuses p._health_checker set in first run().
            self.assertEqual(
                mock_hc_cls.call_count, 1,
                "HealthChecker must be instantiated only once across multiple run() calls",
            )

    def test_health_checker_instance_is_same_object(self):
        """p._health_checker is set after the first run and unchanged after
        the second, confirming object identity reuse."""
        src = _make_source()
        p = Pipeline(sources=[src], check_health=True)
        p._fetch_all_sync = lambda stop, cb: {src.url: [VMESS]}

        fake_checker_instance = MagicMock()
        fake_checker_instance.check_batch.return_value = []
        fake_checker_instance._layer3_checker = None

        with patch(
            "v2ray_finder.health_checker.HealthChecker",
            return_value=fake_checker_instance,
        ):
            p.run()
            checker_after_first = p._health_checker
            p.run()
            checker_after_second = p._health_checker

        self.assertIs(
            checker_after_first, checker_after_second,
            "_health_checker must be the same object after both runs",
        )


if __name__ == "__main__":
    unittest.main()
