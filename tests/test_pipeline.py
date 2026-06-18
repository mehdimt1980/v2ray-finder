"""Tests for pipeline.Pipeline, StopController, and PipelineResult."""
from __future__ import annotations

import threading
import types
import unittest
from unittest.mock import MagicMock, patch, call

from v2ray_finder.pipeline import Pipeline, PipelineResult, StopController
from v2ray_finder.sources import SourceEntry, SourceType, SourceTrust
from v2ray_finder.scorer import ServerScore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VMESS = "vmess://eyJhZGQiOiIxMjcuMC4wLjEiLCJwb3J0Ijo0NDMsImlkIjoiYWJjMTIzIn0="
VLESS = "vless://uuid@1.2.3.4:443?security=tls"
TROJAN = "trojan://password@5.6.7.8:443?security=tls"

SAMPLE_CONFIGS = [VMESS, VLESS, TROJAN]


def _make_source(url: str = "https://example.com/sub") -> SourceEntry:
    return SourceEntry(
        url=url,
        source_type=SourceType.STATIC_SUBSCRIPTION,
        trust=SourceTrust.HIGH,
        label="test-source",
    )


class _FakeResponse:
    """Minimal requests.Response stand-in."""

    def __init__(self, text: str = "", status_code: int = 200):
        self.text        = text
        self.status_code = status_code


# ---------------------------------------------------------------------------
# StopController
# ---------------------------------------------------------------------------

class TestStopController(unittest.TestCase):

    def test_initial_state_not_set(self):
        ctrl = StopController()
        self.assertFalse(ctrl.is_set())

    def test_stop_sets_event(self):
        ctrl = StopController()
        ctrl.stop()
        self.assertTrue(ctrl.is_set())
        self.assertTrue(ctrl.event.is_set())

    def test_reset_clears_event(self):
        ctrl = StopController()
        ctrl.stop()
        ctrl.reset()
        self.assertFalse(ctrl.is_set())

    def test_event_is_threading_event(self):
        ctrl = StopController()
        self.assertIsInstance(ctrl.event, threading.Event)

    def test_stop_idempotent(self):
        ctrl = StopController()
        ctrl.stop()
        ctrl.stop()  # second call must not raise
        self.assertTrue(ctrl.is_set())

    def test_reset_idempotent(self):
        ctrl = StopController()
        ctrl.reset()  # reset without prior stop must not raise
        self.assertFalse(ctrl.is_set())


# ---------------------------------------------------------------------------
# PipelineResult
# ---------------------------------------------------------------------------

class TestPipelineResult(unittest.TestCase):

    def test_defaults_are_empty(self):
        r = PipelineResult()
        self.assertEqual(r.configs, [])
        self.assertEqual(r.health_dicts, [])
        self.assertEqual(r.scores, [])
        self.assertEqual(r.overlap_map, {})
        self.assertEqual(r.stats, {})

    def test_top_configs_returns_config_strings(self):
        s1 = ServerScore(config=VMESS,  protocol="vmess",  latency_score=0.9)
        s2 = ServerScore(config=VLESS,  protocol="vless",  latency_score=0.5)
        r = PipelineResult(scores=[s1, s2])
        self.assertEqual(r.top_configs, [VMESS, VLESS])

    def test_top_configs_preserves_score_order(self):
        """top_configs must NOT re-sort; order is whatever scores list holds."""
        s_low  = ServerScore(config=TROJAN, protocol="trojan", latency_score=0.1)
        s_high = ServerScore(config=VLESS,  protocol="vless",  latency_score=0.9)
        r = PipelineResult(scores=[s_low, s_high])
        self.assertEqual(r.top_configs, [TROJAN, VLESS])

    def test_top_configs_empty_when_no_scores(self):
        r = PipelineResult()
        self.assertEqual(r.top_configs, [])


# ---------------------------------------------------------------------------
# Pipeline.__init__
# ---------------------------------------------------------------------------

