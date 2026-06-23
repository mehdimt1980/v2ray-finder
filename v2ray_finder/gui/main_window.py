# src/v2ray_finder/gui/main_window.py
"""Main GUI window for v2ray-finder.

V1-A2: fully migrated to Pipeline + StopController.

Thread model
------------
All Pipeline work runs inside *WorkerThread* (a QThread subclass).
Communication back to the main thread is via Qt signals only — never
direct widget access from the worker.  Signals:

  progress(stage, current, total, message)  — drives QProgressBar
  result(PipelineResult)                    — table population
  error_signal(str)                         — critical dialog

Cancellation
------------
The Stop button calls StopController.stop(), which sets the threading.Event
that Pipeline.run() checks between stages and between health batches.
The worker thread is then joined (QThread.wait()) so resources are released
before the next run.
"""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..pipeline import Pipeline, PipelineResult, StopController

# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------


class WorkerThread(QThread):
    """Run Pipeline.run() in a background thread.

    Signals
    -------
    progress  — (stage: str, current: int, total: int, message: str)
    result    — (PipelineResult,)
    error_signal — (error_str: str)
    """

    progress = Signal(str, int, int, str)
    result = Signal(object)
    error_signal = Signal(str)

    def __init__(
        self,
        pipeline: Pipeline,
        stop_ctrl: StopController,
    ) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._stop_ctrl = stop_ctrl

    def run(self) -> None:
        try:
            pipe_result = self._pipeline.run(
                stop_event=self._stop_ctrl.event,
                progress_callback=self._on_progress,
            )
            self.result.emit(pipe_result)
        except Exception as exc:  # noqa: BLE001
            self.error_signal.emit(str(exc))

    def _on_progress(self, stage: str, current: int, total: int, message: str) -> None:
        self.progress.emit(stage, current, total, message)


# ---------------------------------------------------------------------------
# Pipeline options widget
# ---------------------------------------------------------------------------


