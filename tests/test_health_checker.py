"""Tests for health_checker module — tiered probe pipeline.

Coverage:
  - ServerHealth dataclass properties (is_healthy, quality_score, probe_level)
  - ServerValidator  — all 5 protocols + validate_config
  - HealthChecker    — Layer 1 (TCP), Layer 2 (HTTP probe), Layer 3 (xray/204)
  - Batch helpers    — check_servers_batch, check_servers, check_batch
  - filter_healthy_servers / sort_by_quality
  - _http_direct_probe / _socks5_http_get  (unit-tested with mocks)
"""

from __future__ import annotations

import asyncio
import base64
import json
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from v2ray_finder.health_checker import (
    HealthChecker,
    HealthStatus,
    ServerHealth,
    ServerValidator,
    _http_direct_probe,
    _latency_to_score,
    _socks5_http_get,
    filter_healthy_servers,
    sort_by_quality,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vmess(host: str, port: int) -> str:
    data = {"add": host, "port": port}
    encoded = base64.b64encode(json.dumps(data).encode()).decode()
    return f"vmess://{encoded}"


def _make_ssr(host: str, port: int) -> str:
    ssr_body = f"{host}:{port}:auth_sha1_v4:rc4-md5:http_simple:dGVzdA=="
    encoded = base64.b64encode(ssr_body.encode()).decode().rstrip("=")
    return f"ssr://{encoded}"


# ---------------------------------------------------------------------------
# _latency_to_score
# ---------------------------------------------------------------------------

class TestLatencyToScore:
    def test_at_100ms_is_100(self):
        assert _latency_to_score(100.0) == 100.0

    def test_below_100ms_is_100(self):
        assert _latency_to_score(50.0) == 100.0

    def test_at_200ms(self):
        # 100 - (100)*(30/200) = 85
        assert _latency_to_score(200.0) == pytest.approx(85.0, abs=0.1)

    def test_at_300ms_boundary(self):
        assert _latency_to_score(300.0) == pytest.approx(70.0, abs=0.1)

    def test_at_1000ms_boundary(self):
        assert _latency_to_score(1000.0) == pytest.approx(20.0, abs=0.1)

    def test_at_3000ms_is_zero(self):
        assert _latency_to_score(3000.0) == 0.0

    def test_beyond_3000ms_is_zero(self):
        assert _latency_to_score(9999.0) == 0.0

    def test_monotone_decreasing(self):
        latencies = [50, 100, 200, 300, 500, 1000, 1500, 2000, 3000, 5000]
        scores = [_latency_to_score(float(l)) for l in latencies]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Not monotone at {latencies[i]}ms ({scores[i]}) "
                f"→ {latencies[i+1]}ms ({scores[i+1]})"
            )


# ---------------------------------------------------------------------------
# ServerHealth — is_healthy
# ---------------------------------------------------------------------------

def test_is_healthy_true():
    h = ServerHealth(config="vmess://x", protocol="vmess", status=HealthStatus.HEALTHY)
    assert h.is_healthy is True


def test_is_healthy_degraded_is_true():
    h = ServerHealth(config="vmess://x", protocol="vmess", status=HealthStatus.DEGRADED)
    assert h.is_healthy is True


def test_is_healthy_false_unreachable():
    h = ServerHealth(config="vmess://x", protocol="vmess", status=HealthStatus.UNREACHABLE)
    assert h.is_healthy is False


def test_is_healthy_false_invalid():
    h = ServerHealth(config="x", protocol="?", status=HealthStatus.INVALID)
    assert h.is_healthy is False


# ---------------------------------------------------------------------------
# ServerHealth — quality_score
# ---------------------------------------------------------------------------

