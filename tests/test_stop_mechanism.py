"""Tests for the graceful stop / Ctrl+C interruption mechanism.

Covers three layers:
  1. core.py  – KeyboardInterrupt caught, partial results returned, should_stop() set.
  2. cli.py   – PipelineStopController wires Ctrl+C → stop_ctrl.stop();
                 interactive_menu per-operation KI handling.
  3. main()   – non-interactive path exits 130 and saves partial results.

NOTE: cli.py was migrated to Pipeline in V1-A2.  The old V2RayServerFinder-based
StopController and the old interactive_menu(finder) signature no longer exist.
Sections 5-7 test the new Pipeline-backed equivalents.
"""

from __future__ import annotations

import threading
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from v2ray_finder.core import V2RayServerFinder
from v2ray_finder.pipeline import StopController as PipelineStopController
from v2ray_finder.result import Ok

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finder() -> V2RayServerFinder:
    return V2RayServerFinder(token=None)


def _ok(servers: list) -> MagicMock:
    """Return a mock that looks like Ok(servers)."""
    m = MagicMock()
    m.is_ok.return_value = True
    m.is_err.return_value = False
    m.unwrap.return_value = servers
    return m


class _FakeSource:
    """Minimal stub that mimics a SourceEntry with a .url attribute."""

    def __init__(self, url: str) -> None:
        self.url = url


# ===========================================================================
# 1. core.py – get_servers_from_known_sources
# ===========================================================================


class TestKnownSourcesInterrupt:
    """get_servers_from_known_sources() must catch KeyboardInterrupt."""

    def _finder_two_sources(self):
        return _finder()

    def test_returns_partial_when_second_url_raises(self):
        finder = self._finder_two_sources()
        fake_sources = [_FakeSource("url_a"), _FakeSource("url_b")]

        def side_effect(url, **_):
            if url == "url_a":
                return Ok(["vmess://partial"])
            raise KeyboardInterrupt

        with patch("v2ray_finder.core.get_enabled_sources", return_value=fake_sources):
            with patch.object(finder, "get_servers_from_url", side_effect=side_effect):
                result = finder.get_servers_from_known_sources()

        # result is Dict[str, List[str]] — check across all source values
        all_configs = [cfg for configs in result.values() for cfg in configs]
        assert "vmess://partial" in all_configs

    def test_sets_should_stop_after_interrupt(self):
        finder = self._finder_two_sources()
        fake_sources = [_FakeSource("url_a"), _FakeSource("url_b")]

        with patch("v2ray_finder.core.get_enabled_sources", return_value=fake_sources):
            with patch.object(
                finder, "get_servers_from_url", side_effect=KeyboardInterrupt
            ):
                finder.get_servers_from_known_sources()

        assert finder.should_stop() is True

    def test_interrupt_does_not_propagate(self):
        finder = self._finder_two_sources()
        fake_sources = [_FakeSource("url_a"), _FakeSource("url_b")]

        with patch("v2ray_finder.core.get_enabled_sources", return_value=fake_sources):
            with patch.object(
                finder, "get_servers_from_url", side_effect=KeyboardInterrupt
            ):
                try:
                    finder.get_servers_from_known_sources()
                except KeyboardInterrupt:
                    pytest.fail(
                        "KeyboardInterrupt escaped get_servers_from_known_sources()"
                    )

    def test_reset_clears_stop_flag(self):
        finder = self._finder_two_sources()
        fake_sources = [_FakeSource("url_a"), _FakeSource("url_b")]

        with patch("v2ray_finder.core.get_enabled_sources", return_value=fake_sources):
            with patch.object(
                finder, "get_servers_from_url", side_effect=KeyboardInterrupt
            ):
                finder.get_servers_from_known_sources()

        assert finder.should_stop() is True
        finder.reset_stop()
        assert finder.should_stop() is False


# ===========================================================================
# 2. core.py – get_servers_from_github
# ===========================================================================


