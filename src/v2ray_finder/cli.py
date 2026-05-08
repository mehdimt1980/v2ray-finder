"""Command-line interface for v2ray-finder."""

import argparse
import os
import sys
import threading
from getpass import getpass
from typing import List, Optional

from .core import V2RayServerFinder
from .exceptions import AuthenticationError, RateLimitError


class StopController:
    """
    Thread-safe stop controller for non-interactive CLI mode only.
    """

    def __init__(self, finder: V2RayServerFinder) -> None:
        self._finder = finder
        self._active = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._finder.reset_stop()
        self._active.set()
        print(
            "\n[i] Press 'q' + Enter at any time to stop and save partial results\n",
            flush=True,
        )
        self._thread = threading.Thread(
            target=self._listen, daemon=True, name="StopListener"
        )
        self._thread.start()

    def _listen(self) -> None:
        while self._active.is_set():
            try:
                key = input().strip().lower()
                if key == "q":
                    print(
                        "\n[!] Stop requested — finishing current request...",
                        flush=True,
                    )
                    self._finder.request_stop()
                    self._active.clear()
                    break
            except EOFError:
                self._active.clear()
                break

    def stop(self) -> None:
        self._active.clear()


def print_stats(servers, show_health: bool = False, show_xray: bool = False) -> None:
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

    if show_health and servers and isinstance(servers[0], dict):
        healthy = sum(1 for s in servers if s.get("health_status") == "healthy")
        degraded = sum(1 for s in servers if s.get("health_status") == "degraded")
        unreachable = sum(1 for s in servers if s.get("health_status") == "unreachable")
        invalid = sum(1 for s in servers if s.get("health_status") == "invalid")
        print("\nHealth status:")
        print(f"  Healthy: {healthy}")
        print(f"  Degraded: {degraded}")
        print(f"  Unreachable: {unreachable}")
        print(f"  Invalid: {invalid}")
        if healthy > 0:
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
        if reachable > 0:
            avg_lat = (
                sum(
                    s.get("latency_ms") or 0
                    for s in servers
                    if s.get("reachable")
                )
                / reachable
            )
            print(f"  Avg real latency:  {avg_lat:.1f}ms")


def prompt_for_token() -> Optional[str]:
    print("\n=== GitHub Token Setup ===")
    print("A GitHub token increases rate limits from 60 to 5000 requests/hour.")
    print("Your token will NOT be stored and is only used for this session.\n")
    use_token = input("Do you want to provide a GitHub token? (y/n): ").strip().lower()
    if use_token == "y":
        print("\nPaste your GitHub token (input will be hidden):")
        token = getpass("Token: ").strip()
        if token:
            print("[✓] Token received\n")
            return token
        print("[!] No token provided, continuing without authentication\n")
        return None
    print("[i] Continuing without authentication\n")
    return None


def save_partial_results(
    servers: List, filename: str = "v2ray_servers_partial.txt"
) -> None:
    if not servers:
        print("No servers to save.")
        return
    try:
        configs: List[str]
        if servers and isinstance(servers[0], dict):
            configs = [s.get("config", "") for s in servers if s.get("config")]
        else:
            configs = list(servers)
        with open(filename, "w", encoding="utf-8") as fh:
            for server in configs:
                fh.write(f"{server}\n")
        print(f"\n[✓] Saved {len(configs)} servers to {filename}")
        print("    You can resume or use these servers.\n")
    except OSError as exc:
        print(f"\n[!] Failed to save partial results: {exc}\n")


