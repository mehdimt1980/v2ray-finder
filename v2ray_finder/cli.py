"""Command-line interface for v2ray-finder.

Both the non-interactive path (``-o`` / ``--stats-only``, V1-A1) and the
interactive menu (V1-A2) are wired through :class:`~pipeline.Pipeline`.
:class:`~core.V2RayServerFinder` is no longer imported here.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from datetime import datetime
from getpass import getpass
from typing import Any, Dict, List, Optional

from .pipeline import Pipeline, PipelineResult
from .pipeline import StopController as PipelineStopController

# ---------------------------------------------------------------------------
# Helpers shared between interactive and non-interactive paths
# ---------------------------------------------------------------------------


def print_stats(
    servers: List,
    show_health: bool = False,
    show_xray: bool = False,
    pipeline_stats: Optional[Dict[str, Any]] = None,
) -> None:
    """Print statistics about fetched servers."""
    if not servers:
        print("No servers found.")
        return

    protocols: dict = {}
    for server in servers:
        if isinstance(server, dict):
            proto = server.get("protocol", "unknown")
        else:
            proto = server.split("://")[0] if "://" in server else "unknown"
        protocols[proto] = protocols.get(proto, 0) + 1

    print(f"\nTotal servers: {len(servers)}")
    print("\nBy protocol:")
    for proto, count in sorted(protocols.items(), key=lambda x: x[1], reverse=True):
        print(f"  {proto}: {count}")

    if pipeline_stats:
        print("\nPipeline stats:")
        for k, v in pipeline_stats.items():
            if v:  # skip zero counters
                print(f"  {k}: {v}")

    if show_health and servers and isinstance(servers[0], dict):
        healthy = sum(1 for s in servers if s.get("health_status") == "healthy")
        degraded = sum(1 for s in servers if s.get("health_status") == "degraded")
        unreachable = sum(1 for s in servers if s.get("health_status") == "unreachable")
        invalid = sum(1 for s in servers if s.get("health_status") == "invalid")
        print("\nHealth status:")
        print(f"  Healthy:     {healthy}")
        print(f"  Degraded:    {degraded}")
        print(f"  Unreachable: {unreachable}")
        print(f"  Invalid:     {invalid}")
        if healthy:
            avg_quality = (
                sum(
                    s.get("quality_score", 0)
                    for s in servers
                    if s.get("health_status") == "healthy"
                )
                / healthy
            )
            avg_latency = (
                sum(
                    s.get("latency_ms", 0)
                    for s in servers
                    if s.get("health_status") == "healthy"
                )
                / healthy
            )
            print(f"\nAverage quality (healthy): {avg_quality:.1f}/100")
            print(f"Average latency (healthy): {avg_latency:.1f}ms")

    if show_xray and servers and isinstance(servers[0], dict):
        reachable = sum(1 for s in servers if s.get("reachable"))
        g204 = sum(1 for s in servers if s.get("google_204_ok"))
        print("\nxray real-connectivity results:")
        print(f"  Reachable (proxy): {reachable}/{len(servers)}")
        print(f"  Google 204 OK:     {g204}/{len(servers)}")
        if reachable:
            avg_lat = (
                sum(s.get("latency_ms") or 0 for s in servers if s.get("reachable"))
                / reachable
            )
            print(f"  Avg real latency:  {avg_lat:.1f}ms")


def prompt_for_token() -> Optional[str]:
    """Prompt user for GitHub token via masked input."""
    print("\n=== GitHub Token Setup ===")
    print("A GitHub token increases rate limits from 60 to 5000 requests/hour.")
    print("Your token will NOT be stored and is only used for this session.\n")
    use_token = input("Do you want to provide a GitHub token? (y/n): ").strip().lower()
    if use_token == "y":
        print("\nPaste your GitHub token (input will be hidden):")
        token = getpass("Token: ").strip()
        if token:
            print("[\u2713] Token received\n")
            return token
        print("[!] No token provided, continuing without authentication\n")
        return None
    print("[i] Continuing without authentication\n")
    return None


def save_results(configs: List[str], filename: str, *, partial: bool = False) -> None:
    """Write config strings to *filename*."""
    if not configs:
        print("No servers to save.")
        return
    label = "partial " if partial else ""
    try:
        with open(filename, "w", encoding="utf-8") as fh:
            for cfg in configs:
                fh.write(f"{cfg}\n")
        print(f"\n[\u2713] Saved {len(configs)} {label}servers to {filename}")
        if partial:
            print("    You can resume or use these servers.\n")
    except OSError as exc:
        print(f"\n[!] Failed to save results: {exc}\n")


def _configs_from_result(result: PipelineResult) -> List[str]:
    """Return the best available config list from a PipelineResult."""
    if result.scores:
        return result.top_configs
    return result.configs


def _run_pipeline_interactive(
    *,
    check_health: bool = False,
    check_google_204: bool = False,
    timeout: float = 5.0,
    min_quality_score: float = 0.0,
    limit: Optional[int] = None,
    binary_path: Optional[str] = None,
    token: Optional[str] = None,
) -> PipelineResult:
    """Build and run a :class:`~pipeline.Pipeline`, honouring Ctrl+C.

    Returns the :class:`~pipeline.PipelineResult` (possibly partial if the
    user pressed Ctrl+C).
    """
    stop_ctrl = PipelineStopController()
    orig_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda _s, _f: stop_ctrl.stop())
    print("(Press Ctrl+C to stop and save partial results)")
    try:
        pipeline = Pipeline(
            check_health=check_health,
            check_http_probe=False,
            check_google_204=check_google_204,
            timeout=timeout,
            min_quality_score=min_quality_score,
            limit=limit,
            binary_path=binary_path,
            github_token=token,
        )
        return pipeline.run(stop_event=stop_ctrl.event)
    finally:
        signal.signal(signal.SIGINT, orig_sigint)


# ---------------------------------------------------------------------------
# Interactive menu (V1-A2 — now uses Pipeline)
# ---------------------------------------------------------------------------


def interactive_menu(token: Optional[str]) -> None:
    """Display interactive terminal menu, backed by :class:`~pipeline.Pipeline`."""
    while True:
        print("\n=== V2Ray Server Finder ===")
        print("1. Fetch from known sources")
        print("2. Fetch with health checking (TCP)")
        print("3. Fetch + health + real xray check")
        print("4. Save to file")
        print("5. Show statistics only")
        print("0. Exit")

        try:
            choice = input("\nSelect option: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nGoodbye!")
            break

        if choice == "0":
            print("Goodbye!")
            break

        # ---- 1: Fetch only ----
        elif choice == "1":
            print("\nFetching from known sources...")
            result = _run_pipeline_interactive(token=token)
            configs = _configs_from_result(result)
            if result.stats.get("dropped_per_source") or result.stats.get(
                "dropped_global"
            ):
                print(
                    f"[!] Caps applied — "
                    f"dropped {result.stats.get('dropped_per_source', 0)} per-source, "
                    f"{result.stats.get('dropped_global', 0)} globally."
                )
            print_stats(
                [{"config": c} for c in configs],
                pipeline_stats=result.stats,
            )

        # ---- 2: Health check ----
        elif choice == "2":
            try:
                min_q_str = input("Min quality score (0-100, default 0): ").strip()
            except (KeyboardInterrupt, EOFError):
                continue
            min_q = float(min_q_str) if min_q_str else 0.0
            print("\nFetching and checking server health (TCP)...")
            result = _run_pipeline_interactive(
                check_health=True,
                min_quality_score=min_q,
                token=token,
            )
            configs = _configs_from_result(result)
            print_stats(
                result.health_dicts or [{"config": c} for c in configs],
                show_health=True,
                pipeline_stats=result.stats,
            )
            if result.scores:
                try:
                    show_top = input("\nShow top 10 by score? (y/n): ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    show_top = "n"
                if show_top == "y":
                    print("\nTop 10 servers:")
                    for i, score in enumerate(result.scores[:10], 1):
                        print(
                            f"{i:2d}. [{score.protocol:8s}] "
                            f"Grade: {score.grade} | "
                            f"Latency: {score.latency_ms or 0:6.1f}ms | "
                            f"{score.config[:60]}"
                        )

        # ---- 3: xray real check ----
        elif choice == "3":
            try:
                limit_str = input("Limit servers to check (0 for all): ").strip()
                xray_bin = (
                    input("xray binary path (leave blank for auto): ").strip() or None
                )
            except (KeyboardInterrupt, EOFError):
                continue
            limit = int(limit_str) if limit_str and limit_str != "0" else None
            print("\nFetching + health + xray real-connectivity checks...")
            print("(Requires xray binary; may take several minutes)")
            result = _run_pipeline_interactive(
                check_health=True,
                check_google_204=True,
                limit=limit,
                binary_path=xray_bin,
                token=token,
            )
            configs = _configs_from_result(result)
            print_stats(
                result.health_dicts or [{"config": c} for c in configs],
                show_health=True,
                show_xray=True,
                pipeline_stats=result.stats,
            )

        # ---- 4: Save to file ----
        elif choice == "4":
            try:
                filename = (
                    input("Filename (default: v2ray_servers.txt): ").strip()
                    or "v2ray_servers.txt"
                )
                check_health = input("Check health? (y/n): ").strip().lower() == "y"
                limit_str = input("Limit (0 for all): ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n[!] Cancelled")
                continue
            limit = int(limit_str) if limit_str and limit_str != "0" else None
            print(f"\nSaving to {filename}...")
            result = _run_pipeline_interactive(
                check_health=check_health,
                limit=limit,
                token=token,
            )
            configs = _configs_from_result(result)
            save_results(configs, filename, partial=False)
            print_stats(
                [{"config": c} for c in configs],
                show_health=check_health,
                pipeline_stats=result.stats,
            )

        # ---- 5: Stats only ----
        elif choice == "5":
            try:
                check_health = input("Check health? (y/n): ").strip().lower() == "y"
            except (KeyboardInterrupt, EOFError):
                continue
            print("\nFetching servers for statistics...")
            result = _run_pipeline_interactive(
                check_health=check_health,
                token=token,
            )
            configs = _configs_from_result(result)
            print_stats(
                result.health_dicts or [{"config": c} for c in configs],
                show_health=check_health,
                pipeline_stats=result.stats,
            )

        else:
            print("Invalid option. Please try again.")


# ---------------------------------------------------------------------------
# Non-interactive pipeline runner (V1-A1)
# ---------------------------------------------------------------------------


def _run_pipeline(
    args: argparse.Namespace,
    token: Optional[str],
) -> int:
    """Execute the non-interactive path via :class:`~pipeline.Pipeline`.

    Returns the process exit code (0 = success, 1 = error, 130 = stopped).
    """
    stop_ctrl = PipelineStopController()
    orig_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda _s, _f: stop_ctrl.stop())

    if not args.quiet:
        action = "known sources"
        health_note = " with health checking" if args.check_health else ""
        xray_note = " with xray real-check" if args.xray_check else ""
        print(f"Fetching servers from {action}{health_note}{xray_note}...")
        print("[i] Press Ctrl+C at any time to stop and save partial results\n")

    pipeline = Pipeline(
        check_health=args.check_health or args.xray_check,
        check_http_probe=False,
        check_google_204=args.xray_check,
        timeout=args.health_timeout,
        min_quality_score=args.min_quality,
        limit=args.limit,
        binary_path=getattr(args, "xray_binary", None),
        github_token=token,
    )

    result = pipeline.run(stop_event=stop_ctrl.event)
    signal.signal(signal.SIGINT, orig_sigint)

    if stop_ctrl.is_set():
        print("\n[!] Operation stopped by user")
        out_file = args.output if args.output else "v2ray_servers_partial.txt"
        save_results(_configs_from_result(result), out_file, partial=True)
        print_stats(
            result.health_dicts or [{"config": c} for c in result.configs],
            show_health=args.check_health,
            show_xray=args.xray_check,
            pipeline_stats=result.stats,
        )
        return 130

    output_configs = _configs_from_result(result)
    if args.limit:
        output_configs = output_configs[: args.limit]

    if args.stats_only:
        print_stats(
            result.health_dicts or [{"config": c} for c in output_configs],
            show_health=args.check_health,
            show_xray=args.xray_check,
            pipeline_stats=result.stats,
        )
        return 0

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                for cfg in output_configs:
                    fh.write(f"{cfg}\n")
        except OSError as exc:
            print(f"\nFailed to write {args.output}: {exc}", file=sys.stderr)
            return 1
        if not args.quiet:
            print(f"\n[\u2713] Saved {len(output_configs)} servers to {args.output}")
            if result.stats:
                print(
                    f"    (fetched {result.stats.get('fetched', '?')}, "
                    f"deduped {result.stats.get('deduped', '?')}, "
                    f"healthy {result.stats.get('healthy', '?')})"
                )

    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch and aggregate V2Ray server configs from GitHub",
        epilog="For security, use GITHUB_TOKEN environment variable instead of -t flag.",
    )
    parser.add_argument(
        "-t",
        "--token",
        help="GitHub token (DEPRECATED: use GITHUB_TOKEN env var instead)",
    )
    parser.add_argument(
        "--prompt-token",
        action="store_true",
        help="Prompt for GitHub token interactively (secure input)",
    )
    parser.add_argument("-o", "--output", help="Output filename for saving servers")
    parser.add_argument("-l", "--limit", type=int, help="Limit number of servers")
    parser.add_argument(
        "--stats-only", action="store_true", help="Only show statistics"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Minimal output")
    parser.add_argument(
        "-c",
        "--check-health",
        action="store_true",
        help="Check server health (TCP connectivity and latency)",
    )
    parser.add_argument(
        "--min-quality",
        type=float,
        default=0.0,
        help="Minimum quality score (0-100, default: 0)",
    )
    parser.add_argument(
        "--health-timeout",
        type=float,
        default=5.0,
        help="Health check timeout in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--xray-check",
        action="store_true",
        help="Run real connectivity check via xray proxy (ground-truth)",
    )
    parser.add_argument(
        "--xray-binary",
        help="Path to xray binary (auto-downloaded if not found)",
    )
    parser.add_argument(
        "--xray-no-download",
        action="store_true",
        help="Disable automatic xray binary download",
    )
    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Main CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    # --- Token resolution ---
    token: Optional[str] = None
    if args.token:
        token = args.token
        print(
            "WARNING: Passing tokens via command line is insecure!\n"
            "         Token may appear in shell history and process listings.\n"
            f"         Use environment variable: export GITHUB_TOKEN='your_token'\n",
            file=sys.stderr,
        )
    elif args.prompt_token:
        token = prompt_for_token()

    token_from_env = os.environ.get("GITHUB_TOKEN")
    if not token and token_from_env:
        token = token_from_env
        if not args.quiet:
            print("[i] Using GitHub token from GITHUB_TOKEN environment variable")
    elif (
        not token and not args.prompt_token and not any([args.output, args.stats_only])
    ):
        token = prompt_for_token()

    # --- Interactive mode (V1-A2) ---
    if not any([args.output, args.stats_only]):
        interactive_menu(token)
        return

    # --- Non-interactive mode via Pipeline (V1-A1) ---
    sys.exit(_run_pipeline(args, token))


if __name__ == "__main__":
    main()
