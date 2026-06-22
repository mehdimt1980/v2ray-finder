# Changelog

All notable changes to v2ray-finder are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

*(nothing pending)*

---

## [1.0.0] — 2026-06-22

First stable release. All V1 sprint items resolved. Production-ready at scale
(100+ sources, 10k+ configs).

### Added

- **Pipeline orchestrator** (`pipeline.py`) — single `Pipeline` class owning the
  full discovery → fetch → dedup → health-check → score chain with
  `StopController` cancellation, `progress_callback`, memory caps
  (`max_configs_per_source`, `max_total_configs`), and `clear_caches()`.
- **Per-config source attribution** (`V1-C1`) — `_build_config_source_map`
  builds per-config attribution during fetch; highest-trust-wins tie-breaking;
  `PipelineResult.source_attribution` added.
- **GitHub rate-limit coordination** (`V1-C3`) — 403/429 short-circuits
  remaining GitHub sources via shared `asyncio.Event`; `rate_limit_delay=0.1s`
  between GitHub requests; `github_token` param wired through.
- **Memory caps** (`V1-C4`) — `max_configs_per_source` (5 000) and
  `max_total_configs` (50 000) prevent OOM; drop counts in
  `PipelineResult.stats["dropped_per_source"]` and `stats["dropped_global"]`.
- **CLI Pipeline migration** (`V1-A1`) — `cli.py` and `cli_rich.py` fully
  wired to `Pipeline`; flags `--check-health`, `--xray-check`, `--xray-binary`,
  `--min-quality`, `--health-timeout`, `--limit`, `-o`, `--stats-only`,
  `--prompt-token`; `StopController` wired to Ctrl+C (exit 130).
- **GUI Pipeline migration** (`V1-A2`) — `WorkerThread` runs
  `Pipeline.run(stop_event=…, progress_callback=…)`; 7-column sortable result
  table; `PipelineOptionsWidget`; stats bar; Failed Sources panel; all updates
  signal-only (thread-safe).
- **Public API surface** (`V1-A3`) — `__init__.py` defines explicit `__all__`;
  `find_servers()` top-level convenience function; module docstring with
  quick-start examples.
- **Structured result serialisation** (`V1-A4`) — `ServerScore.to_dict()` /
  `to_json()`; `PipelineResult.to_dict()` / `to_json()`;
  `PipelineResult.failed_sources` property.
- **`FetchResult.structured_error`** (`V1-D2`) — machine-readable error payload
  (`category` / `kind` / `message` / `retryable`) across all three fetch
  backends; `PipelineResult.failed_source_messages` backward-compat view.
- **xray Layer-3 port-contention retry** (`V1-D4`) — `check_one()` retries
  once with a fresh OS-assigned port; `RealHealthResult.retried` flag;
  `_try_start_xray()` helper guarantees resource cleanup.
- **`py.typed` marker** (`V1-D3`) — downstream `mypy` now picks up inline
  type hints; `pyproject.toml` mypy overrides for `pipeline`, `scorer`,
  `cache`, `async_fetcher`.
- **Deterministic score tie-breaking** (`V1-Q3`) — composite sort key
  (total desc → latency_ms asc → config asc) in `score_servers` /
  `sort_by_score`; reproducible order across runs.
- **Cache stats + clear hook** (`V1-Q4`) — `PipelineResult.stats["layer3_cache"]`
  populated when `check_google_204=True`; `Pipeline.clear_caches()` added.
- **`AsyncFetcher` as sole HTTP path** (`V1-A3 / V1-D1`) — `pipeline.py`
  delegates all fetching to `AsyncFetcher.fetch_many`; own httpx loop removed;
  connection pooling and backoff unified.

### Changed

- `pyproject.toml` version bumped `0.7.0 → 1.0.0`; Development Status
  classifier updated to `5 - Production/Stable`.
- `Pipeline.run()` stats dict includes `errors`, `dropped_per_source`,
  `dropped_global`, and `layer3_cache` keys.
- `_make_unchecked_dict` now extracts `protocol` from config string.
- `score_servers` / `sort_by_score` / `sort_by_quality` all use `_sort_key`
  composite comparator.

### Tests

- 30 test files; all V1 sprint items have dedicated test modules:
  `test_pipeline_source_attribution.py`, `test_pipeline_memory_cap.py`,
  `test_pipeline_error_model.py`, `test_pipeline_cache_stats.py`,
  `test_xray_retry.py`, `test_stop_mechanism.py`, `test_gui.py`,
  `test_cli_pipeline.py`.

---

## [0.7.0] — 2026-06-18

### Added (V1 Sprint — quality & stability)

- **V1-D2** `FetchResult.structured_error: Optional[dict]` — machine-readable
  error payload with `category` / `kind` / `message` / `retryable` fields.
  All three fetch backends (aiohttp, httpx, requests sync) populate it.
  `PipelineResult.failed_source_messages` provides a backward-compatible
  `{url: message_str}` view; `failed_sources` returns the full dict payload.
- **V1-D4** xray Layer-3 port-contention retry — `check_one()` retries once with
  a fresh OS-assigned port (`find_free_port()`) when xray fails to bind.
  `RealHealthResult.retried` flag is set when the retry path was taken.
  `_try_start_xray()` helper guarantees resource cleanup on both success and
  failure paths. TOCTOU window documented in module docstring.
- **V1-A2** GUI fully migrated to `Pipeline` + `StopController`:
  - ⏹ Stop button — calls `StopController.stop()` and joins the worker thread.
  - Real `QProgressBar` driven by `Pipeline.run(progress_callback=…)`.
  - Result table extended to 7 columns: #, Protocol, Score, Grade,
    Latency (ms), Source, Config.
  - Stats bar: Fetched / Deduped / Healthy / Scored / Cache hits.
  - Collapsible **Failed Sources** panel (`QGroupBox`) below the table.
  - `PipelineOptionsWidget` groups Health / HTTP probe / Google-204 /
    Timeout / Limit controls.
  - All widget updates are signal-only (thread-safe).