class TestQualityScore:
    def test_invalid_is_zero(self):
        h = ServerHealth(config="x", protocol="?", status=HealthStatus.INVALID)
        assert h.quality_score == 0.0

    def test_unreachable_is_zero(self):
        h = ServerHealth(config="x", protocol="?", status=HealthStatus.UNREACHABLE)
        assert h.quality_score == 0.0

    def test_no_latency_is_fifty(self):
        h = ServerHealth(config="x", protocol="?", status=HealthStatus.HEALTHY, latency_ms=None)
        assert h.quality_score == 50.0

    def test_tcp_latency_50ms_is_100(self):
        h = ServerHealth(config="x", protocol="?", status=HealthStatus.HEALTHY, latency_ms=50.0)
        assert h.quality_score == 100.0

    def test_tcp_latency_200ms(self):
        h = ServerHealth(config="x", protocol="?", status=HealthStatus.HEALTHY, latency_ms=200.0)
        assert h.quality_score == pytest.approx(85.0, abs=0.5)

    def test_at_300ms_boundary(self):
        h = ServerHealth(config="x", protocol="?", status=HealthStatus.HEALTHY, latency_ms=300.0)
        assert h.quality_score == pytest.approx(70.0, abs=0.5)

    def test_at_1000ms_boundary(self):
        h = ServerHealth(config="x", protocol="?", status=HealthStatus.HEALTHY, latency_ms=1000.0)
        assert h.quality_score == pytest.approx(20.0, abs=0.5)

    def test_at_3000ms_floor(self):
        h = ServerHealth(config="x", protocol="?", status=HealthStatus.HEALTHY, latency_ms=3000.0)
        assert h.quality_score == 0.0

    def test_beyond_3000ms_stays_zero(self):
        h = ServerHealth(config="x", protocol="?", status=HealthStatus.HEALTHY, latency_ms=9999.0)
        assert h.quality_score == 0.0

    def test_live_server_beats_dead(self):
        slow = ServerHealth(config="x", protocol="vmess", status=HealthStatus.HEALTHY, latency_ms=2999.0)
        dead = ServerHealth(config="y", protocol="vmess", status=HealthStatus.UNREACHABLE)
        assert slow.quality_score > dead.quality_score

    def test_monotone_decreasing(self):
        latencies = [50, 100, 200, 300, 500, 1000, 1500, 2000, 3000, 5000]
        scores = [
            ServerHealth(config="x", protocol="vmess", status=HealthStatus.HEALTHY,
                         latency_ms=float(l)).quality_score
            for l in latencies
        ]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_google_204_latency_takes_priority_over_tcp(self):
        """Layer 3 latency governs score even if TCP was fast."""
        h = ServerHealth(
            config="x", protocol="vmess", status=HealthStatus.HEALTHY,
            latency_ms=50.0,
            google_204_latency_ms=2000.0,
        )
        assert h.quality_score == pytest.approx(10.0, abs=0.5)

    def test_google_204_latency_fast_scores_high(self):
        h = ServerHealth(
            config="x", protocol="vmess", status=HealthStatus.HEALTHY,
            latency_ms=800.0,
            google_204_latency_ms=80.0,
        )
        assert h.quality_score == 100.0

    def test_probe_level_field_default_zero(self):
        h = ServerHealth(config="x", protocol="vmess")
        assert h.probe_level == 0


# ---------------------------------------------------------------------------
# ServerValidator — extract_*
# ---------------------------------------------------------------------------

class TestServerValidator:
    def test_extract_vmess_valid(self):
        config = _make_vmess("example.com", 443)
        r = ServerValidator.extract_vmess_info(config)
        assert r is not None
        assert r["host"] == "example.com"
        assert r["port"] == 443

    def test_extract_vmess_uses_address_field(self):
        data = {"address": "alt.com", "port": 80}
        encoded = base64.b64encode(json.dumps(data).encode()).decode()
        r = ServerValidator.extract_vmess_info(f"vmess://{encoded}")
        assert r["host"] == "alt.com"

    def test_extract_vmess_invalid_returns_none(self):
        assert ServerValidator.extract_vmess_info("vmess://not_valid_base64!!!") is None

    def test_extract_vless_valid(self):
        r = ServerValidator.extract_vless_info("vless://uuid@example.com:443?encryption=none#tag")
        assert r is not None
        assert r["host"] == "example.com"
        assert r["port"] == 443

    def test_extract_trojan_valid(self):
        r = ServerValidator.extract_trojan_info("trojan://pw@example.com:443?security=tls#tag")
        assert r is not None
        assert r["host"] == "example.com"
        assert r["port"] == 443

    def test_extract_ss_valid_with_at(self):
        r = ServerValidator.extract_ss_info("ss://method:password@example.com:8388#tag")
        assert r is not None
        assert r["host"] == "example.com"
        assert r["port"] == 8388

    def test_extract_ssr_valid(self):
        r = ServerValidator.extract_ssr_info(_make_ssr("ssr.example.com", 1080))
        assert r is not None
        assert r["host"] == "ssr.example.com"
        assert r["port"] == 1080

    def test_validate_config_empty(self):
        ok, err, host, port = ServerValidator.validate_config("")
        assert ok is False
        assert err == "Empty config"

    def test_validate_config_no_scheme(self):
        ok, err, host, port = ServerValidator.validate_config("example.com:443")
        assert ok is False
        assert "scheme" in err.lower() or "uri" in err.lower()

    def test_validate_config_unknown_protocol(self):
        ok, err, host, port = ServerValidator.validate_config("http://example.com:80")
        assert ok is False
        assert "Unknown" in err

    def test_validate_config_valid_vless(self):
        ok, err, host, port = ServerValidator.validate_config(
            "vless://uuid@example.com:443?encryption=none"
        )
        assert ok is True
        assert host == "example.com"
        assert port == 443