class TestGitHubSearchInterrupt:
    """get_servers_from_github() must catch KeyboardInterrupt."""

    def test_interrupt_in_search_repos_does_not_propagate(self):
        finder = _finder()
        with patch.object(finder, "search_repos", side_effect=KeyboardInterrupt):
            try:
                finder.get_servers_from_github()
            except KeyboardInterrupt:
                pytest.fail("KeyboardInterrupt escaped get_servers_from_github()")

    def test_sets_should_stop_after_interrupt_in_search_repos(self):
        finder = _finder()
        with patch.object(finder, "search_repos", side_effect=KeyboardInterrupt):
            finder.get_servers_from_github()
        assert finder.should_stop() is True

    def test_returns_partial_when_second_url_raises(self):
        finder = _finder()
        repos = [{"full_name": "user/repo"}]
        files = [
            {"name": "a.txt", "download_url": "http://x/a"},
            {"name": "b.txt", "download_url": "http://x/b"},
        ]

        call_count = {"n": 0}

        def url_side(url, **_):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return Ok(["vmess://first"])
            raise KeyboardInterrupt

        with patch.object(finder, "search_repos", return_value=_ok(repos)):
            with patch.object(finder, "get_repo_files", return_value=_ok(files)):
                with patch.object(finder, "get_servers_from_url", side_effect=url_side):
                    result = finder.get_servers_from_github(search_keywords=["kw"])

        assert "vmess://first" in result
        assert finder.should_stop() is True


# ===========================================================================
# 3. core.py – get_servers_with_health (pre-stop path)
# ===========================================================================


class TestHealthPreStop:
    """Verify that a pre-existing stop request skips all health checks."""

    def test_pre_stopped_returns_unchecked_servers(self):
        finder = _finder()
        finder.request_stop()

        servers = ["vmess://s1", "ss://s2"]
        # get_all_servers now returns (configs, overlap_map) tuple
        with patch.object(
            finder, "get_all_servers", return_value=(servers, {})
        ):
            result = finder.get_servers_with_health(check_health=True)

        assert len(result) == 2
        assert all(r["health_checked"] is False for r in result)

    def test_no_health_check_returns_unchecked_servers(self):
        finder = _finder()
        servers = ["trojan://t1", "vless://v1"]
        with patch.object(
            finder, "get_all_servers", return_value=(servers, {})
        ):
            result = finder.get_servers_with_health(check_health=False)

        assert len(result) == 2
        assert all(r["health_checked"] is False for r in result)


# ===========================================================================
# 4. core.py – get_servers_with_health (batch stop)
# ===========================================================================


