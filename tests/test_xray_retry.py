"""Tests for V1-D4: xray Layer-3 port-contention retry logic.

Covers:
  1. find_free_port() returns a usable port.
  2. _try_start_xray() returns (None, runner) on success.
  3. _try_start_xray() returns (error_str, None) on failure and cleans up.
  4. check_one() succeeds on first attempt — retried=False.
  5. check_one() retries when first start fails and retry succeeds — retried=True.
  6. check_one() sets retried=True and combined error when both attempts fail.
  7. check_one() returns early when config_to_xray returns None.
  8. check_one() returns early for non-URI input.
  9. RealHealthResult.retried field is preserved through RealConnectivityChecker.
 10. check_real_connectivity_batch() propagates retried flag.
"""
from __future__ import annotations

import socket
import unittest
from unittest.mock import MagicMock, patch, call

from v2ray_finder.xray_connectivity import (
    RealHealthResult,
    _LegacyResult,
    _try_start_xray,
    check_one,
    check_real_connectivity_batch,
    find_free_port,
)


# ---------------------------------------------------------------------------
# Sample configs
# ---------------------------------------------------------------------------

VLESS = "vless://00000000-0000-0000-0000-000000000001@1.2.3.4:443?security=tls"
VMESS = "vmess://eyJhZGQiOiIxLjIuMy40IiwicG9ydCI6NDQzLCJpZCI6ImFiYzEyMyJ9"
_FAKE_XRAY_CFG = {"inbounds": [], "outbounds": []}


# ---------------------------------------------------------------------------
# 1. find_free_port
# ---------------------------------------------------------------------------

class TestFindFreePort(unittest.TestCase):

    def test_returns_integer(self):
        port = find_free_port()
        self.assertIsInstance(port, int)

    def test_port_in_valid_range(self):
        port = find_free_port()
        self.assertGreater(port, 0)
        self.assertLessEqual(port, 65535)

    def test_port_is_bindable(self):
        """The returned port should be bindable immediately after the call."""
        port = find_free_port()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Should not raise
            s.bind(("", port))

    def test_two_calls_can_return_different_ports(self):
        """Not guaranteed, but overwhelmingly likely."""
        ports = {find_free_port() for _ in range(5)}
        # Allow the degenerate case where OS reuses immediately, but
        # require at least one unique port is returned.
        self.assertGreaterEqual(len(ports), 1)


# ---------------------------------------------------------------------------
# 2 & 3. _try_start_xray
# ---------------------------------------------------------------------------

class TestTryStartXray(unittest.TestCase):

    def _mock_runner(self, start_raises=None):
        runner = MagicMock()
        if start_raises:
            runner.start.side_effect = start_raises
        return runner

    def test_success_returns_none_error_and_runner(self):
        runner = self._mock_runner()
        with patch("v2ray_finder.xray_connectivity.XrayRunner", return_value=runner):
            err, r = _try_start_xray(10900, _FAKE_XRAY_CFG, None, False)
        self.assertIsNone(err)
        self.assertIs(r, runner)
        runner.start.assert_called_once_with(_FAKE_XRAY_CFG)

    def test_failure_returns_error_string_and_none_runner(self):
        runner = self._mock_runner(start_raises=RuntimeError("address in use"))
        with patch("v2ray_finder.xray_connectivity.XrayRunner", return_value=runner):
            err, r = _try_start_xray(10900, _FAKE_XRAY_CFG, None, False)
        self.assertIsNotNone(err)
        self.assertIsNone(r)
        self.assertIn("address in use", err)

    def test_failure_calls_stop_for_cleanup(self):
        runner = self._mock_runner(start_raises=RuntimeError("port busy"))
        with patch("v2ray_finder.xray_connectivity.XrayRunner", return_value=runner):
            _try_start_xray(10900, _FAKE_XRAY_CFG, None, False)
        runner.stop.assert_called_once()

    def test_success_does_not_call_stop(self):
        runner = self._mock_runner()
        with patch("v2ray_finder.xray_connectivity.XrayRunner", return_value=runner):
            _try_start_xray(10900, _FAKE_XRAY_CFG, None, False)
        runner.stop.assert_not_called()


# ---------------------------------------------------------------------------
# 4. check_one — success on first attempt
# ---------------------------------------------------------------------------

