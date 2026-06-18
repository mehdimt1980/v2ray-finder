# Changelog

All notable changes to v2ray-finder are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Planned
- V1-D2: unified error model across fetcher / pipeline / core
- V1-D4: xray Layer-3 retry on port contention
- V1-Q2: README quickstart (public API + CLI examples)
- GUI Pipeline migration (V1-A2 remainder)

---

## [0.7.0] — 2026-06-18

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