# ---------------------------------------------------------------------------
# _http_direct_probe — Layer 2
# ---------------------------------------------------------------------------

class TestHttpDirectProbe:
    def test_success_returns_ok_status_latency(self):
        fake_response = b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n"
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [fake_response, b""]
        with patch("socket.create_connection", return_value=mock_sock):
            ok, status, latency, err = _http_direct_probe(timeout=5.0)
        assert ok is True
        assert status == 204
        assert latency is not None
        assert err is None

    def test_200_response_is_ok(self):
        fake_response = b"HTTP/1.1 200 OK\r\n\r\n"
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [fake_response, b""]
        with patch("socket.create_connection", return_value=mock_sock):
            ok, status, latency, err = _http_direct_probe(timeout=5.0)
        assert ok is True
        assert status == 200

    def test_connection_refused_returns_failure(self):
        with patch("socket.create_connection", side_effect=ConnectionRefusedError("refused")):
            ok, status, latency, err = _http_direct_probe(timeout=1.0)
        assert ok is False
        assert status is None
        assert err is not None

    def test_timeout_returns_failure(self):
        with patch("socket.create_connection", side_effect=socket.timeout("timed out")):
            ok, status, latency, err = _http_direct_probe(timeout=0.001)
        assert ok is False
        assert err is not None

    def test_malformed_response_returns_failure(self):
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [b"GARBAGE\r\n", b""]
        with patch("socket.create_connection", return_value=mock_sock):
            ok, status, latency, err = _http_direct_probe(timeout=5.0)
        assert ok is False


# ---------------------------------------------------------------------------
# _socks5_http_get — Layer 3
# ---------------------------------------------------------------------------