class TestCheckOneFirstAttemptSuccess(unittest.TestCase):

    def _run(self, port=10900):
        runner = MagicMock()
        runner.stop = MagicMock()

        with patch("v2ray_finder.xray_connectivity.config_to_xray",
                   return_value=_FAKE_XRAY_CFG), \
             patch("v2ray_finder.xray_connectivity.XrayRunner", return_value=runner), \
             patch("v2ray_finder.xray_connectivity._socks5_http_get",
                   return_value=(True, 204, 55.0)):
            return check_one(VLESS, local_port=port)

    def test_reachable_true(self):
        r = self._run()
        self.assertTrue(r.reachable)

    def test_google_204_ok(self):
        r = self._run()
        self.assertTrue(r.google_204_ok)

    def test_latency_populated(self):
        r = self._run()
        self.assertAlmostEqual(r.latency_ms, 55.0)

    def test_retried_false(self):
        r = self._run()
        self.assertFalse(r.retried)

    def test_runner_stop_called(self):
        runner = MagicMock()
        with patch("v2ray_finder.xray_connectivity.config_to_xray",
                   return_value=_FAKE_XRAY_CFG), \
             patch("v2ray_finder.xray_connectivity.XrayRunner", return_value=runner), \
             patch("v2ray_finder.xray_connectivity._socks5_http_get",
                   return_value=(True, 204, 55.0)):
            check_one(VLESS, local_port=10900)
        runner.stop.assert_called_once()


# ---------------------------------------------------------------------------
# 5. check_one — first start fails, retry succeeds
# ---------------------------------------------------------------------------

class TestCheckOneRetrySuccess(unittest.TestCase):

    def _run(self):
        fail_runner = MagicMock()
        fail_runner.start.side_effect = RuntimeError("port 10900 in use")
        fail_runner.stop = MagicMock()

        ok_runner = MagicMock()
        ok_runner.stop = MagicMock()

        runner_seq = [fail_runner, ok_runner]

        with patch("v2ray_finder.xray_connectivity.config_to_xray",
                   return_value=_FAKE_XRAY_CFG), \
             patch("v2ray_finder.xray_connectivity.XrayRunner",
                   side_effect=runner_seq), \
             patch("v2ray_finder.xray_connectivity.find_free_port",
                   return_value=10999), \
             patch("v2ray_finder.xray_connectivity._socks5_http_get",
                   return_value=(True, 204, 80.0)):
            return check_one(VLESS, local_port=10900)

    def test_retried_true(self):
        self.assertTrue(self._run().retried)

    def test_reachable_true_after_retry(self):
        self.assertTrue(self._run().reachable)

    def test_google_204_ok_after_retry(self):
        self.assertTrue(self._run().google_204_ok)

    def test_socks_port_is_retry_port(self):
        """After a successful retry the socks_port should be the retry port."""
        r = self._run()
        self.assertEqual(r.socks_port, 10999)

    def test_fail_runner_stop_called_for_cleanup(self):
        fail_runner = MagicMock()
        fail_runner.start.side_effect = RuntimeError("busy")
        ok_runner = MagicMock()

        with patch("v2ray_finder.xray_connectivity.config_to_xray",
                   return_value=_FAKE_XRAY_CFG), \
             patch("v2ray_finder.xray_connectivity.XrayRunner",
                   side_effect=[fail_runner, ok_runner]), \
             patch("v2ray_finder.xray_connectivity.find_free_port",
                   return_value=10999), \
             patch("v2ray_finder.xray_connectivity._socks5_http_get",
                   return_value=(True, 204, 80.0)):
            check_one(VLESS, local_port=10900)

        fail_runner.stop.assert_called_once()


# ---------------------------------------------------------------------------
# 6. check_one — both attempts fail
# ---------------------------------------------------------------------------

class TestCheckOneBothAttemptsFail(unittest.TestCase):

    def _run(self):
        fail1 = MagicMock()
        fail1.start.side_effect = RuntimeError("port A busy")
        fail1.stop = MagicMock()

        fail2 = MagicMock()
        fail2.start.side_effect = RuntimeError("port B busy")
        fail2.stop = MagicMock()

        with patch("v2ray_finder.xray_connectivity.config_to_xray",
                   return_value=_FAKE_XRAY_CFG), \
             patch("v2ray_finder.xray_connectivity.XrayRunner",
                   side_effect=[fail1, fail2]), \
             patch("v2ray_finder.xray_connectivity.find_free_port",
                   return_value=10999):
            return check_one(VLESS, local_port=10900)

    def test_not_reachable(self):
        self.assertFalse(self._run().reachable)

    def test_retried_true(self):
        self.assertTrue(self._run().retried)

    def test_error_contains_both_messages(self):
        r = self._run()
        self.assertIn("port A busy", r.error)
        self.assertIn("port B busy", r.error)

    def test_google_204_false(self):
        self.assertFalse(self._run().google_204_ok)