class TestPipelineInit(unittest.TestCase):

    def test_defaults(self):
        p = Pipeline()
        self.assertTrue(p.check_health)
        self.assertFalse(p.check_http_probe)
        self.assertFalse(p.check_google_204)
        self.assertEqual(p.timeout, 5.0)
        self.assertEqual(p.min_quality_score, 0.0)
        self.assertEqual(p.health_batch_size, 100)
        self.assertEqual(p.fetch_timeout, 15)
        self.assertEqual(p.fetch_concurrency, 10)
        self.assertIsNone(p.limit)
        self.assertIsNone(p.binary_path)

    def test_custom_params(self):
        p = Pipeline(
            check_health=False,
            check_http_probe=True,
            check_google_204=True,
            timeout=3.0,
            min_quality_score=0.5,
            health_batch_size=50,
            fetch_timeout=30,
            fetch_concurrency=5,
            limit=100,
            binary_path="/usr/bin/xray",
        )
        self.assertFalse(p.check_health)
        self.assertTrue(p.check_http_probe)
        self.assertTrue(p.check_google_204)
        self.assertEqual(p.timeout, 3.0)
        self.assertEqual(p.min_quality_score, 0.5)
        self.assertEqual(p.health_batch_size, 50)
        self.assertEqual(p.fetch_timeout, 30)
        self.assertEqual(p.fetch_concurrency, 5)
        self.assertEqual(p.limit, 100)
        self.assertEqual(p.binary_path, "/usr/bin/xray")

    def test_sources_override(self):
        src = _make_source()
        p = Pipeline(sources=[src])
        self.assertEqual(p.sources, [src])

    def test_default_sources_not_empty(self):
        p = Pipeline()
        self.assertGreater(len(p.sources), 0)


# ---------------------------------------------------------------------------
# Pipeline.run — high-level behaviour
# ---------------------------------------------------------------------------

class TestPipelineRun(unittest.TestCase):

    def _pipeline_with_fake_fetch(self, configs=None, check_health=False):
        """Return a Pipeline whose _fetch_all_sync is stubbed."""
        src = _make_source()
        p = Pipeline(sources=[src], check_health=check_health)
        raw_text = "\n".join(configs or SAMPLE_CONFIGS)
        fake_resp = _FakeResponse(text=raw_text, status_code=200)
        p._fetch_all_sync = lambda stop, cb: {src.url: _parse_inline(raw_text)}
        return p

    def test_run_no_health_returns_configs(self):
        p = self._pipeline_with_fake_fetch()
        result = p.run()
        self.assertIsInstance(result, PipelineResult)
        self.assertGreater(len(result.configs), 0)

    def test_run_stop_event_preset_returns_early(self):
        src = _make_source()
        p = Pipeline(sources=[src], check_health=False)
        stop = StopController()
        stop.stop()  # pre-set before run

        # Stub _fetch_all_sync to prove it still runs (stop checked after fetch)
        p._fetch_all_sync = lambda ev, cb: {src.url: SAMPLE_CONFIGS[:]}

        result = p.run(stop_event=stop.event)
        # Pipeline returns after dedup because stop is checked between stages
        self.assertIsInstance(result, PipelineResult)

    def test_run_progress_callback_receives_fetch_events(self):
        src = _make_source()
        p = Pipeline(sources=[src], check_health=False)
        p._fetch_all_sync = lambda ev, cb: {src.url: SAMPLE_CONFIGS[:]}

        events = []
        def cb(stage, current, total, msg):
            events.append((stage, current, total))

        p.run(progress_callback=cb)
        # score stage must have fired at minimum
        stages = {e[0] for e in events}
        self.assertIn("score", stages)

    def test_run_stats_keys_present(self):
        p = self._pipeline_with_fake_fetch()
        result = p.run()
        for key in ("fetched", "deduped", "healthy", "scored"):
            self.assertIn(key, result.stats)

    def test_run_limit_respected(self):
        src = _make_source()
        many = [f"vless://uuid{i}@1.2.3.{i}:443" for i in range(20)]
        p = Pipeline(sources=[src], check_health=False, limit=5)
        p._fetch_all_sync = lambda ev, cb: {src.url: many}
        result = p.run()
        self.assertLessEqual(len(result.configs), 5)


# ---------------------------------------------------------------------------
# Pipeline._fetch_all_sync
# ---------------------------------------------------------------------------