class TestSocks5HttpGet:
    def _make_sock(self, handshake_ok=True, connect_ok=True, http_resp=b"HTTP/1.1 204 No Content\r\n"):
        mock_sock = MagicMock()
        responses = []
        if handshake_ok:
            responses.append(b"\x05\x00")
        else:
            responses.append(b"\x05\xFF")
        if connect_ok:
            responses.append(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        else:
            responses.append(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")
        responses.append(http_resp)
        responses.append(b"")
        mock_sock.recv.side_effect = responses
        return mock_sock

    def test_successful_204(self):
        mock_sock = self._make_sock()
        with patch("socket.create_connection", return_value=mock_sock):
            ok, status, latency = _socks5_http_get("127.0.0.1", 10808,
                                                    "clients3.google.com", 80, "/generate_204")
        assert ok is True
        assert status == 204

    def test_socks5_handshake_rejected(self):
        mock_sock = self._make_sock(handshake_ok=False)
        with patch("socket.create_connection", return_value=mock_sock):
            ok, status, latency = _socks5_http_get("127.0.0.1", 10808,
                                                    "clients3.google.com", 80, "/generate_204")
        assert ok is False

    def test_socks5_connect_rejected(self):
        mock_sock = self._make_sock(connect_ok=False)
        with patch("socket.create_connection", return_value=mock_sock):
            ok, status, latency = _socks5_http_get("127.0.0.1", 10808,
                                                    "clients3.google.com", 80, "/generate_204")
        assert ok is False

    def test_connection_error_returns_failure(self):
        with patch("socket.create_connection", side_effect=ConnectionRefusedError("refused")):
            ok, status, latency = _socks5_http_get("127.0.0.1", 19999,
                                                    "clients3.google.com", 80, "/generate_204")
        assert ok is False
        assert latency >= 0


# ---------------------------------------------------------------------------
# HealthChecker — Layer 1 (TCP)
# ---------------------------------------------------------------------------

class TestHealthCheckerTCP:
    @pytest.mark.asyncio
    async def test_missing_host_returns_failure(self):
        checker = HealthChecker()
        ok, latency, err = await checker.check_tcp_connectivity("", 443)
        assert ok is False
        assert "host" in err.lower()

    @pytest.mark.asyncio
    async def test_missing_port_returns_failure(self):
        checker = HealthChecker()
        ok, latency, err = await checker.check_tcp_connectivity("example.com", 0)
        assert ok is False
        assert "port" in err.lower()

    @pytest.mark.asyncio
    async def test_timeout_returns_failure(self):
        checker = HealthChecker(timeout=0.001)
        ok, latency, err = await checker.check_tcp_connectivity("192.0.2.1", 9999)
        assert ok is False
        assert err is not None

    @pytest.mark.asyncio
    async def test_unsupported_protocol_is_invalid(self):
        checker = HealthChecker()
        result = await checker.check_server_health("http://example.com", "http")
        assert result.status == HealthStatus.INVALID
        assert "Unsupported" in result.validation_error

    @pytest.mark.asyncio
    async def test_invalid_format_is_invalid(self):
        checker = HealthChecker()
        result = await checker.check_server_health("vmess://not_valid!!!", "vmess")
        assert result.status == HealthStatus.INVALID

    @pytest.mark.asyncio
    async def test_reachable_server_is_healthy(self):
        checker = HealthChecker()
        vmess = _make_vmess("example.com", 443)
        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(True, 50.0, None)):
            result = await checker.check_server_health(vmess, "vmess")
        assert result.status == HealthStatus.HEALTHY
        assert result.tcp_ok is True
        assert result.latency_ms == 50.0
        assert result.quality_score == 100.0
        assert result.probe_level == 1

    @pytest.mark.asyncio
    async def test_unreachable_server(self):
        checker = HealthChecker()
        vmess = _make_vmess("example.com", 443)
        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(False, None, "Connection refused")):
            result = await checker.check_server_health(vmess, "vmess")
        assert result.status == HealthStatus.UNREACHABLE
        assert result.tcp_ok is False
        assert result.error == "Connection refused"
        assert result.quality_score == 0.0
        assert result.probe_level == 1

    @pytest.mark.asyncio
    async def test_high_latency_is_degraded(self):
        checker = HealthChecker()
        vmess = _make_vmess("example.com", 443)
        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(True, 600.0, None)):
            result = await checker.check_server_health(vmess, "vmess")
        assert result.status == HealthStatus.DEGRADED
        assert 40.0 < result.quality_score < 60.0


# ---------------------------------------------------------------------------
# HealthChecker — Layer 2 (HTTP probe)
# ---------------------------------------------------------------------------

class TestHealthCheckerHTTPProbe:
    @pytest.mark.asyncio
    async def test_http_probe_ok_sets_field(self):
        checker = HealthChecker(check_http_probe=True)
        vmess = _make_vmess("example.com", 443)
        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(True, 50.0, None)):
            with patch.object(checker, "_run_http_probe",
                               new_callable=AsyncMock, return_value=(True, 204, 120.0, None)):
                result = await checker.check_server_health(vmess, "vmess")
        assert result.http_probe_ok is True
        assert result.http_probe_latency_ms == 120.0
        assert result.probe_level == 2

    @pytest.mark.asyncio
    async def test_http_probe_failure_still_sets_field(self):
        checker = HealthChecker(check_http_probe=True)
        vmess = _make_vmess("example.com", 443)
        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(True, 50.0, None)):
            with patch.object(checker, "_run_http_probe",
                               new_callable=AsyncMock, return_value=(False, None, None, "timeout")):
                result = await checker.check_server_health(vmess, "vmess")
        assert result.http_probe_ok is False
        assert result.http_probe_error == "timeout"
        assert result.probe_level == 2

    @pytest.mark.asyncio
    async def test_http_probe_skipped_when_disabled(self):
        checker = HealthChecker(check_http_probe=False)
        vmess = _make_vmess("example.com", 443)
        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(True, 50.0, None)):
            with patch.object(checker, "_run_http_probe",
                               new_callable=AsyncMock) as mock_probe:
                result = await checker.check_server_health(vmess, "vmess")
        mock_probe.assert_not_called()
        assert result.probe_level == 1

    @pytest.mark.asyncio
    async def test_http_probe_skipped_when_tcp_failed(self):
        """Layer 2 must NOT run if Layer 1 (TCP) failed."""
        checker = HealthChecker(check_http_probe=True)
        vmess = _make_vmess("example.com", 443)
        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(False, None, "refused")):
            with patch.object(checker, "_run_http_probe",
                               new_callable=AsyncMock) as mock_probe:
                result = await checker.check_server_health(vmess, "vmess")
        mock_probe.assert_not_called()
        assert result.status == HealthStatus.UNREACHABLE


