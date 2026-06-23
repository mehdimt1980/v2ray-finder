"""Rich CLI interface for v2ray-finder — Pipeline edition (V2-P1).

All fetch / health / score work is delegated to :class:`~pipeline.Pipeline`.
Progress is driven by the ``progress_callback`` protocol::

    callback(stage: str, current: int, total: int, message: str) -> None

where ``stage`` is one of ``"fetch"``, ``"health"``, ``"score"``.

Non-interactive mode
---------------------
::

    v2ray-finder-rich -o servers.txt          # quick fetch + save
    v2ray-finder-rich -o servers.txt -c       # with health checks
    v2ray-finder-rich --stats-only            # stats only, no file
    v2ray-finder-rich --cache                 # enable source caching
    v2ray-finder-rich --cache-ttl 1800        # 30-min cache TTL

Interactive mode (default when -o / --stats-only absent)
---------------------------------------------------------
::

    v2ray-finder-rich                         # interactive TUI
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from typing import Any, Dict, List, Optional

try:
    from rich import box
    from rich.console import Console
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TaskID,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.prompt import Confirm, IntPrompt, Prompt
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from .pipeline import Pipeline, PipelineResult, StopController

# ---------------------------------------------------------------------------
# Console singleton
# ---------------------------------------------------------------------------

console = Console() if RICH_AVAILABLE else None  # type: ignore[assignment]


def _print(msg: str, markup: bool = True) -> None:
    """Print via Rich console when available, else plain print."""
    if RICH_AVAILABLE and console is not None:
        console.print(msg, markup=markup)
    else:
        import re

        plain = re.sub(r"\[/?[^\]]+]", "", msg)
        print(plain)


# ---------------------------------------------------------------------------
# Global stop controller (module-level so SIGINT handler can reach it)
# ---------------------------------------------------------------------------

_stop_ctrl: Optional[StopController] = None


def _signal_handler(signum: int, frame: Any) -> None:  # noqa: ANN001
    """SIGINT → stop the active pipeline gracefully."""
    if _stop_ctrl is not None:
        _stop_ctrl.stop()
    raise KeyboardInterrupt


# ---------------------------------------------------------------------------
# Rich progress builder
# ---------------------------------------------------------------------------


class PipelineProgress:
    """Maps pipeline ``progress_callback`` events onto Rich Progress bars.

    Three named tasks are pre-created (one per stage).  Each ``__call__``
    updates the matching task so the bars advance live.

    When Rich is not installed the callback is a no-op and all output falls
    back to plain ``print()``.
    """

    def __init__(self) -> None:
        if not RICH_AVAILABLE:
            self._progress = None
            self._tasks: Dict[str, Any] = {}
            return

        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        )
        self._tasks: Dict[str, TaskID] = {}

    # context manager
    def __enter__(self) -> "PipelineProgress":
        if self._progress is not None:
            self._progress.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._progress is not None:
            self._progress.__exit__(*args)

    # callback — called by Pipeline.run()
    def __call__(
        self,
        stage: str,
        current: int,
        total: int,
        message: str,
    ) -> None:
        if self._progress is None:
            # no Rich — just print stage transitions
            if current == 0:
                print(f"[{stage}] {message}")
            return

        label_map = {
            "fetch": "[cyan]Fetching sources[/cyan]",
            "health": "[yellow]Health checks[/yellow]",
            "score": "[green]Scoring[/green]",
        }
        label = label_map.get(stage, stage)

        if stage not in self._tasks:
            t = self._progress.add_task(
                label,
                total=max(total, 1),
            )
            self._tasks[stage] = t
        else:
            t = self._tasks[stage]
            self._progress.update(t, total=max(total, 1))

        self._progress.update(t, completed=current, description=f"{label} — {message}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def print_welcome() -> None:
    if not RICH_AVAILABLE:
        print("=== v2ray-finder (Rich Edition) ===")
        return
    console.print(
        Markdown("# v2ray-finder \u2728\n**Fetch V2Ray servers from curated sources**")
    )
    console.print(Panel("\u2764\ufe0f for freedom", style="bold cyan", box=box.ROUNDED))


def _configs_from_result(result: PipelineResult, limit: int = 0) -> List[str]:
    """Return ordered config strings from a PipelineResult."""
    configs = result.top_configs if result.scores else result.configs
    if limit and limit > 0:
        configs = configs[:limit]
    return configs


def show_stats(
    configs: List[str],
    result: Optional[PipelineResult] = None,
    show_health: bool = False,
) -> None:
    """Display statistics using Rich tables (or plain text as fallback)."""
    if not configs:
        _print("[yellow]! No servers found[/yellow]")
        return

    protocols: Dict[str, int] = {}
    for cfg in configs:
        proto = cfg.split("://")[0].lower() if "://" in cfg else "unknown"
        protocols[proto] = protocols.get(proto, 0) + 1

    total = len(configs)
    _print(f"\n[bold]Total servers: {total}[/bold]")

    if not RICH_AVAILABLE:
        for proto, count in sorted(protocols.items(), key=lambda x: x[1], reverse=True):
            print(f"  {proto}: {count} ({100 * count / total:.1f}%)")
        return

    table = Table(
        title=f"\U0001f4ca Statistics ({total} servers)",
        box=box.ROUNDED,
    )
    table.add_column("Protocol", style="cyan", no_wrap=True)
    table.add_column("Count", justify="right", style="green bold")
    table.add_column("Percent", justify="right", style="magenta")

    for proto, count in sorted(protocols.items(), key=lambda x: x[1], reverse=True):
        table.add_row(proto, str(count), f"{100 * count / total:.1f}%")
    console.print(table)

    # Pipeline stats
    if result and result.stats:
        st = result.stats
        stat_rows = [
            ("fetched", "Raw configs fetched"),
            ("deduped", "After dedup"),
            ("healthy", "Passed health check"),
            ("scored", "Scored"),
            ("dropped_per_source", "Dropped (per-source cap)"),
            ("dropped_global", "Dropped (global cap)"),
            ("cache_hits", "Cache hits"),
            ("cache_misses", "Cache misses"),
        ]
        rows = [(label, st[key]) for key, label in stat_rows if st.get(key)]
        if rows:
            st_table = Table(title="Pipeline Stats", box=box.SIMPLE)
            st_table.add_column("Metric", style="cyan")
            st_table.add_column("Value", justify="right", style="bold")
            for label, val in rows:
                st_table.add_row(label, str(val))
            console.print(st_table)

    # Score summary
    if result and result.scores:
        score_table = Table(title="Top 5 Servers", box=box.SIMPLE)
        score_table.add_column("#", style="dim", width=3)
        score_table.add_column("Protocol", style="cyan")
        score_table.add_column("Score", justify="right", style="green bold")
        score_table.add_column("Grade", justify="center")
        score_table.add_column("Config", style="dim", no_wrap=True)
        for i, score in enumerate(result.scores[:5], 1):
            grade_color = {
                "S": "green bold",
                "A": "green",
                "B": "yellow",
                "C": "yellow",
                "D": "red",
                "F": "red dim",
            }.get(getattr(score, "grade", "F"), "dim")
            score_table.add_row(
                str(i),
                score.protocol,
                f"{score.total:.1f}",
                f"[{grade_color}]{getattr(score, 'grade', '?')}[/{grade_color}]",
                (
                    score.config[:60] + "\u2026"
                    if len(score.config) > 60
                    else score.config
                ),
            )
        console.print(score_table)


def save_results(configs: List[str], filename: str, partial: bool = False) -> None:
    """Save config strings to *filename* with a Rich progress bar."""
    if not configs:
        _print("[yellow]! No servers to save[/yellow]")
        return

    label = "partial results" if partial else "results"
    if not RICH_AVAILABLE:
        with open(filename, "w", encoding="utf-8") as fh:
            for c in configs:
                fh.write(f"{c}\n")
        print(f"Saved {len(configs)} {label} to {filename}")
        return

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as bar:
        task = bar.add_task(f"[cyan]Saving {label}…[/cyan]", total=len(configs))
        with open(filename, "w", encoding="utf-8") as fh:
            for cfg in configs:
                fh.write(f"{cfg}\n")
                bar.advance(task)

    _print(
        f"[green]\u2713[/green] Saved [bold]{len(configs)}[/bold] "
        f"{label} to [bold cyan]{filename}[/bold cyan]"
    )


# ---------------------------------------------------------------------------
# Core run helper
# ---------------------------------------------------------------------------


def _run_pipeline(
    pipeline: Pipeline,
    stop_ctrl: StopController,
    output: Optional[str],
    limit: int,
    stats_only: bool,
) -> int:
    """Execute pipeline with Rich progress bars.  Return exit code."""
    result: Optional[PipelineResult] = None

    with PipelineProgress() as prog:
        try:
            result = pipeline.run(
                stop_event=stop_ctrl.event,
                progress_callback=prog,
            )
        except KeyboardInterrupt:
            stop_ctrl.stop()

    if result is None:
        result = PipelineResult()

    configs = _configs_from_result(result, limit=limit)

    if stop_ctrl.is_set():
        _print(
            "\n[yellow]\u26a0[/yellow] [bold]Stopped by user — partial results[/bold]"
        )
        if configs and output:
            save_results(configs, output, partial=True)
        if configs:
            show_stats(configs, result=result)
        return 130

    if not configs:
        _print("[yellow]! No servers found[/yellow]")
        return 1

    show_stats(configs, result=result)

    if output:
        save_results(configs, output)

    return 0


# ---------------------------------------------------------------------------
# Interactive TUI
# ---------------------------------------------------------------------------


def interactive_mode(
    github_token: Optional[str] = None,
    cache_enabled: bool = False,
    cache_ttl: int = 3600,
) -> None:
    """Rich interactive TUI backed by Pipeline."""
    if not RICH_AVAILABLE:
        _print("[red]Rich is not installed. Run: pip install rich[/red]")
        sys.exit(1)

    print_welcome()
    console.print(
        "[dim]\U0001f4a1 Ctrl+C at any time to stop and show partial results[/dim]\n"
    )

    cached_result: Optional[PipelineResult] = None

    while True:
        console.print("\n[bold cyan]Options:[/bold cyan]")
        console.print("[cyan]1.[/] Quick fetch (no health check)")
        console.print("[cyan]2.[/] Fetch + health check (TCP)")
        console.print("[cyan]3.[/] Show statistics")
        console.print("[cyan]4.[/] Save to file")
        console.print("[cyan]5.[/] Exit")

        try:
            choice = Prompt.ask("\nSelect option", choices=["1", "2", "3", "4", "5"])
        except KeyboardInterrupt:
            console.print("\n\n[bold cyan]\U0001f44b Goodbye![/bold cyan]")
            break

        if choice == "5":
            console.print("\n[bold cyan]\U0001f44b Goodbye![/bold cyan]")
            break

        elif choice in ("1", "2"):
            check_health = choice == "2"
            global _stop_ctrl
            stop = StopController()
            _stop_ctrl = stop

            pipeline = Pipeline(
                check_health=check_health,
                github_token=github_token,
                cache_enabled=cache_enabled,
                cache_ttl=cache_ttl,
            )

            result: Optional[PipelineResult] = None
            with PipelineProgress() as prog:
                try:
                    result = pipeline.run(
                        stop_event=stop.event,
                        progress_callback=prog,
                    )
                except KeyboardInterrupt:
                    stop.stop()

            if result is not None:
                cached_result = result
                configs = _configs_from_result(result)
                label = "partial" if stop.is_set() else "total"
                _print(
                    f"\n[green]\u2713[/green] Found [bold]{len(configs)}[/bold] {label} servers"
                )
                if stop.is_set() and configs:
                    save_results(configs, "v2ray_servers_partial.txt", partial=True)

        elif choice == "3":
            if cached_result is None:
                _print("[yellow]! No results yet. Run fetch first.[/yellow]")
            else:
                show_stats(_configs_from_result(cached_result), result=cached_result)

        elif choice == "4":
            if cached_result is None:
                _print("[yellow]! No results yet. Run fetch first.[/yellow]")
            else:
                filename = Prompt.ask(
                    "\U0001f4c1 Filename", default="v2ray_servers.txt"
                )
                lim = IntPrompt.ask("\U0001f522 Limit (0 = all)", default=0)
                save_results(_configs_from_result(cached_result, limit=lim), filename)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Rich CLI entry point (V2-P1)."""
    global _stop_ctrl

    parser = argparse.ArgumentParser(
        description="v2ray-finder (Rich CLI — Pipeline edition)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  v2ray-finder-rich                      # interactive TUI
  v2ray-finder-rich -o servers.txt       # quick fetch + save
  v2ray-finder-rich -c -o servers.txt    # health check + save
  v2ray-finder-rich --stats-only         # stats only
  v2ray-finder-rich --cache              # enable source caching
  v2ray-finder-rich --cache-ttl 1800     # 30-min cache TTL
        """,
    )
    parser.add_argument("-o", "--output", help="output filename")
    parser.add_argument(
        "-l", "--limit", type=int, default=0, help="limit number of configs (0 = all)"
    )
    parser.add_argument("-t", "--token", help="GitHub token (prefer GITHUB_TOKEN env)")
    parser.add_argument(
        "-c", "--check-health", action="store_true", help="enable TCP health checks"
    )
    parser.add_argument(
        "--check-http", action="store_true", help="enable HTTP probe (Layer 2)"
    )
    parser.add_argument(
        "--check-google-204",
        action="store_true",
        help="enable Google-204 xray probe (Layer 3)",
    )
    parser.add_argument(
        "--min-quality", type=float, default=0.0, help="minimum quality score (0–100)"
    )
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="per-server health-check timeout (s)"
    )
    parser.add_argument(
        "--fetch-timeout", type=int, default=15, help="source fetch HTTP timeout (s)"
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="print stats then exit (no file written)",
    )
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="force interactive TUI"
    )
    parser.add_argument(
        "--cache", action="store_true", help="enable TTL source caching"
    )
    parser.add_argument(
        "--cache-backend",
        default="memory",
        choices=["memory", "disk"],
        help="cache backend (default: memory)",
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=3600,
        help="cache TTL in seconds (default: 3600)",
    )
    parser.add_argument("--cache-dir", default=None, help="disk cache directory")
    args = parser.parse_args()

    # Token resolution
    token: Optional[str] = args.token or os.environ.get("GITHUB_TOKEN")
    if args.token:
        _print("[red]WARNING:[/red] Passing tokens via CLI is insecure!")

    # Register SIGINT handler
    signal.signal(signal.SIGINT, _signal_handler)

    # Interactive mode
    if args.interactive or (not args.output and not args.stats_only):
        interactive_mode(
            github_token=token,
            cache_enabled=args.cache,
            cache_ttl=args.cache_ttl,
        )
        return

    # Non-interactive mode
    print_welcome()

    stop = StopController()
    _stop_ctrl = stop

    pipeline = Pipeline(
        check_health=args.check_health,
        check_http_probe=args.check_http,
        check_google_204=args.check_google_204,
        min_quality_score=args.min_quality,
        timeout=args.timeout,
        fetch_timeout=args.fetch_timeout,
        limit=args.limit or None,
        github_token=token,
        cache_enabled=args.cache,
        cache_backend=args.cache_backend,
        cache_ttl=args.cache_ttl,
        cache_dir=args.cache_dir,
    )

    code = _run_pipeline(
        pipeline=pipeline,
        stop_ctrl=stop,
        output=args.output,
        limit=args.limit,
        stats_only=args.stats_only,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