class TestPipelineFetchSync(unittest.TestCase):

    def _make_pipeline(self, sources=None):
        srcs = sources or [_make_source()]
        return Pipeline(sources=srcs, check_health=False)

    def test_happy_path_returns_configs(self):
        src = _make_source("https://a.example.com/sub")
        p = self._make_pipeline([src])
        stop = threading.Event()

        fake_resp = _FakeResponse(text="\n".join(SAMPLE_CONFIGS))
        with patch("v2ray_finder.pipeline.requests") as mock_req:
            mock_req.get.return_value = fake_resp  # type: ignore
            # We need the real import inside the method
            import importlib, sys
            # patch at the module level used inside _fetch_all_sync
            with patch("requests.get", return_value=fake_resp):
                result = p._fetch_all_sync(stop, None)

        # At least one source url key present
        self.assertIn(src.url, result)
        self.assertGreater(len(result[src.url]), 0)

    def test_http_error_skips_source(self):
        src = _make_source()
        p = self._make_pipeline([src])
        stop = threading.Event()

        with patch("requests.get", return_value=_FakeResponse(status_code=404)):
            result = p._fetch_all_sync(stop, None)

        self.assertEqual(result, {})

    def test_network_exception_skips_source(self):
        import requests as _req
        src = _make_source()
        p = self._make_pipeline([src])
        stop = threading.Event()

        with patch("requests.get", side_effect=_req.exceptions.ConnectionError("fail")):
            result = p._fetch_all_sync(stop, None)

        self.assertEqual(result, {})

    def test_stop_event_preset_skips_all_sources(self):
        src = _make_source()
        p = self._make_pipeline([src])
        stop = threading.Event()
        stop.set()

        called = []
        with patch("requests.get", side_effect=lambda *a, **kw: called.append(1) or _FakeResponse()):
            result = p._fetch_all_sync(stop, None)

        self.assertEqual(called, [])
        self.assertEqual(result, {})

    def test_multiple_sources_all_succeed(self):
        srcs = [_make_source(f"https://src{i}.example.com/sub") for i in range(3)]
        p = self._make_pipeline(srcs)
        stop = threading.Event()
        text = "\n".join(SAMPLE_CONFIGS)

        with patch("requests.get", return_value=_FakeResponse(text=text)):
            result = p._fetch_all_sync(stop, None)

        self.assertEqual(len(result), 3)


# ---------------------------------------------------------------------------
# Async fallback when httpx absent
# ---------------------------------------------------------------------------

class TestPipelineFetchAsyncFallback(unittest.TestCase):

    def test_falls_back_to_sync_when_no_httpx(self):
        """When httpx import raises ImportError, _fetch_all_sync is used."""
        src = _make_source()
        p = Pipeline(sources=[src], check_health=False)
        stop = threading.Event()

        sync_result = {src.url: SAMPLE_CONFIGS[:]}
        p._fetch_all_sync = MagicMock(return_value=sync_result)

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "httpx":
                raise ImportError("no httpx")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = p._fetch_all(stop, None)

        p._fetch_all_sync.assert_called_once()
        self.assertEqual(result, sync_result)


# ---------------------------------------------------------------------------
# Pipeline._run_health
# ---------------------------------------------------------------------------

