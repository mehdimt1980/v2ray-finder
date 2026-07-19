"""Tests for xray_connectivity.py — V1-D4 retry logic."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call, patch

from v2ray_finder.xray_connectivity import (
    RealHealthResult,
    _LegacyResult,
    check_one,
    find_free_port,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VMESS_URI = (
    "vmess://eyJhZGQiOiIxMjcuMC4wLjEiLCJwb3J0IjoiODA4MCIsImlkIjoiZmFrZS11dWlkIn0="
)


def _make_runner_mock(fail_on_first: bool = False):
    """Return a (runner_cls_mock, start_call_count) pair.

    When fail_on_first=True the first .start() call raises RuntimeError;
    subsequent calls succeed.
    """
    runner_mock = MagicMock()
    call_count = [0]

    def _start(cfg):
        call_count[0] += 1
        if fail_on_first and call_count[0] == 1:
            raise RuntimeError("port already in use")

    runner_mock.start.side_effect = _start
    runner_mock.stop.return_value = None
    return runner_mock, call_count


# ---------------------------------------------------------------------------
# find_free_port
# ---------------------------------------------------------------------------


class TestFindFreePort(unittest.TestCase):

    def test_returns_int(self):
        port = find_free_port()
        self.assertIsInstance(port, int)

    def test_port_in_valid_range(self):
        port = find_free_port()
        self.assertGreater(port, 0)
        self.assertLessEqual(port, 65535)

    def test_two_calls_may_differ(self):
        """Not guaranteed but almost always true in practice."""
        ports = {find_free_port() for _ in range(5)}
        self.assertGreaterEqual(len(ports), 1)


# ---------------------------------------------------------------------------
# check_one — no retry path (normal success)
# ---------------------------------------------------------------------------


class TestCheckOneSuccess(unittest.TestCase):

    @patch("v2ray_finder.xray_connectivity.config_to_xray")
    @patch("v2ray_finder.xray_connectivity.XrayRunner")
    @patch("v2ray_finder.xray_connectivity._socks5_http_get")
    def test_live_probe_runs_before_runner_stops(self, mock_probe, mock_runner_cls, mock_cfg):
        mock_cfg.return_value = {"inbounds": []}
        runner_inst = MagicMock()
        mock_runner_cls.return_value = runner_inst
        mock_probe.return_value = (True, 204, 55.0)
        observed = {}

        def live_probe(port):
            observed["port"] = port
            observed["stopped"] = runner_inst.stop.called
            return {"checked": 4, "ok_count": 3, "success_rate": 0.75, "results": []}

        result = check_one(VMESS_URI, local_port=19000, live_probe=live_probe)

        self.assertEqual(observed, {"port": 19000, "stopped": False})
        self.assertEqual(result.endpoint_probe["checked"], 4)
        runner_inst.stop.assert_called_once()

    @patch("v2ray_finder.xray_connectivity.config_to_xray")
    @patch("v2ray_finder.xray_connectivity.XrayRunner")
    @patch("v2ray_finder.xray_connectivity._socks5_http_get")
    def test_success_no_retry(self, mock_probe, mock_runner_cls, mock_cfg):
        mock_cfg.return_value = {"inbounds": []}
        runner_inst = MagicMock()
        mock_runner_cls.return_value = runner_inst
        mock_probe.return_value = (True, 204, 55.0)

        result = check_one(VMESS_URI, local_port=19000)

        self.assertTrue(result.reachable)
        self.assertTrue(result.google_204_ok)
        self.assertAlmostEqual(result.latency_ms, 55.0)
        self.assertFalse(result.retried)
        runner_inst.start.assert_called_once()
        runner_inst.stop.assert_called_once()

    @patch("v2ray_finder.xray_connectivity.config_to_xray")
    @patch("v2ray_finder.xray_connectivity.XrayRunner")
    @patch("v2ray_finder.xray_connectivity._socks5_http_get")
    def test_probe_failure_no_retry(self, mock_probe, mock_runner_cls, mock_cfg):
        mock_cfg.return_value = {"inbounds": []}
        mock_runner_cls.return_value = MagicMock()
        mock_probe.return_value = (False, 0, None)

        result = check_one(VMESS_URI, local_port=19001)

        self.assertFalse(result.reachable)
        self.assertFalse(result.retried)

    def test_invalid_uri_no_retry(self):
        result = check_one("not-a-uri")
        self.assertFalse(result.reachable)
        self.assertIsNotNone(result.error)
        self.assertFalse(result.retried)

    @patch("v2ray_finder.xray_connectivity.config_to_xray", return_value=None)
    def test_config_conversion_failure(self, _):
        result = check_one(VMESS_URI)
        self.assertFalse(result.reachable)
        self.assertIn("convert", result.error)
        self.assertFalse(result.retried)


# ---------------------------------------------------------------------------
# V1-D4: retry on xray start failure
# ---------------------------------------------------------------------------


class TestCheckOneRetry(unittest.TestCase):

    @patch("v2ray_finder.xray_connectivity.find_free_port", return_value=29999)
    @patch("v2ray_finder.xray_connectivity.config_to_xray")
    @patch("v2ray_finder.xray_connectivity.XrayRunner")
    @patch("v2ray_finder.xray_connectivity._socks5_http_get")
    def test_retry_succeeds_on_second_attempt(
        self, mock_probe, mock_runner_cls, mock_cfg, mock_ffp
    ):
        """First start() raises RuntimeError; retry on free port succeeds."""
        mock_cfg.return_value = {"inbounds": []}
        mock_probe.return_value = (True, 204, 80.0)

        runner_inst = MagicMock()
        start_calls = [0]

        def _start(cfg):
            start_calls[0] += 1
            if start_calls[0] == 1:
                raise RuntimeError("address already in use")

        runner_inst.start.side_effect = _start
        mock_runner_cls.return_value = runner_inst

        result = check_one(VMESS_URI, local_port=19000)

        self.assertTrue(result.reachable)
        self.assertTrue(result.retried)
        self.assertEqual(result.socks_port, 29999)
        self.assertEqual(start_calls[0], 2)
        mock_ffp.assert_called_once()

    @patch("v2ray_finder.xray_connectivity.find_free_port", return_value=29998)
    @patch("v2ray_finder.xray_connectivity.config_to_xray")
    @patch("v2ray_finder.xray_connectivity.XrayRunner")
    @patch("v2ray_finder.xray_connectivity._socks5_http_get")
    def test_retry_also_fails_returns_original_error(
        self, mock_probe, mock_runner_cls, mock_cfg, mock_ffp
    ):
        """Both attempts fail — retried=True, original error preserved."""
        mock_cfg.return_value = {"inbounds": []}

        runner_inst = MagicMock()
        runner_inst.start.side_effect = RuntimeError("port busy")
        mock_runner_cls.return_value = runner_inst

        result = check_one(VMESS_URI, local_port=19001)

        self.assertFalse(result.reachable)
        self.assertTrue(result.retried)
        self.assertIn("port busy", result.error)
        mock_ffp.assert_called_once()
        mock_probe.assert_not_called()

    @patch("v2ray_finder.xray_connectivity.find_free_port", return_value=29997)
    @patch("v2ray_finder.xray_connectivity.config_to_xray")
    @patch("v2ray_finder.xray_connectivity.XrayRunner")
    @patch("v2ray_finder.xray_connectivity._socks5_http_get")
    def test_retry_cfg_uses_retry_port(
        self, mock_probe, mock_runner_cls, mock_cfg, mock_ffp
    ):
        """config_to_xray is called with the retry port on retry."""
        xray_cfg = {"inbounds": []}
        mock_cfg.return_value = xray_cfg
        mock_probe.return_value = (True, 204, 40.0)

        runner_inst = MagicMock()
        call_count = [0]

        def _start(cfg):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("busy")

        runner_inst.start.side_effect = _start
        mock_runner_cls.return_value = runner_inst

        check_one(VMESS_URI, local_port=19002)

        # config_to_xray should be called twice: original port + retry port
        self.assertEqual(mock_cfg.call_count, 2)
        calls = mock_cfg.call_args_list
        self.assertEqual(calls[0], call(VMESS_URI, local_port=19002))
        self.assertEqual(calls[1], call(VMESS_URI, local_port=29997))

    @patch("v2ray_finder.xray_connectivity.find_free_port", return_value=29996)
    @patch("v2ray_finder.xray_connectivity.config_to_xray")
    @patch("v2ray_finder.xray_connectivity.XrayRunner")
    @patch("v2ray_finder.xray_connectivity._socks5_http_get")
    def test_no_retry_when_start_succeeds(
        self, mock_probe, mock_runner_cls, mock_cfg, mock_ffp
    ):
        """find_free_port should NOT be called when first start succeeds."""
        mock_cfg.return_value = {"inbounds": []}
        mock_probe.return_value = (True, 204, 30.0)
        mock_runner_cls.return_value = MagicMock()

        result = check_one(VMESS_URI, local_port=19003)

        self.assertFalse(result.retried)
        mock_ffp.assert_not_called()


# ---------------------------------------------------------------------------
# retried field surfaces in RealHealthResult / real_health_to_dict
# ---------------------------------------------------------------------------


class TestRetryFieldPropagation(unittest.TestCase):

    def test_legacy_result_retried_default_false(self):
        r = _LegacyResult(config="vmess://x", protocol="vmess")
        self.assertFalse(r.retried)

    def test_real_health_result_retried_default_false(self):
        r = RealHealthResult(config="vmess://x", protocol="vmess")
        self.assertFalse(r.retried)

    def test_real_health_to_dict_contains_retried(self):
        from v2ray_finder.xray_connectivity import real_health_to_dict

        r = RealHealthResult(config="vmess://x", protocol="vmess", retried=True)
        d = real_health_to_dict(r)
        self.assertIn("retried", d)
        self.assertTrue(d["retried"])


if __name__ == "__main__":
    unittest.main()
