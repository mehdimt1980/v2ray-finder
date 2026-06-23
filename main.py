"""Mobile Android UI for v2ray-finder.

This entrypoint is intentionally self-contained for Android packaging. When the
full ``v2ray_finder`` package is available, the UI uses the real project
``Pipeline``. If Buildozer packages only ``main.pyc`` in the APK, the app falls
back to a compact mobile backend implemented in this file so the Android app can
still open and perform useful fetch / dedup / score / optional TCP checks.
"""

from __future__ import annotations

import base64
import json
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

# The project uses a src/ layout. This helps desktop/local runs. Android builds
# may not include src/, so imports below have a self-contained fallback.
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

try:  # Prefer the real project engine when it is packaged.
    from v2ray_finder import Pipeline, StopController  # type: ignore
    ENGINE_MODE = "full project engine"
except Exception:  # noqa: BLE001 - Android fallback must survive import issues.
    ENGINE_MODE = "mobile fallback engine"

    class StopController:
        """Small replacement for v2ray_finder.pipeline.StopController."""

        def __init__(self) -> None:
            self.event = threading.Event()

        def stop(self) -> None:
            self.event.set()

        def is_set(self) -> bool:
            return self.event.is_set()

    @dataclass
    class _MobileScore:
        config: str
        protocol: str
        total: float
        grade: str
        latency_ms: Optional[float] = None
        health_details: Optional[dict] = None

    class _MobileResult:
        def __init__(self, configs: list[str], scores: list[_MobileScore], stats: dict) -> None:
            self.configs = configs
            self.scores = scores
            self.stats = stats

        @property
        def top_configs(self) -> list[str]:
            return [score.config for score in self.scores]

    class Pipeline:
        """Compact Android-safe pipeline used when the real package is absent.

        It intentionally avoids optional desktop dependencies and xray probing.
        """

        DEFAULT_SOURCES = [
            "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
            "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
            "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
            "https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2",
            "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
            "https://raw.githubusercontent.com/ALIILAPRO/v2rayNG-Config/main/server.txt",
            "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/vmess.txt",
            "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/vless.txt",
            "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/trojan.txt",
            "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/shadowsocks.txt",
        ]

        CONFIG_RE = re.compile(r"\b(?:vmess|vless|trojan|ss|ssr)://[^\s\"'<>]+", re.IGNORECASE)
        PROTOCOL_WEIGHT = {"vless": 1.0, "trojan": 0.94, "vmess": 0.86, "ss": 0.72, "ssr": 0.55}

        def __init__(
            self,
            *,
            check_health: bool = False,
            timeout: float = 5.0,
            limit: Optional[int] = None,
            github_token: Optional[str] = None,
            max_total_configs: Optional[int] = None,
            **_: object,
        ) -> None:
            self.check_health = check_health
            self.timeout = timeout
            self.limit = limit or max_total_configs or 200
            self.github_token = github_token

        def run(self, stop_event=None, progress_callback=None) -> _MobileResult:
            raw: list[str] = []
            errors = 0
            total_sources = len(self.DEFAULT_SOURCES)

            for i, url in enumerate(self.DEFAULT_SOURCES, 1):
                if self._stopped(stop_event):
                    break
                self._progress(progress_callback, "fetch", i, total_sources, f"Fetching source {i}/{total_sources}")
                try:
                    text = self._fetch_url(url)
                    raw.extend(self._extract_configs(text))
                except Exception:
                    errors += 1
                if len(raw) >= self.limit * 3:
                    break

            self._progress(progress_callback, "dedup", 1, 1, "Deduplicating configs")
            unique = self._dedup(raw)[: self.limit]

            scores: list[_MobileScore] = []
            healthy = 0
            total = len(unique) or 1

            for i, config in enumerate(unique, 1):
                if self._stopped(stop_event):
                    break
                proto = self._protocol(config)
                latency_ms: Optional[float] = None
                reachable = None

                if self.check_health:
                    self._progress(progress_callback, "health", i, total, f"Checking {i}/{total}")
                    reachable, latency_ms = self._tcp_check(config)
                    if reachable:
                        healthy += 1
                    else:
                        # In health mode, keep unreachable entries but score them lower.
                        pass
                else:
                    self._progress(progress_callback, "score", i, total, f"Scoring {i}/{total}")

                score_value = self._score(proto, reachable, latency_ms, self.check_health)
                scores.append(
                    _MobileScore(
                        config=config,
                        protocol=proto,
                        total=score_value,
                        grade=self._grade(score_value),
                        latency_ms=latency_ms,
                        health_details={"reachable": reachable} if reachable is not None else None,
                    )
                )

            scores.sort(key=lambda s: (-s.total, s.latency_ms if s.latency_ms is not None else 999999, s.config))
            stats = {
                "fetched": len(raw),
                "deduped": len(unique),
                "healthy": healthy,
                "scored": len(scores),
                "errors": errors,
                "engine": ENGINE_MODE,
            }
            self._progress(progress_callback, "done", 1, 1, f"Ready: {len(scores)} configs")
            return _MobileResult(unique, scores, stats)

        def _fetch_url(self, url: str) -> str:
            import requests

            headers = {"User-Agent": "v2ray-finder-android/1.0"}
            if self.github_token and "githubusercontent.com" in url:
                headers["Authorization"] = f"Bearer {self.github_token}"
            response = requests.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response.text

        def _extract_configs(self, text: str) -> list[str]:
            found = []
            for match in self.CONFIG_RE.findall(text or ""):
                cleaned = match.strip().rstrip(".,;)]}>\"'")
                if "://" in cleaned:
                    found.append(cleaned)
            return found

        def _dedup(self, configs: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for config in configs:
                key = config.strip()
                if key and key not in seen:
                    seen.add(key)
                    out.append(key)
            return out

        def _protocol(self, config: str) -> str:
            return config.split("://", 1)[0].lower() if "://" in config else "unknown"

        def _score(self, proto: str, reachable: Optional[bool], latency_ms: Optional[float], health_mode: bool) -> float:
            base = self.PROTOCOL_WEIGHT.get(proto, 0.45)
            if not health_mode:
                return round(max(0.0, min(1.0, base * 0.85)), 3)
            if not reachable:
                return round(max(0.05, base * 0.25), 3)
            latency_component = self._latency_score(latency_ms)
            return round(max(0.0, min(1.0, base * 0.35 + latency_component * 0.65)), 3)

        def _latency_score(self, latency_ms: Optional[float]) -> float:
            if latency_ms is None:
                return 0.2
            if latency_ms <= 100:
                return 1.0
            if latency_ms <= 300:
                return 1.0 - ((latency_ms - 100) / 200) * 0.3
            if latency_ms <= 1000:
                return 0.7 - ((latency_ms - 300) / 700) * 0.5
            if latency_ms <= 3000:
                return 0.2 - ((latency_ms - 1000) / 2000) * 0.2
            return 0.0

        def _grade(self, total: float) -> str:
            if total >= 0.80:
                return "A"
            if total >= 0.60:
                return "B"
            if total >= 0.40:
                return "C"
            if total >= 0.20:
                return "D"
            return "F"

        def _tcp_check(self, config: str) -> tuple[bool, Optional[float]]:
            host, port = self._host_port(config)
            if not host or not port:
                return False, None
            start = time.perf_counter()
            try:
                with socket.create_connection((host, int(port)), timeout=self.timeout):
                    pass
                return True, (time.perf_counter() - start) * 1000
            except Exception:
                return False, None

        def _host_port(self, config: str) -> tuple[Optional[str], Optional[int]]:
            proto = self._protocol(config)
            try:
                if proto == "vmess":
                    payload = config.split("://", 1)[1].split("#", 1)[0]
                    data = self._b64_json(payload)
                    host = data.get("add") or data.get("host")
                    port = int(data.get("port")) if data.get("port") else None
                    return host, port
                if proto in {"vless", "trojan"}:
                    parsed = urlsplit(config)
                    return parsed.hostname, parsed.port
                if proto == "ss":
                    body = config.split("://", 1)[1].split("#", 1)[0]
                    if "@" not in body:
                        body = self._b64_text(body)
                    parsed = urlsplit("ss://" + body)
                    return parsed.hostname, parsed.port
                if proto == "ssr":
                    body = config.split("://", 1)[1].split("#", 1)[0]
                    decoded = self._b64_text(body)
                    parts = decoded.split(":")
                    if len(parts) >= 2:
                        return parts[0], int(parts[1])
            except Exception:
                return None, None
            return None, None

        def _b64_text(self, payload: str) -> str:
            payload = payload.strip().replace("-", "+").replace("_", "/")
            payload += "=" * (-len(payload) % 4)
            return base64.b64decode(payload).decode("utf-8", errors="ignore")

        def _b64_json(self, payload: str) -> dict:
            text = self._b64_text(payload)
            return json.loads(text)

        def _stopped(self, stop_event) -> bool:
            return bool(stop_event and stop_event.is_set())

        def _progress(self, callback, stage: str, current: int, total: int, message: str) -> None:
            if callback:
                callback(stage, current, total, message)


BG = (0.035, 0.047, 0.075, 1)
SURFACE = (0.075, 0.095, 0.145, 1)
SURFACE_2 = (0.105, 0.130, 0.195, 1)
ACCENT = (0.188, 0.529, 0.964, 1)
TEXT = (0.93, 0.96, 1.0, 1)
MUTED = (0.63, 0.70, 0.80, 1)
DANGER = (0.95, 0.27, 0.35, 1)
WARNING = (0.98, 0.69, 0.25, 1)
SUCCESS = (0.25, 0.85, 0.55, 1)


def _parse_int(value: str, default: int, minimum: int = 0, maximum: int = 5000) -> int:
    try:
        num = int(value.strip())
    except Exception:
        return default
    return max(minimum, min(maximum, num))


def _parse_float(value: str, default: float, minimum: float = 0.0, maximum: float = 120.0) -> float:
    try:
        num = float(value.strip())
    except Exception:
        return default
    return max(minimum, min(maximum, num))


class Card(BoxLayout):
    bg_color = ListProperty(SURFACE)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.padding = kwargs.get("padding", dp(14))
        self.spacing = kwargs.get("spacing", dp(8))
        with self.canvas.before:
            Color(*self.bg_color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(18)])
        self.bind(pos=self._update_rect, size=self._update_rect, bg_color=self._update_color)

    def _update_rect(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _update_color(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*self.bg_color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(18)])