class TestPipelineRunHealth(unittest.TestCase):

    def _mock_health_checker(self, configs):
        """Return a mock HealthChecker that marks every config as tcp_ok."""
        from v2ray_finder.health_checker import ServerHealth, HealthStatus

        def check_batch(batch):
            results = []
            for c in batch:
                h = ServerHealth(
                    config=c,
                    protocol="vless",
                    status=HealthStatus.HEALTHY,
                    tcp_ok=True,
                    http_probe_ok=False,
                    google_204_ok=False,
                    latency_ms=50.0,
                )
                results.append(h)
            return results

        mock = MagicMock()
        mock.check_batch.side_effect = check_batch
        return mock

    def test_returns_annotated_dicts(self):
        src = _make_source()
        p = Pipeline(sources=[src], check_health=True)
        overlap_map = {src.url: 0.2}
        stop = threading.Event()

        mock_checker = self._mock_health_checker(SAMPLE_CONFIGS)

        with patch("v2ray_finder.pipeline.HealthChecker", return_value=mock_checker), \
             patch("v2ray_finder.pipeline.filter_healthy_servers",
                   side_effect=lambda results, **kw: results):
            dicts = p._run_health(SAMPLE_CONFIGS[:], overlap_map, stop, None)

        self.assertEqual(len(dicts), len(SAMPLE_CONFIGS))
        required_keys = {
            "config", "protocol", "tcp_ok", "http_ok",
            "google_204_ok", "latency_ms", "health_checked",
            "source_url", "source_trust", "overlap_ratio",
        }
        for d in dicts:
            self.assertTrue(required_keys.issubset(d.keys()),
                            f"Missing keys: {required_keys - d.keys()}")

    def test_health_checked_flag_is_true(self):
        src = _make_source()
        p = Pipeline(sources=[src])
        overlap_map = {src.url: 0.0}
        stop = threading.Event()

        mock_checker = self._mock_health_checker([VLESS])
        with patch("v2ray_finder.pipeline.HealthChecker", return_value=mock_checker), \
             patch("v2ray_finder.pipeline.filter_healthy_servers",
                   side_effect=lambda results, **kw: results):
            dicts = p._run_health([VLESS], overlap_map, stop, None)

        self.assertTrue(dicts[0]["health_checked"])

    def test_stop_event_cancels_remaining_batches(self):
        src = _make_source()
        # health_batch_size=1 so each config is its own batch
        p = Pipeline(sources=[src], health_batch_size=1)
        overlap_map = {src.url: 0.0}
        stop = threading.Event()

        call_count = [0]

        def check_batch(batch):
            call_count[0] += 1
            stop.set()  # signal stop after first batch
            from v2ray_finder.health_checker import ServerHealth, HealthStatus
            return [ServerHealth(
                config=batch[0], protocol="vless",
                status=HealthStatus.HEALTHY, tcp_ok=True,
                http_probe_ok=False, google_204_ok=False, latency_ms=10.0,
            )]

        mock_checker = MagicMock()
        mock_checker.check_batch.side_effect = check_batch

        with patch("v2ray_finder.pipeline.HealthChecker", return_value=mock_checker), \
             patch("v2ray_finder.pipeline.filter_healthy_servers",
                   side_effect=lambda results, **kw: results):
            p._run_health(SAMPLE_CONFIGS[:], overlap_map, stop, None)

        # Only the first batch should have run
        self.assertEqual(call_count[0], 1)

    def test_empty_configs_returns_empty(self):
        src = _make_source()
        p = Pipeline(sources=[src])
        mock_checker = MagicMock()
        mock_checker.check_batch.return_value = []
        with patch("v2ray_finder.pipeline.HealthChecker", return_value=mock_checker), \
             patch("v2ray_finder.pipeline.filter_healthy_servers",
                   side_effect=lambda results, **kw: results):
            dicts = p._run_health([], {}, threading.Event(), None)
        self.assertEqual(dicts, [])


# ---------------------------------------------------------------------------
# Pipeline._emit
# ---------------------------------------------------------------------------

class TestPipelineEmit(unittest.TestCase):

    def test_emit_calls_callback(self):
        calls = []
        Pipeline._emit(lambda s, c, t, m: calls.append((s, c, t, m)),
                       "fetch", 1, 10, "hello")
        self.assertEqual(calls, [("fetch", 1, 10, "hello")])

    def test_emit_none_callback_safe(self):
        # Must not raise
        Pipeline._emit(None, "health", 0, 5, "msg")

    def test_emit_callback_exception_suppressed(self):
        def bad_cb(*a):
            raise RuntimeError("oops")
        # Must not propagate
        Pipeline._emit(bad_cb, "score", 0, 1, "msg")

    def test_emit_stage_values(self):
        seen = []
        cb = lambda s, c, t, m: seen.append(s)
        for stage in ("fetch", "health", "score"):
            Pipeline._emit(cb, stage, 0, 1, "x")
        self.assertEqual(seen, ["fetch", "health", "score"])


# ---------------------------------------------------------------------------
# Integration: full Pipeline.run() round-trip
# ---------------------------------------------------------------------------