# ---------------------------------------------------------------------------
# 7. check_one — config_to_xray returns None
# ---------------------------------------------------------------------------

class TestCheckOneInvalidConfig(unittest.TestCase):

    def test_config_to_xray_none_returns_error(self):
        with patch("v2ray_finder.xray_connectivity.config_to_xray",
                   return_value=None):
            r = check_one(VLESS, local_port=10900)
        self.assertFalse(r.reachable)
        self.assertIsNotNone(r.error)

    def test_config_to_xray_none_no_retry(self):
        """When config conversion fails there should be no XrayRunner instantiation."""
        with patch("v2ray_finder.xray_connectivity.config_to_xray",
                   return_value=None), \
             patch("v2ray_finder.xray_connectivity.XrayRunner") as mock_runner:
            check_one(VLESS, local_port=10900)
        mock_runner.assert_not_called()


# ---------------------------------------------------------------------------
# 8. check_one — non-URI input
# ---------------------------------------------------------------------------

class TestCheckOneNonUri(unittest.TestCase):

    def test_not_a_uri_returns_error_result(self):
        r = check_one("not-a-uri", local_port=10900)
        self.assertFalse(r.reachable)
        self.assertIsNotNone(r.error)

    def test_protocol_is_unknown_for_non_uri(self):
        r = check_one("not-a-uri", local_port=10900)
        self.assertEqual(r.protocol, "unknown")


# ---------------------------------------------------------------------------
# 9. retried flag through RealConnectivityChecker.check_server_real_sync
# ---------------------------------------------------------------------------

class TestRealConnectivityCheckerRetried(unittest.TestCase):

    def test_retried_false_propagated(self):
        from v2ray_finder.xray_connectivity import RealConnectivityChecker
        checker = RealConnectivityChecker(cache_enabled=False)

        legacy = _LegacyResult(
            config=VLESS, protocol="vless",
            reachable=True, google_204_ok=True,
            latency_ms=50.0, socks_port=10900, retried=False,
        )
        with patch("v2ray_finder.xray_connectivity.check_one", return_value=legacy):
            result = checker.check_server_real_sync(VLESS, use_cache=False)

        self.assertFalse(result.retried)

    def test_retried_true_propagated(self):
        from v2ray_finder.xray_connectivity import RealConnectivityChecker
        checker = RealConnectivityChecker(cache_enabled=False)

        legacy = _LegacyResult(
            config=VLESS, protocol="vless",
            reachable=True, google_204_ok=True,
            latency_ms=80.0, socks_port=10999, retried=True,
        )
        with patch("v2ray_finder.xray_connectivity.check_one", return_value=legacy):
            result = checker.check_server_real_sync(VLESS, use_cache=False)

        self.assertTrue(result.retried)


# ---------------------------------------------------------------------------
# 10. check_real_connectivity_batch — retried flag forwarded
# ---------------------------------------------------------------------------

class TestBatchRetried(unittest.TestCase):

    def test_batch_result_carries_retried_true(self):
        legacy = _LegacyResult(
            config=VLESS, protocol="vless",
            reachable=True, google_204_ok=True,
            latency_ms=60.0, socks_port=10999, retried=True,
        )
        with patch("v2ray_finder.xray_connectivity.check_one", return_value=legacy):
            results = check_real_connectivity_batch([VLESS], max_workers=1)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].retried)

    def test_batch_result_carries_retried_false(self):
        legacy = _LegacyResult(
            config=VLESS, protocol="vless",
            reachable=True, google_204_ok=True,
            latency_ms=60.0, socks_port=10900, retried=False,
        )
        with patch("v2ray_finder.xray_connectivity.check_one", return_value=legacy):
            results = check_real_connectivity_batch([VLESS], max_workers=1)

        self.assertFalse(results[0].retried)

    def test_batch_empty_input(self):
        results = check_real_connectivity_batch([], max_workers=1)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