class GhostButton(Button):
    def __init__(self, **kwargs):
        bg = kwargs.pop("background_color", ACCENT)
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_color = bg
        self.color = TEXT
        self.bold = True
        self.font_size = sp(14)
        self.size_hint_y = None
        self.height = dp(46)


class SmallLabel(Label):
    def __init__(self, text: str = "", color=MUTED, **kwargs):
        super().__init__(text=text, color=color, **kwargs)
        self.font_size = kwargs.get("font_size", sp(12))
        self.halign = kwargs.get("halign", "left")
        self.valign = kwargs.get("valign", "middle")
        self.bind(size=lambda *_: setattr(self, "text_size", self.size))


class StatCard(Card):
    def __init__(self, title: str, value: str = "0", **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.size_hint_y = None
        self.height = dp(72)
        self.title_label = SmallLabel(title.upper(), color=MUTED, font_size=sp(10))
        self.value_label = Label(text=value, color=TEXT, bold=True, font_size=sp(22), halign="left", valign="middle")
        self.value_label.bind(size=lambda *_: setattr(self.value_label, "text_size", self.value_label.size))
        self.add_widget(self.title_label)
        self.add_widget(self.value_label)

    def set_value(self, value: object) -> None:
        self.value_label.text = str(value)


class ResultRow(Card):
    def __init__(self, index: int, score, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.size_hint_y = None
        self.height = dp(112)
        self.bg_color = SURFACE_2
        grade = getattr(score, "grade", "?")
        total = getattr(score, "total", 0.0)
        protocol = getattr(score, "protocol", "?")
        latency = getattr(score, "latency_ms", None)
        config = getattr(score, "config", "")

        header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(28), spacing=dp(8))
        badge_color = SUCCESS if grade in ("A", "B") else WARNING if grade in ("C", "D") else DANGER
        grade_badge = Label(
            text=f"[b]{grade}[/b]",
            markup=True,
            color=(0.02, 0.03, 0.05, 1),
            size_hint_x=None,
            width=dp(38),
            font_size=sp(13),
        )
        with grade_badge.canvas.before:
            Color(*badge_color)
            grade_badge._rect = RoundedRectangle(pos=grade_badge.pos, size=grade_badge.size, radius=[dp(10)])
        grade_badge.bind(pos=lambda w, *_: setattr(w._rect, "pos", w.pos), size=lambda w, *_: setattr(w._rect, "size", w.size))

        title = Label(
            text=f"#{index}  {protocol.upper()}  •  score {total:.2f}",
            color=TEXT,
            bold=True,
            halign="left",
            valign="middle",
            font_size=sp(14),
        )
        title.bind(size=lambda *_: setattr(title, "text_size", title.size))
        latency_text = "n/a" if latency is None else f"{latency:.0f} ms"
        meta = Label(text=latency_text, color=MUTED, size_hint_x=None, width=dp(78), font_size=sp(12))
        header.add_widget(grade_badge)
        header.add_widget(title)
        header.add_widget(meta)

        cfg_label = Label(
            text=config,
            color=MUTED,
            font_size=sp(11),
            halign="left",
            valign="top",
            shorten=True,
            shorten_from="right",
        )
        cfg_label.bind(size=lambda *_: setattr(cfg_label, "text_size", cfg_label.size))
        self.add_widget(header)
        self.add_widget(cfg_label)


class V2RayFinderMobileApp(App):
    title = "V2Ray Finder"

    def build(self):
        self.stop_controller: Optional[StopController] = None
        self.worker: Optional[threading.Thread] = None
        self.latest_result = None
        self.latest_configs: list[str] = []

        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        with root.canvas.before:
            Color(*BG)
            root._rect = RoundedRectangle(pos=root.pos, size=root.size, radius=[0])
        root.bind(pos=lambda w, *_: setattr(w._rect, "pos", w.pos), size=lambda w, *_: setattr(w._rect, "size", w.size))

        header = Card(orientation="vertical", bg_color=(0.06, 0.09, 0.17, 1), size_hint_y=None, height=dp(118))
        title = Label(text="[b]V2Ray Finder[/b]", markup=True, color=TEXT, font_size=sp(28), halign="left")
        title.bind(size=lambda *_: setattr(title, "text_size", title.size))
        header.add_widget(title)
        header.add_widget(SmallLabel(f"Find, rank and export configs • {ENGINE_MODE}", color=MUTED, font_size=sp(13)))
        root.add_widget(header)

        controls = Card(orientation="vertical", bg_color=SURFACE, size_hint_y=None, height=dp(230))
        row1 = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(48))
        self.token_input = TextInput(
            hint_text="GitHub token optional",
            password=True,
            multiline=False,
            foreground_color=TEXT,
            hint_text_color=MUTED,
            background_color=(0.12, 0.15, 0.22, 1),
            cursor_color=ACCENT,
            padding=[dp(12), dp(12), dp(12), dp(12)],
        )
        row1.add_widget(self.token_input)
        controls.add_widget(row1)

        row2 = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(48))
        self.limit_input = TextInput(text="200", hint_text="Limit", multiline=False, input_filter="int", foreground_color=TEXT, hint_text_color=MUTED, background_color=(0.12, 0.15, 0.22, 1), padding=[dp(12), dp(12), dp(12), dp(12)])
        self.timeout_input = TextInput(text="5", hint_text="Timeout", multiline=False, input_filter="float", foreground_color=TEXT, hint_text_color=MUTED, background_color=(0.12, 0.15, 0.22, 1), padding=[dp(12), dp(12), dp(12), dp(12)])
        row2.add_widget(self.limit_input)
        row2.add_widget(self.timeout_input)
        controls.add_widget(row2)

        row3 = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(38))
        self.health_check = CheckBox(active=False, size_hint_x=None, width=dp(42), color=ACCENT)
        row3.add_widget(self.health_check)
        row3.add_widget(SmallLabel("TCP health check", color=TEXT, font_size=sp(13)))
        row3.add_widget(Widget())
        controls.add_widget(row3)

        btn_row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(50))
        self.start_btn = GhostButton(text="Start Scan", background_color=ACCENT)
        self.stop_btn = GhostButton(text="Stop", background_color=DANGER, disabled=True)
        self.copy_btn = GhostButton(text="Copy", background_color=SURFACE_2, disabled=True)
        self.save_btn = GhostButton(text="Save", background_color=SURFACE_2, disabled=True)
        self.start_btn.bind(on_release=lambda *_: self.start_scan())
        self.stop_btn.bind(on_release=lambda *_: self.stop_scan())
        self.copy_btn.bind(on_release=lambda *_: self.copy_results())
        self.save_btn.bind(on_release=lambda *_: self.save_results())
        btn_row.add_widget(self.start_btn)
        btn_row.add_widget(self.stop_btn)
        btn_row.add_widget(self.copy_btn)
        btn_row.add_widget(self.save_btn)
        controls.add_widget(btn_row)
        root.add_widget(controls)

        stats_grid = GridLayout(cols=4, spacing=dp(8), size_hint_y=None, height=dp(78))
        self.stat_fetched = StatCard("Fetched")
        self.stat_unique = StatCard("Unique")
        self.stat_healthy = StatCard("Healthy")
        self.stat_scored = StatCard("Scored")
        for card in (self.stat_fetched, self.stat_unique, self.stat_healthy, self.stat_scored):
            stats_grid.add_widget(card)
        root.add_widget(stats_grid)

        status_card = Card(orientation="vertical", bg_color=(0.055, 0.07, 0.105, 1), size_hint_y=None, height=dp(70))
        self.status_label = SmallLabel("Ready. Start with a low limit first on Android.", color=TEXT, font_size=sp(13))
        self.progress = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(8))
        status_card.add_widget(self.status_label)
        status_card.add_widget(self.progress)
        root.add_widget(status_card)

        self.results_layout = GridLayout(cols=1, spacing=dp(10), size_hint_y=None)
        self.results_layout.bind(minimum_height=self.results_layout.setter("height"))
        scroll = ScrollView(do_scroll_x=False)
        scroll.add_widget(self.results_layout)
        root.add_widget(scroll)
        return root

    def start_scan(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.results_layout.clear_widgets()
        self.latest_configs = []
        self.latest_result = None
        self.set_buttons(running=True)
        self.update_stats({"fetched": 0, "deduped": 0, "healthy": 0, "scored": 0})
        self.progress.value = 0
        self.status_label.text = "Starting pipeline..."
        self.stop_controller = StopController()
        limit = _parse_int(self.limit_input.text, default=200, minimum=1, maximum=5000)
        timeout = _parse_float(self.timeout_input.text, default=5.0, minimum=1.0, maximum=60.0)
        token = self.token_input.text.strip() or None
        check_health = bool(self.health_check.active)

        def progress_callback(stage: str, current: int, total: int, message: str) -> None:
            Clock.schedule_once(lambda _dt: self.on_progress(stage, current, total, message), 0)

        def run_pipeline() -> None:
            try:
                pipeline = Pipeline(
                    check_health=check_health,
                    check_http_probe=False,
                    check_google_204=False,
                    timeout=timeout,
                    limit=limit,
                    github_token=token,
                    fetch_concurrency=4,
                    health_batch_size=50,
                    max_total_configs=limit,
                )
                result = pipeline.run(
                    stop_event=self.stop_controller.event if self.stop_controller else None,
                    progress_callback=progress_callback,
                )
                Clock.schedule_once(lambda _dt: self.on_result(result), 0)
            except Exception as exc:  # noqa: BLE001
                Clock.schedule_once(lambda _dt: self.on_error(str(exc)), 0)

        self.worker = threading.Thread(target=run_pipeline, daemon=True)
        self.worker.start()

    def stop_scan(self) -> None:
        if self.stop_controller:
            self.stop_controller.stop()
        self.status_label.text = "Stopping at the next safe checkpoint..."
        self.stop_btn.disabled = True

    def on_progress(self, stage: str, current: int, total: int, message: str) -> None:
        if total > 0:
            self.progress.value = min(100, max(0, current / total * 100))
        self.status_label.text = f"{stage.upper()}: {message}"

    def on_result(self, result) -> None:
        self.latest_result = result
        self.latest_configs = result.top_configs if result.scores else result.configs
        self.update_stats(result.stats)
        self.populate_results(result)
        self.progress.value = 100
        stopped = self.stop_controller.is_set() if self.stop_controller else False
        label = "Stopped with partial results" if stopped else "Done"
        self.status_label.text = f"{label}. {len(self.latest_configs)} configs ready."
        self.set_buttons(running=False)
        has_results = bool(self.latest_configs)
        self.copy_btn.disabled = not has_results
        self.save_btn.disabled = not has_results

    def on_error(self, message: str) -> None:
        self.status_label.text = f"Error: {message}"
        self.set_buttons(running=False)

    def update_stats(self, stats: dict) -> None:
        self.stat_fetched.set_value(stats.get("fetched", 0))
        self.stat_unique.set_value(stats.get("deduped", 0))
        self.stat_healthy.set_value(stats.get("healthy", 0))
        self.stat_scored.set_value(stats.get("scored", 0))

    def populate_results(self, result) -> None:
        self.results_layout.clear_widgets()
        scores = result.scores[:100]
        if not scores:
            empty = Card(orientation="vertical", size_hint_y=None, height=dp(80))
            empty.add_widget(SmallLabel("No scored results. Try disabling health check or increasing the limit.", color=TEXT))
            self.results_layout.add_widget(empty)
            return
        for idx, score in enumerate(scores, 1):
            self.results_layout.add_widget(ResultRow(idx, score))

    def set_buttons(self, running: bool) -> None:
        self.start_btn.disabled = running
        self.stop_btn.disabled = not running
        self.copy_btn.disabled = running or not bool(self.latest_configs)
        self.save_btn.disabled = running or not bool(self.latest_configs)

    def copy_results(self) -> None:
        if not self.latest_configs:
            return
        Clipboard.copy("\n".join(self.latest_configs))
        self.status_label.text = f"Copied {len(self.latest_configs)} configs to clipboard."

    def save_results(self) -> None:
        if not self.latest_configs:
            return
        out_dir = Path(self.user_data_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "v2ray_servers.txt"
        out_file.write_text("\n".join(self.latest_configs) + "\n", encoding="utf-8")
        self.status_label.text = f"Saved {len(self.latest_configs)} configs."


if __name__ == "__main__":
    V2RayFinderMobileApp().run()