class TestPipelineIntegration(unittest.TestCase):

    def _make_health_result(self, config: str) -> dict:
        return {
            "config":         config,
            "protocol":       "vless",
            "tcp_ok":         True,
            "http_ok":        False,
            "google_204_ok":  False,
            "latency_ms":     100.0,
            "health_checked": True,
            "source_url":     "https://example.com/sub",
            "source_trust":   3,
            "overlap_ratio":  0.1,
        }

    def test_full_run_produces_sorted_scores(self):
        """End-to-end: fetch → dedup → health → score → sorted scores."""
        src = _make_source()
        p = Pipeline(sources=[src], check_health=True, health_batch_size=100)

        # Stub the sync fetch
        p._fetch_all_sync = lambda ev, cb: {src.url: SAMPLE_CONFIGS[:]}

        health_dicts = [self._make_health_result(c) for c in SAMPLE_CONFIGS]

        from v2ray_finder.health_checker import ServerHealth, HealthStatus

        def fake_check_batch(batch):
            return [
                ServerHealth(
                    config=c, protocol="vless",
                    status=HealthStatus.HEALTHY,
                    tcp_ok=True, http_probe_ok=False,
                    google_204_ok=False, latency_ms=100.0,
                )
                for c in batch
            ]

        mock_checker = MagicMock()
        mock_checker.check_batch.side_effect = fake_check_batch

        with patch("v2ray_finder.pipeline.HealthChecker", return_value=mock_checker), \
             patch("v2ray_finder.pipeline.filter_healthy_servers",
                   side_effect=lambda results, **kw: results):
            result = p.run()

        self.assertIsInstance(result, PipelineResult)
        self.assertGreater(len(result.scores), 0)

        # Scores must be sorted descending
        totals = [s.total for s in result.scores]
        self.assertEqual(totals, sorted(totals, reverse=True))

    def test_full_run_no_health_skip_score(self):
        """check_health=False → health_dicts are unchecked, scores still produced."""
        src = _make_source()
        p = Pipeline(sources=[src], check_health=False)
        p._fetch_all_sync = lambda ev, cb: {src.url: SAMPLE_CONFIGS[:]}

        result = p.run()
        self.assertIsInstance(result, PipelineResult)
        # health_dicts should all have health_checked=False
        for d in result.health_dicts:
            self.assertFalse(d["health_checked"])
        # scores still produced from unchecked dicts
        self.assertEqual(len(result.scores), len(result.health_dicts))

    def test_run_with_stop_controller(self):
        """StopController.stop() during run must not crash; returns partial result."""
        src = _make_source()
        p = Pipeline(sources=[src], check_health=False)
        ctrl = StopController()

        def fake_fetch(ev, cb):
            ctrl.stop()  # stop mid-fetch
            return {src.url: SAMPLE_CONFIGS[:]}

        p._fetch_all_sync = fake_fetch
        result = p.run(stop_event=ctrl.event)
        self.assertIsInstance(result, PipelineResult)


# ---------------------------------------------------------------------------
# __init__ exports
# ---------------------------------------------------------------------------

class TestInitExports(unittest.TestCase):

    def test_pipeline_importable_from_package(self):
        import v2ray_finder
        self.assertTrue(hasattr(v2ray_finder, "Pipeline"))

    def test_stop_controller_importable_from_package(self):
        import v2ray_finder
        self.assertTrue(hasattr(v2ray_finder, "StopController"))

    def test_pipeline_result_importable_from_package(self):
        import v2ray_finder
        self.assertTrue(hasattr(v2ray_finder, "PipelineResult"))

    def test_version_bumped(self):
        import v2ray_finder
        major, minor, *_ = v2ray_finder.__version__.split(".")
        self.assertEqual(major, "0")
        self.assertGreaterEqual(int(minor), 6)


# ---------------------------------------------------------------------------

def _parse_inline(text: str):
    """Minimal inline config parser for test stubs."""
    import re
    _RE = re.compile(
        r"(?:vmess|vless|trojan|ss|ssr)://[A-Za-z0-9+/=_\-@:.?&#%]+",
        re.IGNORECASE,
    )
    return list(dict.fromkeys(_RE.findall(text)))


if __name__ == "__main__":
    unittest.main()