# ---------------------------------------------------------------------------
# HealthChecker — Layer 3 (xray / Google 204)
# ---------------------------------------------------------------------------

class TestHealthCheckerGoogle204:
    @pytest.mark.asyncio
    async def test_google_204_ok_sets_field_and_probe_level(self):
        checker = HealthChecker(check_google_204=True)
        vmess = _make_vmess("example.com", 443)

        mock_real_result = MagicMock()
        mock_real_result.google_204_ok = True
        mock_real_result.latency_ms = 90.0

        mock_checker = MagicMock()
        mock_checker.is_xray_available.return_value = True
        mock_checker.check_server_real_sync.return_value = mock_real_result

        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(True, 50.0, None)):
            with patch("v2ray_finder.health_checker.RealConnectivityChecker",
                       return_value=mock_checker):
                result = await checker.check_server_health(vmess, "vmess")

        assert result.google_204_ok is True
        assert result.google_204_latency_ms == 90.0
        assert result.probe_level == 3
        assert result.quality_score == 100.0

    @pytest.mark.asyncio
    async def test_google_204_slow_latency_governs_score(self):
        checker = HealthChecker(check_google_204=True)
        vmess = _make_vmess("example.com", 443)

        mock_real_result = MagicMock()
        mock_real_result.google_204_ok = True
        mock_real_result.latency_ms = 2000.0

        mock_checker = MagicMock()
        mock_checker.is_xray_available.return_value = True
        mock_checker.check_server_real_sync.return_value = mock_real_result

        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(True, 30.0, None)):
            with patch("v2ray_finder.health_checker.RealConnectivityChecker",
                       return_value=mock_checker):
                result = await checker.check_server_health(vmess, "vmess")

        assert result.quality_score == pytest.approx(10.0, abs=0.5)

    @pytest.mark.asyncio
    async def test_layer3_skipped_when_xray_unavailable(self):
        checker = HealthChecker(check_google_204=True)
        vmess = _make_vmess("example.com", 443)

        mock_checker = MagicMock()
        mock_checker.is_xray_available.return_value = False

        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(True, 50.0, None)):
            with patch("v2ray_finder.health_checker.RealConnectivityChecker",
                       return_value=mock_checker):
                result = await checker.check_server_health(vmess, "vmess")

        assert result.probe_level == 1
        assert result.google_204_ok is False

    @pytest.mark.asyncio
    async def test_layer3_exception_is_caught_gracefully(self):
        checker = HealthChecker(check_google_204=True)
        vmess = _make_vmess("example.com", 443)

        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(True, 50.0, None)):
            with patch("v2ray_finder.health_checker.RealConnectivityChecker",
                       side_effect=RuntimeError("xray crashed")):
                result = await checker.check_server_health(vmess, "vmess")

        assert result.tcp_ok is True
        assert result.google_204_ok is False
        assert result.probe_level == 1

    @pytest.mark.asyncio
    async def test_layer3_skipped_when_disabled(self):
        checker = HealthChecker(check_google_204=False)
        vmess = _make_vmess("example.com", 443)

        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(True, 50.0, None)):
            with patch("v2ray_finder.health_checker.RealConnectivityChecker") as mock_cls:
                result = await checker.check_server_health(vmess, "vmess")

        mock_cls.assert_not_called()
        assert result.probe_level == 1


# ---------------------------------------------------------------------------
# HealthChecker — batch helpers
# ---------------------------------------------------------------------------

