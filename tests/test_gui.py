"""Tests for gui/main_window.py — WorkerThread and MainWindow.

Requires:  pytest-qt  (pip install pytest-qt)
CI needs:  QT_QPA_PLATFORM=offscreen  (set in conftest or env)
"""

import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pyside6 = pytest.importorskip("PySide6", reason="PySide6 not installed")
pytest_qt = pytest.importorskip("pytestqt", reason="pytest-qt not installed")

from unittest.mock import MagicMock, patch  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from v2ray_finder.gui.main_window import MainWindow, WorkerThread  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp():
    """Single QApplication for the whole test session."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp):
    w = MainWindow()
    yield w
    w.close()


# ---------------------------------------------------------------------------
# WorkerThread
# ---------------------------------------------------------------------------


class TestWorkerThread:
    def test_run_emits_finished_with_servers(self, qtbot):
        servers = ["vless://a", "vmess://b"]
        finder_mock = MagicMock()
        finder_mock.get_servers_from_known_sources.return_value = servers

        with patch(
            "v2ray_finder.gui.main_window.V2RayServerFinder",
            return_value=finder_mock,
        ):
            worker = WorkerThread(token=None, use_search=False)
            received = []
            worker.finished.connect(received.append)

            with qtbot.waitSignal(worker.finished, timeout=3000):
                worker.run()

        assert received[0] == servers

    def test_run_with_search_merges_results(self, qtbot):
        known = ["vless://a"]
        github = ["vmess://b", "vless://a"]  # duplicate
        finder_mock = MagicMock()
        finder_mock.get_servers_from_known_sources.return_value = known
        finder_mock.get_servers_from_github.return_value = github

        with patch(
            "v2ray_finder.gui.main_window.V2RayServerFinder",
            return_value=finder_mock,
        ):
            worker = WorkerThread(token="tok", use_search=True)
            received = []
            worker.finished.connect(received.append)

            with qtbot.waitSignal(worker.finished, timeout=3000):
                worker.run()

        # deduplication: vless://a appears once
        assert received[0].count("vless://a") == 1
        assert "vmess://b" in received[0]

    def test_run_emits_error_on_exception(self, qtbot):
        with patch(
            "v2ray_finder.gui.main_window.V2RayServerFinder",
            side_effect=RuntimeError("boom"),
        ):
            worker = WorkerThread()
            errors = []
            worker.error.connect(errors.append)

            with qtbot.waitSignal(worker.error, timeout=3000):
                worker.run()

        assert "boom" in errors[0]

    def test_run_emits_progress_signals(self, qtbot):
        finder_mock = MagicMock()
        finder_mock.get_servers_from_known_sources.return_value = []

        with patch(
            "v2ray_finder.gui.main_window.V2RayServerFinder",
            return_value=finder_mock,
        ):
            worker = WorkerThread()
            progress_msgs = []
            worker.progress.connect(progress_msgs.append)

            with qtbot.waitSignal(worker.finished, timeout=3000):
                worker.run()

        assert len(progress_msgs) >= 2


# ---------------------------------------------------------------------------
# MainWindow — initial state
# ---------------------------------------------------------------------------


class TestMainWindowInit:
    def test_window_title(self, window):
        assert window.windowTitle() == "v2ray-finder"

    def test_save_btn_disabled_initially(self, window):
        assert not window.save_btn.isEnabled()

    def test_copy_btn_disabled_initially(self, window):
        assert not window.copy_btn.isEnabled()

    def test_table_empty_initially(self, window):
        assert window.table.rowCount() == 0

    def test_servers_list_empty_initially(self, window):
        assert window.servers == []


# ---------------------------------------------------------------------------
# MainWindow — on_fetch_finished
# ---------------------------------------------------------------------------


class TestOnFetchFinished:
    SERVERS = [
        "vless://host1:443",
        "vmess://host2:80",
        "trojan://host3:443",
    ]

    def test_table_populated(self, window):
        window.on_fetch_finished(self.SERVERS)
        assert window.table.rowCount() == 3

    def test_table_row_content(self, window):
        window.on_fetch_finished(self.SERVERS)
        assert window.table.item(0, 1).text() == "vless"
        assert window.table.item(1, 1).text() == "vmess"
        assert window.table.item(2, 2).text() == "trojan://host3:443"

    def test_save_btn_enabled_after_fetch(self, window):
        window.on_fetch_finished(self.SERVERS)
        assert window.save_btn.isEnabled()

    def test_copy_btn_enabled_after_fetch(self, window):
        window.on_fetch_finished(self.SERVERS)
        assert window.copy_btn.isEnabled()

    def test_fetch_btn_re_enabled(self, window):
        window.fetch_btn.setEnabled(False)
        window.on_fetch_finished(self.SERVERS)
        assert window.fetch_btn.isEnabled()

    def test_status_label_updated(self, window):
        window.on_fetch_finished(self.SERVERS)
        assert "3" in window.status_label.text()

    def test_progress_bar_hidden(self, window):
        window.progress_bar.setVisible(True)
        window.on_fetch_finished(self.SERVERS)
        assert not window.progress_bar.isVisible()

    def test_limit_respected(self, window):
        window.limit_spinbox.setValue(2)
        window.on_fetch_finished(self.SERVERS)
        assert window.table.rowCount() == 2
        window.limit_spinbox.setValue(0)  # reset

    def test_no_limit_shows_all(self, window):
        window.limit_spinbox.setValue(0)
        window.on_fetch_finished(self.SERVERS)
        assert window.table.rowCount() == 3

    def test_servers_stored(self, window):
        window.on_fetch_finished(self.SERVERS)
        assert window.servers == self.SERVERS

    def test_unknown_protocol_label(self, window):
        window.on_fetch_finished(["noscheme"])
        assert window.table.item(0, 1).text() == "unknown"


# ---------------------------------------------------------------------------
# MainWindow — on_fetch_error
# ---------------------------------------------------------------------------


class TestOnFetchError:
    def test_status_label_shows_error(self, window):
        window.on_fetch_error("network timeout")
        assert "network timeout" in window.status_label.text()

    def test_fetch_btn_re_enabled(self, window):
        window.fetch_btn.setEnabled(False)
        window.on_fetch_error("err")
        assert window.fetch_btn.isEnabled()

    def test_progress_bar_hidden(self, window):
        window.progress_bar.setVisible(True)
        window.on_fetch_error("err")
        assert not window.progress_bar.isVisible()


# ---------------------------------------------------------------------------
# MainWindow — update_stats
# ---------------------------------------------------------------------------


class TestUpdateStats:
    def test_counts_protocols(self, window):
        servers = ["vless://a", "vless://b", "vmess://c"]
        window.update_stats(servers)
        text = window.stats_label.text()
        assert "vless: 2" in text
        assert "vmess: 1" in text

    def test_total_in_stats(self, window):
        window.update_stats(["vmess://x", "trojan://y"])
        assert "Total: 2" in window.stats_label.text()

    def test_empty_servers(self, window):
        window.update_stats([])
        assert "Total: 0" in window.stats_label.text()

    def test_unknown_protocol_counted(self, window):
        window.update_stats(["noscheme"])
        assert "unknown: 1" in window.stats_label.text()


# ---------------------------------------------------------------------------
# MainWindow — clear_table
# ---------------------------------------------------------------------------


class TestClearTable:
    def test_table_emptied(self, window):
        window.on_fetch_finished(["vless://x"])
        window.clear_table()
        assert window.table.rowCount() == 0

    def test_servers_reset(self, window):
        window.servers = ["vless://x"]
        window.clear_table()
        assert window.servers == []

    def test_save_btn_disabled(self, window):
        window.save_btn.setEnabled(True)
        window.clear_table()
        assert not window.save_btn.isEnabled()

    def test_copy_btn_disabled(self, window):
        window.copy_btn.setEnabled(True)
        window.clear_table()
        assert not window.copy_btn.isEnabled()

    def test_status_label_updated(self, window):
        window.clear_table()
        assert "cleared" in window.status_label.text().lower()

    def test_stats_label_cleared(self, window):
        window.stats_label.setText("something")
        window.clear_table()
        assert window.stats_label.text() == ""


# ---------------------------------------------------------------------------
# MainWindow — save_servers (no dialog — unit-level)
# ---------------------------------------------------------------------------


class TestSaveServers:
    def test_no_servers_does_not_open_dialog(self, window, qtbot):
        window.servers = []
        # If QMessageBox.warning fires and blocks, test would hang;
        # patch it to return immediately.
        with patch("v2ray_finder.gui.main_window.QMessageBox") as mb:
            window.save_servers()
            mb.warning.assert_called_once()

    def test_saves_all_servers_to_file(self, window, tmp_path):
        window.servers = ["vless://a", "vmess://b"]
        window.limit_spinbox.setValue(0)
        dest = str(tmp_path / "out.txt")
        with patch(
            "v2ray_finder.gui.main_window.QFileDialog.getSaveFileName",
            return_value=(dest, ""),
        ):
            with patch("v2ray_finder.gui.main_window.QMessageBox"):
                window.save_servers()
        lines = open(dest).read().splitlines()
        assert lines == ["vless://a", "vmess://b"]

    def test_saves_limited_servers(self, window, tmp_path):
        window.servers = ["vless://a", "vmess://b", "trojan://c"]
        window.limit_spinbox.setValue(2)
        dest = str(tmp_path / "out.txt")
        with patch(
            "v2ray_finder.gui.main_window.QFileDialog.getSaveFileName",
            return_value=(dest, ""),
        ):
            with patch("v2ray_finder.gui.main_window.QMessageBox"):
                window.save_servers()
        lines = open(dest).read().splitlines()
        assert len(lines) == 2
        window.limit_spinbox.setValue(0)  # reset

    def test_no_file_selected_does_nothing(self, window, tmp_path):
        window.servers = ["vless://a"]
        with patch(
            "v2ray_finder.gui.main_window.QFileDialog.getSaveFileName",
            return_value=("", ""),
        ):
            window.save_servers()  # must not raise


# ---------------------------------------------------------------------------
# MainWindow — copy_selected
# ---------------------------------------------------------------------------


class TestCopySelected:
    def test_no_selection_shows_info(self, window):
        window.on_fetch_finished(["vless://a"])
        window.table.clearSelection()
        with patch("v2ray_finder.gui.main_window.QMessageBox") as mb:
            window.copy_selected()
            mb.information.assert_called_once()

    def test_selected_rows_copied_to_clipboard(self, window, qapp):
        window.on_fetch_finished(["vless://a", "vmess://b"])
        window.table.selectRow(0)
        window.copy_selected()
        clipboard_text = qapp.clipboard().text()
        assert "vless://a" in clipboard_text

    def test_multiple_rows_copied(self, window, qapp):
        window.on_fetch_finished(["vless://a", "vmess://b", "trojan://c"])
        window.table.selectAll()
        window.copy_selected()
        clipboard_text = qapp.clipboard().text()
        assert "vless://a" in clipboard_text
        assert "vmess://b" in clipboard_text
        assert "trojan://c" in clipboard_text

    def test_status_label_updated(self, window):
        window.on_fetch_finished(["vless://a"])
        window.table.selectRow(0)
        window.copy_selected()
        assert "opied" in window.status_label.text()
