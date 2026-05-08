# Changelog

All notable changes to v2ray-finder will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.3.0] - 2026-05-08

### Added

- **Real-time health checking** — servers are now health-checked **immediately**
  as each one is discovered, not in a separate batch step after all sources are
  exhausted.

  **New constructor parameters on `V2RayServerFinder`:**
  | Parameter | Default | Description |
  |---|---|---|
  | `realtime_health_check` | `False` | Enable per-server inline health checks |
  | `health_timeout` | `5.0` | Timeout (seconds) per check method |
  | `health_concurrent_limit` | `50` | Max concurrent async checks |
  | `health_enable_google_204` | `True` | Google 204 connectivity check |
  | `health_enable_http_check` | `True` | HTTP-level reachability check |

- **Google 204 connectivity check** in `health_checker.py`
  - `GET http://connectivitycheck.gstatic.com/generate_204`
  - Expects HTTP 204 (same check Android uses for captive-portal detection)
  - Implemented as `HealthChecker.check_google_204()` (async)
  - A secondary fallback endpoint (`gstatic.com/generate_204`) is also defined

- **HTTP reachability check** in `health_checker.py`
  - `HealthChecker.check_http_reachability()` — lightweight HTTP GET to the
    server's own `host:port`
  - Any HTTP response (including 4xx/5xx) counts as reachable; only connection
    error / timeout counts as failure
  - SSL/TLS errors are treated as *reachable* (port is open, just not plain HTTP)

- **`ServerHealth` extended fields:**
  - `tcp_ok: bool` — did TCP connect succeed?
  - `http_ok: bool` — did HTTP reachability check succeed?
  - `google_204_ok: bool` — did Google 204 check return 204?
  - `check_methods: List[str]` — which methods were run (`tcp`, `http`, `google_204`)

- **Quality score bonus** — `google_204_ok` adds +10 pts, `http_ok` adds +5 pts
  to the quality score on top of the latency-based base score.

- **`HealthChecker.check_server_now()`** — synchronous single-server check;
  designed for inline use inside discovery pipelines without accumulating a batch.

- **`HealthChecker.check_servers_batch()`** now uses a shared `aiohttp.ClientSession`
  with a matching `TCPConnector` for the entire batch, reducing connection overhead.

- **Generator-based discovery pipeline** in `core.py`
  - `_iter_raw_servers(use_github_search)` — generator that yields raw server
    strings one at a time as each source is parsed (enables streaming)
  - `_iter_servers_with_realtime_health(use_github_search)` — wraps the raw
    generator; yields only servers that pass `_passes_realtime_check()`

- **`get_all_servers()` updated** — when `realtime_health_check=True` the method
  transparently routes through the streaming pipeline; the public API is unchanged.

- **`get_servers_with_health()` result dicts** now include the new fields:
  `tcp_ok`, `http_ok`, `google_204_ok`, `check_methods`.

### Changed

- `health_checker.py` now depends on **`aiohttp`** (replaces plain
  `asyncio.open_connection` for HTTP-level checks). `aiohttp` is already an
  optional dependency via `[async]`; it is now also pulled in by `[health]`.
- `ServerHealth` dataclass gains four new optional fields with safe defaults
  (`False` / `[]`) — **backward compatible**.
- `HealthChecker.__init__` gains two new optional flags:
  `enable_google_204=True` and `enable_http_check=True`.

### Technical Notes

- **Zero breaking changes** for existing callers — `realtime_health_check`
  defaults to `False`, preserving the previous batch-only behaviour.
- The real-time path is **fail-open**: if `health_checker` cannot be imported or
  an unexpected error occurs, the server is passed through unchanged.
- All three check methods run **concurrently** via `asyncio.gather` per server,
  keeping per-server wall-clock time equal to `max(tcp, http, g204)` rather than
  their sum.

---

## [0.2.1] - 2026-02-24

### Fixed