class PipelineOptionsWidget(QGroupBox):
    """Collapsible group of Pipeline tuning controls."""

    def __init__(self, parent=None) -> None:
        super().__init__("Pipeline Options", parent)
        layout = QHBoxLayout()

        self.health_cb = QCheckBox("Health check")
        self.health_cb.setChecked(True)
        self.http_cb = QCheckBox("HTTP probe")
        self.google_204_cb = QCheckBox("Google 204")
        layout.addWidget(self.health_cb)
        layout.addWidget(self.http_cb)
        layout.addWidget(self.google_204_cb)
        layout.addSpacing(12)

        layout.addWidget(QLabel("Timeout:"))
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(1.0, 60.0)
        self.timeout_spin.setValue(5.0)
        self.timeout_spin.setSuffix(" s")
        self.timeout_spin.setFixedWidth(80)
        layout.addWidget(self.timeout_spin)
        layout.addSpacing(12)

        layout.addWidget(QLabel("Limit:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 10_000)
        self.limit_spin.setValue(0)
        self.limit_spin.setSpecialValueText("No limit")
        self.limit_spin.setFixedWidth(100)
        layout.addWidget(self.limit_spin)
        layout.addStretch()

        self.setLayout(layout)

    def build_pipeline(self, github_token: Optional[str] = None) -> Pipeline:
        limit = self.limit_spin.value() or None
        return Pipeline(
            check_health=self.health_cb.isChecked(),
            check_http_probe=self.http_cb.isChecked(),
            check_google_204=self.google_204_cb.isChecked(),
            timeout=self.timeout_spin.value(),
            limit=limit,
            github_token=github_token or None,
        )


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    """Main GUI window for v2ray-finder (V1-A2: Pipeline backend)."""

    # Column indices
    COL_NUM = 0
    COL_PROTO = 1
    COL_SCORE = 2
    COL_GRADE = 3
    COL_LATENCY = 4
    COL_SOURCE = 5
    COL_CONFIG = 6

    def __init__(self) -> None:
        super().__init__()
        self._result: Optional[PipelineResult] = None
        self._worker: Optional[WorkerThread] = None
        self._stop_ctrl = StopController()
        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        self.setWindowTitle("v2ray-finder")
        self.setGeometry(100, 100, 1200, 800)

        root = QWidget()
        vbox = QVBoxLayout()
        self.setCentralWidget(root)

        # --- Token row ---
        token_row = QHBoxLayout()
        token_row.addWidget(QLabel("GitHub Token:"))
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("optional — raises API rate limit")
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setMinimumWidth(280)
        token_row.addWidget(self.token_input)
        token_row.addStretch()
        vbox.addLayout(token_row)

        # --- Pipeline options ---
        self.options = PipelineOptionsWidget()
        vbox.addWidget(self.options)

        # --- Action buttons ---
        btn_row = QHBoxLayout()

        self.fetch_btn = QPushButton("🔍 Fetch Servers")
        self.fetch_btn.clicked.connect(self._on_fetch)
        btn_row.addWidget(self.fetch_btn)

        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self.stop_btn)

        self.save_btn = QPushButton("💾 Save to File")
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.setEnabled(False)
        btn_row.addWidget(self.save_btn)

        self.copy_btn = QPushButton("📋 Copy Selected")
        self.copy_btn.clicked.connect(self._on_copy)
        self.copy_btn.setEnabled(False)
        btn_row.addWidget(self.copy_btn)

        self.clear_btn = QPushButton("🗑️ Clear")
        self.clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(self.clear_btn)

        vbox.addLayout(btn_row)

        # --- Status label ---
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("padding: 6px; font-weight: bold;")
        vbox.addWidget(self.status_label)

        # --- Progress bar ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        vbox.addWidget(self.progress_bar)

        # --- Stats label ---
        self.stats_label = QLabel("")
        bold = QFont()
        bold.setBold(True)
        self.stats_label.setFont(bold)
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_label.setStyleSheet(
            "padding: 6px; background: #f0f0f0; border-radius: 4px;"
        )
        vbox.addWidget(self.stats_label)

        # --- Servers table ---
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["#", "Protocol", "Score", "Grade", "Latency (ms)", "Source", "Config"]
        )
        self.table.setColumnWidth(self.COL_NUM, 45)
        self.table.setColumnWidth(self.COL_PROTO, 80)
        self.table.setColumnWidth(self.COL_SCORE, 60)
        self.table.setColumnWidth(self.COL_GRADE, 55)
        self.table.setColumnWidth(self.COL_LATENCY, 95)
        self.table.setColumnWidth(self.COL_SOURCE, 180)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        vbox.addWidget(self.table)

        # --- Failed sources box (hidden until there are errors) ---
        self.errors_group = QGroupBox("Failed Sources")
        self.errors_group.setVisible(False)
        errors_vbox = QVBoxLayout()
        self.errors_text = QTextEdit()
        self.errors_text.setReadOnly(True)
        self.errors_text.setMaximumHeight(110)
        errors_vbox.addWidget(self.errors_text)
        self.errors_group.setLayout(errors_vbox)
        vbox.addWidget(self.errors_group)

        root.setLayout(vbox)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_fetch(self) -> None:
        if self._worker and self._worker.isRunning():
            return

        self._stop_ctrl.reset()
        token = self.token_input.text().strip() or None
        pipeline = self.options.build_pipeline(github_token=token)

        self._worker = WorkerThread(pipeline=pipeline, stop_ctrl=self._stop_ctrl)
        self._worker.progress.connect(self._on_progress)
        self._worker.result.connect(self._on_result)
        self._worker.error_signal.connect(self._on_error)
        self._worker.finished.connect(self._on_worker_done)
        self._worker.start()

        self.fetch_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.status_label.setText("🔄 Starting pipeline…")
        self.errors_group.setVisible(False)

    def _on_stop(self) -> None:
        self._stop_ctrl.stop()
        self.status_label.setText("⏹ Stopping…")
        self.stop_btn.setEnabled(False)

    def _on_save(self) -> None:
        if not self._result:
            QMessageBox.warning(self, "No Data", "Run a fetch first.")
            return
        configs = self._result.top_configs
        if not configs:
            QMessageBox.warning(self, "No Data", "No scored configs to save.")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save V2Ray Servers",
            "v2ray_servers.txt",
            "Text Files (*.txt);;All Files (*)",
        )
        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(configs) + "\n")
                QMessageBox.information(
                    self,
                    "Saved",
                    f"Saved {len(configs)} configs to:\n{filename}",
                )
                self.status_label.setText(f"💾 Saved {len(configs)} configs")
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Save Error", str(exc))

    def _on_copy(self) -> None:
        selected_rows = {item.row() for item in self.table.selectedItems()}
        configs = []
        for row in sorted(selected_rows):
            item = self.table.item(row, self.COL_CONFIG)
            if item:
                configs.append(item.text())
        if not configs:
            QMessageBox.information(
                self, "Nothing Selected", "Select rows in the table first."
            )
            return
        QApplication.clipboard().setText("\n".join(configs))
        self.status_label.setText(f"📋 Copied {len(configs)} configs")

    def _on_clear(self) -> None:
        self.table.setRowCount(0)
        self.stats_label.setText("")
        self.errors_group.setVisible(False)
        self._result = None
        self.status_label.setText("🗑️ Cleared")
        self.save_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Worker signal handlers (main-thread only)
    # ------------------------------------------------------------------

    def _on_progress(self, stage: str, current: int, total: int, message: str) -> None:
        self.status_label.setText(message)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        else:
            self.progress_bar.setRange(0, 0)  # indeterminate

    def _on_result(self, pipe_result: PipelineResult) -> None:
        self._result = pipe_result
        self._populate_table(pipe_result)
        self._populate_stats(pipe_result)
        self._populate_errors(pipe_result)

    def _on_error(self, error_str: str) -> None:
        self.status_label.setText(f"❌ Error: {error_str}")
        QMessageBox.critical(self, "Pipeline Error", f"Pipeline failed:\n{error_str}")

    def _on_worker_done(self) -> None:
        self.fetch_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        has_results = bool(self._result and self._result.scores)
        self.save_btn.setEnabled(has_results)
        self.copy_btn.setEnabled(has_results)
        if self._stop_ctrl.is_set():
            self.status_label.setText("⚠️ Stopped by user (partial results)")
        elif has_results:
            n = len(self._result.scores)
            self.status_label.setText(f"✅ Done — {n} servers scored")

    # ------------------------------------------------------------------
    # Table / stats population
    # ------------------------------------------------------------------

    def _populate_table(self, pipe_result: PipelineResult) -> None:
        scores = pipe_result.scores
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(scores))

        for i, s in enumerate(scores):
            latency = ""
            if s.latency_ms is not None:
                latency = f"{s.latency_ms:.0f}"

            src_url = getattr(s, "source_url", "") or ""
            # Shorten source URL for display
            if src_url and len(src_url) > 40:
                src_display = "..." + src_url[-37:]
            else:
                src_display = src_url

            def _cell(text: str) -> QTableWidgetItem:
                return QTableWidgetItem(str(text))

            self.table.setItem(i, self.COL_NUM, _cell(i + 1))
            self.table.setItem(i, self.COL_PROTO, _cell(s.protocol))
            self.table.setItem(i, self.COL_SCORE, _cell(f"{s.total:.1f}"))
            self.table.setItem(i, self.COL_GRADE, _cell(s.grade))
            self.table.setItem(i, self.COL_LATENCY, _cell(latency))
            self.table.setItem(i, self.COL_SOURCE, _cell(src_display))
            self.table.setItem(i, self.COL_CONFIG, _cell(s.config))

        self.table.setSortingEnabled(True)

    def _populate_stats(self, pipe_result: PipelineResult) -> None:
        st = pipe_result.stats
        parts = [
            f"Fetched: {st.get('fetched', 0)}",
            f"Deduped: {st.get('deduped', 0)}",
            f"Healthy: {st.get('healthy', 0)}",
            f"Scored: {st.get('scored', 0)}",
        ]
        hits = st.get("cache_hits", 0)
        if hits:
            parts.append(f"Cache hits: {hits}")
        self.stats_label.setText("  |  ".join(parts))

    def _populate_errors(self, pipe_result: PipelineResult) -> None:
        msgs = pipe_result.failed_source_messages
        if not msgs:
            self.errors_group.setVisible(False)
            return
        lines = [f"{url}\n  └ {msg}" for url, msg in msgs.items()]
        self.errors_text.setPlainText("\n".join(lines))
        self.errors_group.setTitle(f"Failed Sources ({len(msgs)})")
        self.errors_group.setVisible(True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def launch() -> None:
    """Launch the GUI application."""
    app = QApplication(sys.argv)
    app.setApplicationName("v2ray-finder")
    app.setApplicationVersion("0.7.0")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    launch()