def interactive_menu(finder: V2RayServerFinder) -> None:
    partial_servers: List = []

    while True:
        print("\n=== V2Ray Server Finder ===")
        print("1. Fetch from known sources")
        print("2. Fetch with GitHub search")
        print("3. Fetch with health checking (TCP/HTTP)")
        print("4. Save to file")
        print("5. Show statistics only")
        print("6. Check rate limit info")
        print("7. Real connectivity check via xray (ground-truth)")
        print("0. Exit")

        try:
            choice = input("\nSelect option: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nGoodbye!")
            break

        if choice == "0":
            print("Goodbye!")
            break

        elif choice == "1":
            print("\nFetching from known sources...")
            print("(Press Ctrl+C to stop and save partial results)")
            finder.reset_stop()
            try:
                servers = finder.get_all_servers(use_github_search=False)
            except KeyboardInterrupt:
                finder.request_stop()
                servers = []
            partial_servers = servers
            if finder.should_stop() and servers:
                print(f"\n[!] Stopped early — {len(servers)} partial results")
                save_partial_results(servers)
            print_stats(servers)

        elif choice == "2":
            print("\nFetching with GitHub search (slower)...")
            print("(Press Ctrl+C to stop and save partial results)")
            finder.reset_stop()
            try:
                servers = finder.get_all_servers(use_github_search=True)
            except KeyboardInterrupt:
                finder.request_stop()
                servers = []
            partial_servers = servers
            if finder.should_stop() and servers:
                print(f"\n[!] Stopped early — {len(servers)} partial results")
                save_partial_results(servers)
            print_stats(servers)
            rate_info = finder.get_rate_limit_info()
            if rate_info:
                print(
                    f"\nAPI calls remaining: "
                    f"{rate_info['remaining']}/{rate_info['limit']}"
                )

        elif choice == "3":
            try:
                use_search = input("Use GitHub search? (y/n): ").strip().lower() == "y"
            except (KeyboardInterrupt, EOFError):
                continue
            print("\nFetching and checking server health (TCP/HTTP)...")
            print("(Press Ctrl+C to stop)")
            finder.reset_stop()
            try:
                servers = finder.get_servers_with_health(
                    use_github_search=use_search,
                    check_health=True,
                    health_timeout=5.0,
                    min_quality_score=0,
                    filter_unhealthy=False,
                )
            except KeyboardInterrupt:
                finder.request_stop()
                servers = []
            partial_servers = servers
            if finder.should_stop() and servers:
                print(f"\n[!] Stopped early — {len(servers)} partial results")
                save_partial_results(servers, "v2ray_servers_partial_health.txt")
            print_stats(servers, show_health=True)
            if servers:
                try:
                    show_top = input("\nShow top 10 by quality? (y/n): ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    show_top = "n"
                if show_top == "y":
                    print("\nTop 10 servers by quality:")
                    for i, s in enumerate(servers[:10], 1):
                        status = s.get("health_status", "unknown")
                        quality = s.get("quality_score", 0)
                        latency = s.get("latency_ms", 0)
                        proto = s.get("protocol", "?")
                        print(
                            f"{i:2d}. [{proto:8s}] Quality: {quality:5.1f} "
                            f"| Latency: {latency:6.1f}ms | Status: {status}"
                        )

        elif choice == "4":
            try:
                filename = (
                    input("Enter filename (default: v2ray_servers.txt): ").strip()
                    or "v2ray_servers.txt"
                )
                use_search = input("Use GitHub search? (y/n): ").strip().lower() == "y"
                check_health = (
                    input("Check server health? (y/n): ").strip().lower() == "y"
                )
                limit_str = input("Limit (0 for all): ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n[!] Cancelled")
                continue
            limit = int(limit_str) if limit_str and limit_str != "0" else None
            print(f"\nSaving to {filename}...")
            finder.reset_stop()
            try:
                if check_health:
                    print("(Health checking enabled — this will take longer)")
                    health_data = finder.get_servers_with_health(
                        use_github_search=use_search,
                        check_health=True,
                        health_timeout=5.0,
                        min_quality_score=50.0,
                        filter_unhealthy=True,
                    )
                    output: List[str] = [s["config"] for s in health_data]
                else:
                    raw = finder.get_all_servers(use_github_search=use_search)
                    output = list(raw)
            except KeyboardInterrupt:
                finder.request_stop()
                output = []
            if limit:
                output = output[:limit]
            partial_servers = output
            if finder.should_stop():
                save_partial_results(output, filename)
            else:
                try:
                    with open(filename, "w", encoding="utf-8") as fh:
                        for server in output:
                            fh.write(f"{server}\n")
                    print(f"Saved {len(output)} serv