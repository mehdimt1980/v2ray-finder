"""Tests for scorer.py — to_dict/to_json (V3-A1) and deterministic sort (V3-Q3)."""
from __future__ import annotations

import json
import unittest

from v2ray_finder.scorer import (
    ServerScore,
    _sort_key,
    score_server,
    score_servers,
    sort_by_score,
)

VMESS  = "vmess://eyJhZGQiOiIxMjcuMC4wLjEifQ=="
VLESS  = "vless://uuid@1.2.3.4:443?security=tls"
TROJAN = "trojan://pass@5.6.7.8:443"


def _score(**kw) -> ServerScore:
    defaults = dict(config=VMESS, protocol="vmess")
    defaults.update(kw)
    return score_server(**defaults)


# ---------------------------------------------------------------------------
# V3-A1: ServerScore.to_dict / to_json
# ---------------------------------------------------------------------------

class TestServerScoreToDict(unittest.TestCase):

    def test_to_dict_contains_required_keys(self):
        s = _score(latency_ms=100)
        d = s.to_dict()
        for key in ("config", "protocol", "total", "grade", "latency_ms",
                    "latency_score", "reachability_score", "protocol_score",
                    "source_trust_score", "freshness_score",
                    "uniqueness_score", "google_204_score", "health_details"):
            self.assertIn(key, d)

    def test_to_dict_values_match_properties(self):
        s = _score(latency_ms=50, tcp_ok=True)
        d = s.to_dict()
        self.assertEqual(d["total"],   s.total)
        self.assertEqual(d["grade"],   s.grade)
        self.assertEqual(d["config"],  s.config)
        self.assertAlmostEqual(d["latency_ms"], 50)

    def test_to_dict_none_latency(self):
        s = _score()
        d = s.to_dict()
        self.assertIsNone(d["latency_ms"])

    def test_to_dict_health_details_keys(self):
        s = _score(tcp_ok=True, http_ok=False, google_204_ok=True)
        d = s.to_dict()
        self.assertTrue(d["health_details"]["tcp_ok"])
        self.assertFalse(d["health_details"]["http_ok"])
        self.assertTrue(d["health_details"]["google_204_ok"])

    def test_to_json_is_valid_json(self):
        s = _score(latency_ms=80)
        j = s.to_json()
        parsed = json.loads(j)   # must not raise
        self.assertIsInstance(parsed, dict)

    def test_to_json_roundtrip_total(self):
        s = _score(latency_ms=80, tcp_ok=True)
        parsed = json.loads(s.to_json())
        self.assertAlmostEqual(parsed["total"], s.total, places=4)

    def test_to_json_indent_respected(self):
        s = _score()
        j2 = s.to_json(indent=2)
        j4 = s.to_json(indent=4)
        self.assertIn("\n", j2)
        self.assertIn("    ", j4)

    def test_to_json_non_ascii_config(self):
        s = ServerScore(config="vmess://فارسی", protocol="vmess")
        j = s.to_json()
        self.assertIn("فارسی", j)

    def test_to_dict_is_json_serialisable(self):
        s = _score(latency_ms=200, tcp_ok=True, google_204_ok=True)
        json.dumps(s.to_dict())  # must not raise TypeError


# ---------------------------------------------------------------------------
# V3-A1: PipelineResult.to_dict / to_json
# ---------------------------------------------------------------------------

class TestPipelineResultSerialization(unittest.TestCase):

    def _result(self, n=3):
        from v2ray_finder.pipeline import PipelineResult
        configs = [VMESS, VLESS, TROJAN][:n]
        scores  = [score_server(c, c.split("://")[0]) for c in configs]
        return PipelineResult(
            configs=configs,
            scores=scores,
            stats={"fetched": n, "deduped": n, "healthy": 0,
                   "scored": n, "cache_hits": 0, "cache_misses": 0,
                   "errors": {}},
        )

    def test_to_dict_has_required_keys(self):
        r = self._result()
        d = r.to_dict()
        for key in ("stats", "servers", "configs"):
            self.assertIn(key, d)

    def test_to_dict_servers_count_matches_scores(self):
        r = self._result(3)
        d = r.to_dict()
        self.assertEqual(len(d["servers"]), 3)

    def test_to_dict_each_server_has_config_key(self):
        r = self._result(2)
        for srv in r.to_dict()["servers"]:
            self.assertIn("config", srv)

    def test_to_dict_configs_list_derived_from_scores(self):
        r = self._result(2)
        d = r.to_dict()
        self.assertEqual(d["configs"], [s["config"] for s in d["servers"]])

    def test_to_json_valid_json(self):
        r = self._result()
        parsed = json.loads(r.to_json())
        self.assertIsInstance(parsed, dict)

    def test_to_json_roundtrip_stats(self):
        r = self._result(2)
        parsed = json.loads(r.to_json())
        self.assertEqual(parsed["stats"]["fetched"], 2)

    def test_to_json_empty_result(self):
        from v2ray_finder.pipeline import PipelineResult
        r = PipelineResult()
        parsed = json.loads(r.to_json())
        self.assertEqual(parsed["servers"], [])

    def test_failed_sources_property_empty(self):
        r = self._result()
        self.assertEqual(r.failed_sources, {})

    def test_failed_sources_property_from_stats(self):
        from v2ray_finder.pipeline import PipelineResult
        r = PipelineResult(stats={"errors": {"http://bad.example": "timeout"}})
        self.assertEqual(r.failed_sources["http://bad.example"], "timeout")