class TestHealthCheckerBatch:
    @pytest.mark.asyncio
    async def test_batch_empty(self):
        checker = HealthChecker()
        assert await checker.check_servers_batch([]) == []

    @pytest.mark.asyncio
    async def test_batch_multiple_servers(self):
        checker = HealthChecker()
        vmess1 = _make_vmess("host1.com", 443)
        vmess2 = _make_vmess("host2.com", 8443)
        with patch.object(checker, "check_tcp_connectivity",
                          new_callable=AsyncMock, return_value=(True, 30.0, None)):
            results = await checker.check_servers_batch([(vmess1, "vmess"), (vmess2, "vmess")])
        assert len(results) == 2
        assert all(r.status == HealthStatus.HEALTHY for r in results)

    @pytest.mark.asyncio
    async def test_batch_exceptions_do_not_abort(self):
        checker = HealthChecker()
        vmess_good = _make_vmess("good.com", 443)
        vmess_bad = _make_vmess("bad.com", 443)

        async def mock_health(config, protocol):
            if "bad" in config:
                raise RuntimeError("simulated crash")
            return ServerHealth(config=config, protocol=protocol,
                                status=HealthStatus.HEALTHY, tcp_ok=True)

        with patch.object(checker, "check_server_health", side_effect=mock_health):
            results = await checker.check_servers_batch(
                [(vmess_good, "vmess"), (vmess_bad, "vmess")]
            )
        assert len(results) == 1
        assert results[0].status == HealthStatus.HEALTHY

    def test_check_one_invalid_config(self):
        checker = HealthChecker()
        result = checker.check_one("not-a-valid-config")
        assert result.status == HealthStatus.INVALID

    def test_check_batch_empty(self):
        checker = HealthChecker()
        assert checker.check_batch([]) == []

    def test_check_batch_invalid_configs(self):
        checker = HealthChecker()
        results = checker.check_batch(["invalid1", "invalid2"])
        assert len(results) == 2
        assert all(r.status == HealthStatus.INVALID for r in results)


# ---------------------------------------------------------------------------
# filter_healthy_servers
# ---------------------------------------------------------------------------

class TestFilterHealthyServers:
    def test_removes_invalid(self):
        results = [
            ServerHealth(config="x", protocol="?", status=HealthStatus.INVALID),
            ServerHealth(config="y", protocol="vmess", status=HealthStatus.HEALTHY),
        ]
        assert len(filter_healthy_servers(results)) == 1

    def test_removes_unreachable_by_default(self):
        results = [
            ServerHealth(config="x", protocol="?", status=HealthStatus.UNREACHABLE),
            ServerHealth(config="y", protocol="vmess", status=HealthStatus.HEALTHY),
        ]
        assert len(filter_healthy_servers(results)) == 1

    def test_keeps_unreachable_when_flag_off(self):
        results = [
            ServerHealth(config="x", protocol="?", status=HealthStatus.UNREACHABLE),
            ServerHealth(config="y", protocol="vmess", status=HealthStatus.HEALTHY),
        ]
        assert len(filter_healthy_servers(results, exclude_unreachable=False)) == 2

    def test_min_quality_score_filters_slow(self):
        results = [
            ServerHealth(config="fast", protocol="vmess", status=HealthStatus.HEALTHY, latency_ms=50.0),
            ServerHealth(config="dead", protocol="vmess", status=HealthStatus.UNREACHABLE),
        ]
        filtered = filter_healthy_servers(results, exclude_unreachable=False, min_quality_score=50.0)
        assert len(filtered) == 1
        assert filtered[0].config == "fast"

    def test_empty_list_returns_empty(self):
        assert filter_healthy_servers([]) == []

    def test_all_invalid_returns_empty(self):
        results = [
            ServerHealth(config="x", protocol="?", status=HealthStatus.INVALID),
            ServerHealth(config="y", protocol="?", status=HealthStatus.INVALID),
        ]
        assert filter_healthy_servers(results) == []


# ---------------------------------------------------------------------------
# sort_by_quality
# ---------------------------------------------------------------------------

class TestSortByQuality:
    def test_descending_puts_fastest_first(self):
        results = [
            ServerHealth(config="slow", protocol="vmess", status=HealthStatus.HEALTHY, latency_ms=800.0),
            ServerHealth(config="fast", protocol="vmess", status=HealthStatus.HEALTHY, latency_ms=50.0),
            ServerHealth(config="dead", protocol="?", status=HealthStatus.UNREACHABLE),
        ]
        sorted_r = sort_by_quality(results)
        assert sorted_r[0].config == "fast"
        assert sorted_r[-1].config == "dead"

    def test_ascending_puts_slowest_first(self):
        results = [
            ServerHealth(config="fast", protocol="vmess", status=HealthStatus.HEALTHY, latency_ms=50.0),
            ServerHealth(config="dead", protocol="?", status=HealthStatus.UNREACHABLE),
        ]
        sorted_r = sort_by_quality(results, descending=False)
        assert sorted_r[0].config == "dead"

    def test_empty_list(self):
        assert sort_by_quality([]) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