- **Graceful stop / Ctrl+C handling** — complete overhaul across all layers:

  **`core.py` — `get_servers_from_known_sources()`**
  - Added `try/except KeyboardInterrupt` around each URL fetch
  - On interrupt: calls `self.request_stop()`, breaks the loop, returns
    whatever was already collected (partial results are no longer lost)

  **`core.py` — `get_servers_from_github()`**
  - Same `try/except KeyboardInterrupt` pattern applied to the repo-file
    iteration loop
  - Partial results from files fetched before Ctrl+C are preserved

  **`core.py` — `get_servers_with_health()`**
  - Added `health_batch_size` parameter (default `50`) to split the
    server list into smaller batches
  - `should_stop()` is checked between every batch — no longer necessary
    to wait for all health checks to finish before the stop takes effect
  - `try/except KeyboardInterrupt` inside the batch loop: already-checked
    servers are returned immediately on interrupt

  **`cli.py` — interactive menu**
  - Removed `start_keyboard_listener()` / `stop_keyboard_listener()` calls
    from `interactive_menu()` — the background thread competed with the
    menu's own `input()` calls, silently discarding the first keystroke
    after each operation
  - Every menu operation (options 1–5) now has its own
    `try/except KeyboardInterrupt` with partial-results save
  - Replaced bare boolean `_stop_listener` flag with `threading.Event`
    inside `StopController` for thread-safe lifecycle control
  - `StopController` (listener thread) is now used **only** in the
    non-interactive (`--output` / `--stats-only`) path where the main
    thread never calls `input()` during a fetch

  **`cli_rich.py` — Rich interactive mode**
  - `_signal_handler()` now calls `_active_finder.request_stop()` before
    re-raising `KeyboardInterrupt`; previously it only set a bare boolean
    that the core loops never checked
  - `fetch_servers()` updates the `partial` snapshot after every
    individual step (known sources, then GitHub search) so a Ctrl+C at
    any point yields whatever was collected up to that moment
  - `StopController` (same pattern as plain CLI) used only in
    non-interactive path to avoid competing `input()` threads

### Tests

- Added `TestHealthBatchStop` class to `tests/test_stop_mechanism.py`

---

## [0.2.0] - 2026-02-20

### Added

- **Async HTTP Fetching** (`async_fetcher` module) — 10-50x faster concurrent downloads
- **Smart Caching Layer** (`cache` module) — memory/disk, configurable TTL, hit-rate stats
- **Enhanced Error Handling** (`exceptions` + `result` modules)
- **Health Checking** (`health_checker` module) — TCP connectivity, latency, quality scoring
- **Secure Token Handling** — `GITHUB_TOKEN` env var, `from_env()` factory
- **Rate Limit Tracking** — `get_rate_limit_info()`
- **Test Suite** (78% coverage) — CI matrix Python 3.8–3.12 on Linux/macOS/Windows

### Changed

- `search_repos()` returns `Result[List[Dict], V2RayFinderError]`
- Rate limit checking moved after HTTP status checks

---

## [0.1.0] - 2026-01-15

### First Release

- GitHub repository search for public V2Ray configs
- Curated direct subscription sources (3 reliable sources)
- Protocol support: vmess, vless, trojan, shadowsocks (ss), ssr
- Automatic deduplication
- Python API + CLI + Rich CLI + GUI (PySide6)

---

## Project Statistics

| Metric | Value |
|--------|-------|
| Source Lines | ~3,000+ |
| Test Files | 8 |
| Test Coverage | ~80% |
| Supported Protocols | 5 (vmess, vless, trojan, ss, ssr) |
| Health Check Methods | 3 (TCP, HTTP, Google 204) |
| Interfaces | 3 (Python API, CLI, GUI) |
| Python Versions | 3.8 – 3.12 |
| Platforms | Linux, macOS, Windows |

---

## Contributors

- Ali Sadeghi Aghili ([@alisadeghiaghili](https://github.com/alisadeghiaghili)) — Creator & Maintainer

---

## License

MIT License — see [LICENSE](LICENSE) for details.