class TestHealthBatchStop:
    @staticmethod
    def _make_health_result(config: str) -> MagicMock:
        h = MagicMock()
        h.config = config
        h.protocol = config.split("://")[0]
        h.status = MagicMock()
        h.status.value = "healthy"
        h.latency_ms = 10.0
        h.quality_score = 80.0
        h.host = "1.2.3.4"
        h.port = 443
        h.error = None
        h.validation_error = None
        h.tcp_ok = True
        h.http_probe_ok = True
        h.google_204_ok = False
        return h

    def test_ki_during_batch_returns_partial(self):
        finder = _finder()
        servers = ["vmess://s{}".format(i) for i in range(6)]

        try:
            from v2ray_finder.health_checker import HealthChecker  # noqa: F401
        except ImportError:
            pytest.skip("health_checker not available")

        batch_call = {"n": 0}

        def fake_check(batch):
            batch_call["n"] += 1
            if batch_call["n"] == 2:
                raise KeyboardInterrupt
            return [self._make_health_result(s) for s in batch]

        checker_mock = MagicMock()
        checker_mock.check_batch.side_effect = fake_check

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    finder, "get_all_servers", return_value=(servers, {})
                )
            )
            stack.enter_context(
                patch(
                    "v2ray_finder.core.HealthChecker",
                    return_value=checker_mock,
                )
            )
            stack.enter_context(
                patch(
                    "v2ray_finder.core.filter_healthy_servers",
                    side_effect=lambda r, **_: r,
                )
            )
            result = finder.get_servers_with_health(
                check_health=True, health_batch_size=3
            )

        assert len(result) == 3
        assert finder.should_stop() is True

    def test_ki_does_not_propagate(self):
        finder = _finder()
        servers = ["vmess://s1", "vmess://s2"]

        try:
            from v2ray_finder.health_checker import HealthChecker  # noqa: F401
        except ImportError:
            pytest.skip("health_checker not available")

        checker_mock = MagicMock()
        checker_mock.check_batch.side_effect = KeyboardInterrupt

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    finder, "get_all_servers", return_value=(servers, {})
                )
            )
            stack.enter_context(
                patch(
                    "v2ray_finder.core.HealthChecker",
                    return_value=checker_mock,
                )
            )
            stack.enter_context(
                patch(
                    "v2ray_finder.core.filter_healthy_servers",
                    side_effect=lambda r, **_: r,
                )
            )
            try:
                finder.get_servers_with_health(check_health=True)
            except KeyboardInterrupt:
                pytest.fail("KeyboardInterrupt escaped get_servers_with_health()")

    def test_should_stop_between_batches_stops_processing(self):
        finder = _finder()
        servers = ["vmess://s{}".format(i) for i in range(9)]

        try:
            from v2ray_finder.health_checker import HealthChecker  # noqa: F401
        except ImportError:
            pytest.skip("health_checker not available")

        def fake_check(batch):
            finder.request_stop()
            return [self._make_health_result(s) for s in batch]

        checker_mock = MagicMock()
        checker_mock.check_batch.side_effect = fake_check

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    finder, "get_all_servers", return_value=(servers, {})
                )
            )
            stack.enter_context(
                patch(
                    "v2ray_finder.core.HealthChecker",
                    return_value=checker_mock,
                )
            )
            stack.enter_context(
                patch(
                    "v2ray_finder.core.filter_healthy_servers",
                    side_effect=lambda r, **_: r,
                )
            )
            result = finder.get_servers_with_health(
                check_health=True, health_batch_size=3
            )

        assert checker_mock.check_batch.call_count == 1
        assert len(result) == 3

    def test_custom_batch_size_splits_work(self):
        finder = _finder()
        servers = ["vmess://s{}".format(i) for i in range(6)]

        try:
            from v2ray_finder.health_checker import HealthChecker  # noqa: F401
        except ImportError:
            pytest.skip("health_checker not available")

        checker_mock = MagicMock()
        checker_mock.check_batch.side_effect = lambda batch: [
            self._make_health_result(s) for s in batch
        ]

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    finder, "get_all_servers", return_value=(servers, {})
                )
            )
            stack.enter_context(
                patch(
                    "v2ray_finder.core.HealthChecker",
                    return_value=checker_mock,
                )
            )
            stack.enter_context(
                patch(
                    "v2ray_finder.core.filter_healthy_servers",
                    side_effect=lambda r, **_: r,
                )
            )
            result = finder.get_servers_with_health(
                check_health=True, health_batch_size=2
            )

        assert checker_mock.check_batch.call_count == 3
        assert len(result) == 6


# ===========================================================================
# 5. pipeline.py – PipelineStopController
# ===========================================================================


class TestPipelineStopController:
    """PipelineStopController: stop() sets event; is_set() reflects state."""

    def test_initial_state_not_set(self):
        ctrl = PipelineStopController()
        assert not ctrl.is_set()
        assert not ctrl.event.is_set()

    def test_stop_sets_event(self):
        ctrl = PipelineStopController()
        ctrl.stop()
        assert ctrl.is_set()
        assert ctrl.event.is_set()

    def test_stop_is_idempotent(self):
        ctrl = PipelineStopController()
        ctrl.stop()
        ctrl.stop()  # must not raise
        assert ctrl.is_set()

    def test_event_can_be_passed_to_pipeline(self):
        """event attribute is a threading.Event usable as stop_event."""
        ctrl = PipelineStopController()
        assert hasattr(ctrl.event, "is_set")
        assert hasattr(ctrl.event, "set")
        assert hasattr(ctrl.event, "wait")

    def test_stop_from_another_thread(self):
        ctrl = PipelineStopController()
        t = threading.Thread(target=ctrl.stop)
        t.start()
        t.join(timeout=2.0)
        assert ctrl.is_set()


# ===========================================================================
# 6. cli.py – interactive_menu (Pipeline-backed, token signature)
# ===========================================================================