- **V1-Q2** Documentation updated across all three language variants
  (README.md, README.en.md, README.fa.md):
  - "What's New in v0.7.0" section.
  - GUI features table.
  - `structured_error` code snippet in Error Handling.
  - xray retry mentioned in Layer-3 health description.

### Tests
- `tests/test_pipeline_error_model.py` — 21 tests covering structured error
  propagation for timeout / network / rate-limit / HTTP-5xx / success paths.
- `tests/test_xray_retry.py` — 28 tests across 9 classes covering
  `find_free_port`, `_try_start_xray`, `check_one` (first-attempt success,
  retry success, both-fail, invalid config, non-URI), `RealConnectivityChecker`
  retried flag propagation, and `check_real_connectivity_batch`.

### Added (V3 Sprint)
- **V3-A1** `ServerScore.to_dict()` / `to_json()` — stable, round-trip-safe JSON
  serialisation for every scored server.
- **V3-A1** `PipelineResult.to_dict()` / `to_json()` — full run serialisation
  (stats + servers + configs).
- **V3-A1** `PipelineResult.failed_sources` property — dict of `{url: error_str}`
  for sources that failed during fetch (V1-D2 foundation).
- **V3-Q3** Deterministic score tie-breaking in `score_servers` / `sort_by_score`:
  primary `total` desc → secondary `latency_ms` asc (None last) → tertiary
  `config` asc.  Reproducible order across runs.
- **V3-D3** `py.typed` marker — downstream `mypy` now picks up inline type hints.
- **V3-D3** `pyproject.toml` mypy overrides — `disallow_untyped_defs = true` for
  `pipeline`, `scorer`, `cache`, `async_fetcher`.
- **V2-C1** TTL source caching in `Pipeline` via `CacheManager` — `cache_enabled`,
  `cache_backend`, `cache_ttl`, `cache_dir`, `cache_manager` params.
- **V2-P1** `cli_rich.py` fully rewritten to use `Pipeline` + `PipelineProgress`
  (Rich progress bars driven by `progress_callback`).

### Changed
- `pyproject.toml` version bumped `0.6.0 → 0.7.0`.
- `Pipeline.run()` stats dict now includes `errors: {}` key (failed source URLs).
- `_make_unchecked_dict` now extracts `protocol` from config string.
- `score_servers` / `sort_by_score` / `sort_by_quality` all use `_sort_key`
  composite comparator.

---

## [0.6.0] — 2026-06-18

### Added (V1 + V2 Sprints)
- **Pipeline orchestrator** (`pipeline.py`) — single `Pipeline` class owning the
  full discovery → fetch → dedup → health → score chain.
- **StopController** — `threading.Event`-backed cancellation shared by CLI, GUI,
  and pipeline.
- **AsyncFetcher** (`async_fetcher.py`) — concurrent httpx/aiohttp fetcher with
  retry/backoff, now the sole HTTP fetch path.
- **Per-config source attribution** — `_build_config_source_map` ensures each
  scored server carries the trust level of its actual originating source.
- **GitHub rate-limit coordination** — 403/429 short-circuits remaining GitHub
  sources; optional `github_token` param.
- **Memory caps** — `max_configs_per_source` (5 000) and `max_total_configs`
  (50 000) prevent OOM on large runs.
- **`find_servers()` public API** — top-level convenience function in `__init__.py`.
- **`CacheManager` integration** — `cache.py` backend abstraction (memory/disk)
  wired into `Pipeline`.
- **Rich CLI rewrite** — `cli_rich.py` migrated to `Pipeline` with live progress.

### Fixed (from opus v1.0.0 review)
- C1: `is_xray_available` now uses `runner.find_binary()`.
- C2: Per-server `RealConnectivityChecker` churn — shared checker, concurrency
  capped at 5.
- C3: `get_all_servers` routes through `normalizer.deduplicate_across_sources`.
- C4: `source_trust` + `overlap_ratio` now reach `scorer.py`.
- A4: Duplicated `_socks5_http_get` and `_latency_to_score` removed; single
  source of truth in `probes.py` / `scoring_curves.py`.
- D1: `google_204` weight rebalanced to 0.10.
- D2: `from_env` kwarg collision guard added.
- D3: `XrayRunner.run` base raises `NotImplementedError`.
- D4: `get_servers_sorted` deprecated, renamed `get_servers_with_metadata`.
- Q2: `MemoryCache` FIFO eviction documented.
- Q4: `_ZERO_SCORE` sentinel hoisted to module level.

---

## [0.5.1] — 2026-06-17

### Fixed
- Minor import cleanup and type annotation corrections.

## [0.5.0] — 2026-06-15

### Added
- Initial `cache.py` with `MemoryCache`, `DiskCache`, `CacheManager`.
- Initial `scorer.py` with 7-dimension scoring and grade.
- `health_checker.py` three-layer health checks (TCP / HTTP / Google-204).
- `normalizer.py` structural deduplication via SHA-256 fingerprinting.
- `sources.py` `SourceEntry` / `SourceTrust` with curated source list.
- `exceptions.py` hierarchy with `to_dict` / `details`.
- `result.py` `Ok` / `Err` algebraic result type.
- Rich CLI (`cli_rich.py`) initial version.
- PySide6 GUI (`gui/main_window.py`) initial version.

## [0.4.0] — 2026-06-10

### Added
- Initial public release with `core.py` `V2RayServerFinder`.
- Basic CLI (`cli.py`) with `-o` / `-s` / `-t` flags.
- GitHub API + raw subscription fetching.