# ---------------------------------------------------------------------------
# V3-Q3: Deterministic sort
# ---------------------------------------------------------------------------

class TestDeterministicSort(unittest.TestCase):

    def _s(self, config, total_override=None, latency=None):
        """Build a ServerScore with predictable total via freshness_score."""
        s = ServerScore(
            config=config,
            protocol="vmess",
            latency_ms=latency,
            freshness_score=total_override if total_override is not None else 0.0,
        )
        return s

    # -- _sort_key structure --
    def test_sort_key_descending_sign(self):
        s = self._s(VMESS)
        key_d = _sort_key(s, descending=True)
        key_a = _sort_key(s, descending=False)
        # descending flips sign of first element
        self.assertAlmostEqual(key_d[0], -key_a[0], places=6)

    def test_sort_key_none_latency_last(self):
        s_none = self._s(VMESS,  latency=None)
        s_fast = self._s(VLESS,  latency=10)
        # For ascending secondary key None should sort after any real value
        self.assertGreater(_sort_key(s_none)[1], _sort_key(s_fast)[1])

    def test_sort_key_third_element_is_config(self):
        s = self._s(VMESS)
        self.assertEqual(_sort_key(s)[2], VMESS)

    # -- Three servers with identical total --
    def test_tie_broken_by_latency(self):
        """Lower latency wins when totals are equal."""
        s1 = ServerScore(config="vmess://aaa", protocol="vmess", latency_ms=100)
        s2 = ServerScore(config="vmess://bbb", protocol="vmess", latency_ms=50)
        result = sort_by_score([s1, s2], descending=True)
        # s1.total == s2.total == 0.0; s2 has lower latency -> comes first
        self.assertEqual(result[0].config, "vmess://bbb")

    def test_tie_broken_by_config_string(self):
        """When total AND latency are equal, config string ascending wins."""
        s1 = ServerScore(config="vmess://zzz", protocol="vmess", latency_ms=50)
        s2 = ServerScore(config="vmess://aaa", protocol="vmess", latency_ms=50)
        result = sort_by_score([s1, s2], descending=True)
        self.assertEqual(result[0].config, "vmess://aaa")

    def test_sort_is_deterministic_across_multiple_calls(self):
        servers = [
            ServerScore(config=f"vmess://x{i:03d}", protocol="vmess", latency_ms=i * 10)
            for i in range(10)
        ]
        r1 = sort_by_score(servers[:])
        r2 = sort_by_score(servers[::-1])
        self.assertEqual([s.config for s in r1], [s.config for s in r2])

    # -- score_servers uses composite key --
    def test_score_servers_deterministic(self):
        health = [
            {"config": VMESS,  "protocol": "vmess",  "latency_ms": 100},
            {"config": VLESS,  "protocol": "vless",  "latency_ms": 50},
            {"config": TROJAN, "protocol": "trojan", "latency_ms": 200},
        ]
        r1 = score_servers(health)
        r2 = score_servers(health[::-1])
        self.assertEqual([s.config for s in r1], [s.config for s in r2])

    def test_ascending_sort(self):
        s1 = ServerScore(config="vmess://low",  protocol="vmess", latency_score=0.1)
        s2 = ServerScore(config="vmess://high", protocol="vmess", latency_score=0.9)
        result = sort_by_score([s1, s2], descending=False)
        self.assertLessEqual(result[0].total, result[1].total)


# ---------------------------------------------------------------------------
# V3-D3: py.typed present
# ---------------------------------------------------------------------------

class TestPyTyped(unittest.TestCase):

    def test_py_typed_marker_exists(self):
        import importlib.resources as ir
        import v2ray_finder
        try:
            # Python 3.9+
            ref = ir.files(v2ray_finder).joinpath("py.typed")
            self.assertTrue(ref.is_file())
        except AttributeError:
            # Python 3.8 fallback
            import os, v2ray_finder as pkg
            marker = os.path.join(os.path.dirname(pkg.__file__), "py.typed")
            self.assertTrue(os.path.exists(marker))


if __name__ == "__main__":
    unittest.main()