class TestInteractiveMenu:
    """interactive_menu(token) must handle KI without leaking."""

    def test_ctrl_c_at_menu_prompt_exits_gracefully(self):
        from v2ray_finder.cli import interactive_menu

        printed = []
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            with patch(
                "builtins.print", side_effect=lambda *a, **_: printed.append(str(a))
            ):
                interactive_menu(token=None)  # must not raise

        assert any("Goodbye" in s for s in printed)

    def test_option_0_exits(self):
        from v2ray_finder.cli import interactive_menu

        with patch("builtins.input", return_value="0"):
            with patch("builtins.print"):
                interactive_menu(token=None)  # must return cleanly

    def test_invalid_option_prints_error(self):
        from v2ray_finder.cli import interactive_menu

        printed = []
        with patch("builtins.input", side_effect=["99", KeyboardInterrupt]):
            with patch(
                "builtins.print", side_effect=lambda *a, **_: printed.append(str(a))
            ):
                interactive_menu(token=None)

        assert any("Invalid" in s for s in printed)

    def test_option_1_calls_run_pipeline_interactive(self):
        """Choosing option 1 must invoke _run_pipeline_interactive."""
        from v2ray_finder import cli

        fake_result = MagicMock()
        fake_result.scores = []
        fake_result.configs = ["vmess://x"]
        fake_result.top_configs = ["vmess://x"]
        fake_result.stats = {}
        fake_result.health_dicts = None

        with patch.object(
            cli, "_run_pipeline_interactive", return_value=fake_result
        ) as mock_run:
            with patch("builtins.input", side_effect=["1", "0"]):
                with patch("builtins.print"):
                    cli.interactive_menu(token=None)

        mock_run.assert_called_once()


# ===========================================================================
# 7. cli.py – main() non-interactive path
# ===========================================================================


class TestMainNonInteractivePipeline:
    """main() must exit(130) and save results when StopController is set."""

    def test_exits_130_when_stopped(self, tmp_path):
        from v2ray_finder import cli

        out = str(tmp_path / "out.txt")
        fake_result = MagicMock()
        fake_result.scores = []
        fake_result.configs = []
        fake_result.top_configs = []
        fake_result.stats = {}
        fake_result.health_dicts = None

        fake_ctrl = MagicMock(spec=PipelineStopController)
        fake_ctrl.event = MagicMock()
        fake_ctrl.is_set.return_value = True

        with patch.object(cli, "Pipeline") as MockPipeline:
            MockPipeline.return_value.run.return_value = fake_result
            with patch(
                "v2ray_finder.cli.PipelineStopController", return_value=fake_ctrl
            ):
                with patch("sys.argv", ["v2ray-finder", "-o", out, "-q"]):
                    with patch("builtins.print"):
                        with patch.object(cli, "save_results"):
                            with pytest.raises(SystemExit) as exc_info:
                                cli.main()

        assert exc_info.value.code == 130

    def test_normal_completion_does_not_exit_130(self, tmp_path):
        from v2ray_finder import cli

        out = str(tmp_path / "servers.txt")
        fake_result = MagicMock()
        fake_result.scores = []
        fake_result.configs = ["vmess://s1"]
        fake_result.top_configs = ["vmess://s1"]
        fake_result.stats = {}
        fake_result.health_dicts = None

        fake_ctrl = MagicMock(spec=PipelineStopController)
        fake_ctrl.event = MagicMock()
        fake_ctrl.is_set.return_value = False

        with patch.object(cli, "Pipeline") as MockPipeline:
            MockPipeline.return_value.run.return_value = fake_result
            with patch(
                "v2ray_finder.cli.PipelineStopController", return_value=fake_ctrl
            ):
                with patch("sys.argv", ["v2ray-finder", "-o", out, "-q"]):
                    with patch("builtins.print"):
                        with patch.object(cli, "save_results"):
                            # Normal completion: accept clean return or SystemExit(0)
                            try:
                                cli.main()
                            except SystemExit as exc:
                                assert exc.code == 0, (
                                    f"Expected exit 0 or no exit, got {exc.code}"
                                )

    def test_saves_partial_when_stopped(self, tmp_path):
        from v2ray_finder import cli

        out = str(tmp_path / "partial.txt")
        partial = ["vmess://p1", "vmess://p2"]
        fake_result = MagicMock()
        fake_result.scores = []
        fake_result.configs = partial
        fake_result.top_configs = partial
        fake_result.stats = {}
        fake_result.health_dicts = None

        fake_ctrl = MagicMock(spec=PipelineStopController)
        fake_ctrl.event = MagicMock()
        fake_ctrl.is_set.return_value = True

        with patch.object(cli, "Pipeline") as MockPipeline:
            MockPipeline.return_value.run.return_value = fake_result
            with patch(
                "v2ray_finder.cli.PipelineStopController", return_value=fake_ctrl
            ):
                with patch("sys.argv", ["v2ray-finder", "-o", out, "-q"]):
                    with patch("builtins.print"):
                        with patch.object(cli, "save_results") as mock_save:
                            with pytest.raises(SystemExit):
                                cli.main()

        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert saved == partial
