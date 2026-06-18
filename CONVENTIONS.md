## Session Log

### [2026-06-18] Initial Code Review
**Critical Issues Found:**
- `is_xray_available()` in xray_connectivity.py checks nonexistent `runner.binary_path`, so Layer 3 health checks never run.
- Layer 3 in health_checker.py creates a new RealConnectivityChecker per server, risking overlapping xray port binds under high concurrency.
- `get_all_servers()` in core.py uses naive string dedup, bypassing normalizer's SHA-256 structural deduplication.
- Source trust and overlap_ratio never reach scorer.py, leaving two of six scoring dimensions as dead weight.

**Decisions Made:**
- Introduce a single `Pipeline` orchestrator (new pipeline.py) owning discovery, dedup, health-check, and scoring.
- Replace the plain `_stop_requested` bool with a shared `threading.Event` for true cross-thread cancellation.
- Route real fetching through `AsyncFetcher.fetch_many` instead of serial `requests.get` in core.py.
- Consolidate duplicated `_socks5_http_get` and divergent `_latency_to_score` curves into shared modules.

**Next Steps:**
- Fix `is_xray_available` to use `runner.find_binary()` (unblocks Layer 3).
- Wire normalizer dedup + source trust/overlap into the main pipeline and scorer.
- Build the `Pipeline` orchestrator and migrate CLI/Rich/GUI to it.
- Migrate stop mechanism to `threading.Event`.
- Rebalance scorer reachability weights once Layer 3 runs; rename `get_servers_sorted`.
- Populate the CHANGELOG `[Unreleased]` section.

---

## Roadmap

### Summary Of Work Done This Session
- Performed a full architecture review of the discover → fetch → dedup → health-check → score → output pipeline.
- Catalogued critical correctness bugs (xray availability, per-server checker churn, missing structural dedup, dead scoring dimensions).
- Recorded architectural decisions (Pipeline orchestrator, threading.Event stop, async fetch in main path, shared probe/scoring helpers).
- Appended the dated session log above as the project's source of truth.
- Verified against the latest pasted source that the four critical fixes are **not yet applied** — they remain open below.

### Status Legend
- [ ] TODO — not started / not yet in code
- [~] IN PROGRESS — partially applied
- [x] DONE — verified present in source

---

### P0 — Critical (correctness; pipeline silently produces wrong/empty results)
- [x] **C1. xray availability check is broken** — Fixed: `return runner.find_binary() is not None`
- [x] **C2. Per-server RealConnectivityChecker churn** — Fixed: shared checker in `HealthChecker.__init__`, Layer-3 concurrency capped at 5.
- [x] **C3. Structural dedup bypassed** — Fixed: `get_all_servers` routes through `normalizer.deduplicate_across_sources`.
- [x] **C4. Trust & overlap never reach the scorer** — Fixed: `source_url → SourceEntry` and overlap map threaded into health-result dicts.

### P1 — Architecture (structural; unlocks correctness and maintainability)
- [x] **A1. Pipeline orchestrator** — `pipeline.py` with `Pipeline`, `PipelineResult`, `StopController`.
- [x] **A2. threading.Event stop mechanism** — `threading.Event` shared across `StopController` and GUI `WorkerThread`.
- [x] **A3. Use AsyncFetcher in the real path** — `AsyncFetcher.fetch_many` is the real fetch path.
- [x] **A4. De-duplicate probe/scoring helpers** — `probes.py` and `scoring_curves.py` extracted; both consumers import from them.

### P2 — Technical Debt
- [x] **D1. google_204 weight = 0** — Rebalanced to 0.10.
- [x] **D2. `from_env` kwarg collision** — `kwargs.pop("token", None)` guard added.
- [x] **D3. `XrayRunner.run` broken stub** — Base raises `NotImplementedError`; `XrayBinaryManager.run` is the real async ctx.
- [x] **D4. `get_servers_sorted` does not sort** — Deprecated with `warnings.warn`, renamed to `get_servers_with_metadata`.

### P3 — Quick Wins (small, high-impact)
- [x] **Q1. Fix `is_xray_available`** — Fixed.
- [x] **Q2. Document MemoryCache eviction** — FIFO docstring added.
- [x] **Q3. Warn on dropped token** — `logger.warning` added.
- [x] **Q4. Hoist zero-score sentinel** — `_ZERO_SCORE` module-level sentinel in scorer.py.
- [x] **Q5. Populate CHANGELOG `[Unreleased]`** — Done.

### Keep As-Is (well-designed; do not refactor without cause)
- [x] `result.py` Ok/Err Result type — clean and well-used.
- [x] `sources.py` SourceEntry / get_enabled_sources — filterable, trust-tagged.
- [x] `normalizer.py` structural fingerprinting — correct (needs wiring per C3).
- [x] `exceptions.py` hierarchy — comprehensive, with to_dict/details.
- [x] `cache.py` backend abstraction — clean ABC, graceful diskcache fallback.
- [x] Piecewise-linear latency curve — sound thresholds (consolidate per A4).

---

## v1.0.0 Readiness Review — [2026-06-18]

Scope: production-readiness at scale (100+ sources, 10k+ configs), public
API quality, and PyPI publishability. Analysis only — no code in this pass.
Each actionable item has a ready-to-paste aider prompt directly beneath it.

### Status Legend
- [ ] TODO   [~] IN PROGRESS   [x] DONE

---

## 1. Critical Issues (would fail in production)

### [ ] V1-C1. Per-server source attribution in pipeline is wrong
`pipeline.py::Pipeline._run_health` attributes EVERY healthy server to the
*first* source URL found in `overlap_map`. This means `source_trust` and
`overlap_ratio` (two scoring dimensions, 0.15 of total weight) are identical
for all servers — the C4 fix is structurally defeated inside the Pipeline.
At scale every config gets the same (often wrong) trust/overlap.

```
In src/v2ray_finder/pipeline.py, fix the source attribution bug in _run_health. Currently it assigns the first source
URL from overlap_map to every healthy server. Instead, build a per-config source map during fetch: change
_fetch_all/_fetch_all_async/_fetch_all_sync to also return, or store on self, a dict mapping each config string to the
SourceEntry it came from (first source wins on collision). Then in _run_health, look up each h.config in that map to set
source_url, source_trust (from SourceEntry.trust.value), and overlap_ratio (from overlap_map[source_url]). Add a unit
test in tests/test_pipeline.py that fetches two sources with different trust levels and asserts each scored server
carries the trust of its actual originating source.
```

### [ ] V1-C2. AsyncFetcher / pipeline open a new httpx client per request
`pipeline.py::_fetch_all_async._fetch_one` constructs `httpx.AsyncClient(...)`
inside the per-source coroutine, so connection pooling never happens — with
100+ sources this opens 100+ TLS sessions and exhausts ephemeral ports.
`async_fetcher.py` is the documented real fetch path (A3) but `pipeline.py`
re-implements its own httpx loop instead of using it.

```
In src/v2ray_finder/pipeline.py, refactor _fetch_all_async to create ONE shared httpx.AsyncClient (with
limits=httpx.Limits(max_connections=self.fetch_concurrency, max_keepalive_connections=self.fetch_concurrency)) and
reuse it across all source fetches via the existing semaphore. Move client creation outside _fetch_one so the single
client is passed in. Ensure the client is closed in a finally block. Do not change the public signature of
_fetch_all_async. Update tests/test_pipeline.py mocks accordingly.
```

### [ ] V1-C3. No GitHub rate-limit coordination on the async path
`core.py` tracks rate limits via `_check_rate_limit`, but the Pipeline async
fetch path bypasses `core.py` entirely and never inspects
`X-RateLimit-Remaining`. At 100+ sources including GitHub raw/API endpoints,
this triggers 403/429 bans mid-run with no backoff.

```
In src/v2ray_finder/pipeline.py, add GitHub rate-limit awareness to _fetch_all_async. After each response, if the host
is api.github.com or raw.githubusercontent.com and the response has X-RateLimit-Remaining, log a warning when remaining
< 10% of limit, and if status is 403/429 with a Retry-After or X-RateLimit-Reset header, skip remaining GitHub-host
sources for this run rather than hammering them. Add a Pipeline.__init__ param github_token: Optional[str] = None that,
when set, adds the Authorization header to GitHub-host requests only. Add tests covering: 429 short-circuits GitHub
sources, non-GitHub sources continue, token header applied only to github hosts.
```

### [ ] V1-C4. Unbounded memory on 10k+ configs (no streaming)
`Pipeline.run` holds `servers_by_source`, `configs`, `health_dicts`, and
`scores` simultaneously. With 10k+ configs across 100+ sources the raw text
plus parsed lists plus ServerHealth plus ServerScore objects all live at once.
There is no cap between fetch and dedup, so a single huge source can OOM.

```
In src/v2ray_finder/pipeline.py, add a per-source config cap and a global pre-dedup cap. Add Pipeline.__init__ params
max_configs_per_source: int = 5000 and max_total_configs: Optional[int] = 50000. In _parse_configs callers, truncate
each source's parsed list to max_configs_per_source. After dedup, before health checks, truncate to max_total_configs if
set. Log how many were dropped. Add tests asserting both caps are enforced.
```

---

## 2. Architecture Improvements (structural, for v1.0.0)

### [ ] V1-A1. CLI does not expose Pipeline parameters
`cli.py` / `cli_rich.py` still call legacy `finder.get_*` methods and do not
expose check_http_probe, check_google_204, fetch_concurrency,
min_quality_score, limit, binary_path, or an output format. This is a stated
v1.0.0 requirement.

```
In src/v2ray_finder/cli.py, migrate the non-interactive path to use v2ray_finder.pipeline.Pipeline. Add argparse flags:
--health/--no-health (check_health), --http-probe (check_http_probe), --google-204 (check_google_204), --concurrency N
(fetch_concurrency, default 10), --min-quality FLOAT (min_quality_score), --limit N, --xray-binary PATH (binary_path),
and --format {raw,json,table} (default raw). Build a Pipeline from these flags, run it with a StopController wired to
Ctrl+C, and render output per --format: raw = one config per line, json = list of
{config,protocol,grade,total,latency_ms}, table = aligned columns. Keep the existing -o/-s/-q/-t flags working.
Preserve exit code 130 on interruption with partial save. Add tests in tests/test_cli.py for each new flag and each
output format.
```

```
In src/v2ray_finder/cli_rich.py, migrate the non-interactive and interactive paths to v2ray_finder.pipeline.Pipeline.
Add the same flags as cli.py (--health/--no-health, --http-probe, --google-204, --concurrency, --min-quality, --limit,
--xray-binary, --format raw|json|table). Wire Pipeline.run's progress_callback to a Rich Progress bar with one task per
stage (fetch/health/score). Render table format using rich.table.Table with columns Grade, Protocol, Latency, Score,
Config. Keep StopController wired to Ctrl+C and partial-save behaviour. Add tests in tests/test_cli_rich.py.
```

### [ ] V1-A2. GUI is not wired to Pipeline
`gui/main_window.py::WorkerThread` still calls
`finder.get_servers_from_known_sources` / `get_servers_from_github` and does
not run health checks, scoring, progress, or sortable scored results — all
stated v1.0.0 requirements.

```
In src/v2ray_finder/gui/main_window.py, rewrite WorkerThread to run v2ray_finder.pipeline.Pipeline. Pass a
StopController and connect its event to a Stop button. Emit a new progress(stage:str, current:int, total:int,
message:str) signal from Pipeline's progress_callback (marshal via the worker thread, not directly to widgets). Emit
finished(result: PipelineResult). Add GUI controls for check_health, check_http_probe, check_google_204,
min_quality_score, fetch_concurrency, and limit. In MainWindow.on_fetch_finished, populate the table from result.scores
with sortable columns Grade, Protocol, Latency(ms), Score, Config (use QTableWidget.setSortingEnabled(True) and numeric
sort keys). Add an Export button that writes the displayed configs to a chosen file. Update tests/test_gui.py to assert
the worker builds a Pipeline, the progress signal fires, and the table sorts by score.
```

### [ ] V1-A3. Public API surface is undefined
There is no curated `__all__`, no top-level convenience function, and callers
must know internal module layout. For a trusted PyPI library the package
top-level should expose a stable, documented surface.

```
In src/v2ray_finder/__init__.py, define an explicit __all__ exporting the stable public API: Pipeline, PipelineResult,
StopController, ServerScore, ServerHealth, HealthStatus, V2RayServerFinder, and the exception classes (V2RayFinderError
and subclasses). Add a top-level convenience function find_servers(check_health: bool = True, limit: Optional[int] =
None, **kwargs) -> PipelineResult that constructs a Pipeline and calls run(). Add a module docstring documenting the
public API and a one-line usage example. Do not export internal helpers (_parse_configs, probes, scoring_curves
internals). Add a test asserting every name in __all__ is importable from v2ray_finder.
```

### [x] V1-A4. No structured result serialization
`PipelineResult` and `ServerScore` have no `to_dict`/`to_json`. JSON output
(CLI --format json, GUI export, programmatic use) each re-implement
serialization, guaranteeing drift.
— Fixed: `ServerScore.to_dict()`, `PipelineResult.to_dict()`, `PipelineResult.to_json()` added.

---

## 3. Technical Debt (fix before v1.0.0)

### [x] V1-D1. Two parallel fetch implementations
`async_fetcher.py` (A3 path) and `pipeline.py::_fetch_all_async` both
implement httpx fetching with retry/backoff.
— Fixed: `pipeline.py` delegates all HTTP fetching to `AsyncFetcher.fetch_many`;
own httpx loop removed; GitHub rate-limit handled via separate GitHub/non-GitHub
fetcher instances with token support.

### [x] V1-D2. Inconsistent timeout/error semantics across modules
— Fixed: Pipeline records per-source failures in `PipelineResult.stats["errors"]`;
`PipelineResult.failed_sources` property added; Pipeline never raises on network failures.

### [x] V1-D3. Missing py.typed marker and full type coverage
— Fixed: `py.typed` marker added at `src/v2ray_finder/py.typed`;
mypy section added to `pyproject.toml`.

### [x] V1-D4. No retry/backoff on Layer-3 xray startup at scale
`xray_connectivity.py` caps Layer 3 concurrency at 5 but a flaky binary
or port contention yields hard failures with no retry.
— Fixed: `_try_start_xray()` helper extracted with `runner.stop()` on failure;
one retry on fresh free port in `check_one`; resource leak plugged; type hints
corrected; tests added in `tests/test_xray_retry.py`.

---

## 4. Quick Wins (small, high-impact)

### [ ] V1-Q1. CHANGELOG and version bump for v1.0.0

```
Update CHANGELOG.md: move the [Unreleased] entries under a new [1.0.0] heading summarising the Pipeline orchestrator,
async fetch, 3-layer health checks, 7-dimension scorer, and the CLI/GUI Pipeline migration. Bump the version to 1.0.0 in
pyproject.toml and src/v2ray_finder/__init__.py (__version__). Add a fresh empty [Unreleased] section.
```

### [ ] V1-Q2. README quickstart for the public API

```
Update README.md with a Quickstart section showing: pip install v2ray-finder, a 5-line Python example using
v2ray_finder.find_servers() and iterating result.scores, and the three CLI invocations (raw/json/table output). Add a
short API table listing Pipeline, PipelineResult, StopController, find_servers. Keep it under 60 lines.
```

### [x] V1-Q3. Deterministic score tie-breaking
`scorer.score_servers` sorts by `total` only; equal totals produce
nondeterministic order across runs, breaking reproducible output/tests.
— Fixed: composite sort key (total desc, latency_ms asc, config asc) in
`score_servers` and `sort_by_score`; test added.

### [x] V1-Q4. Expose cache stats and a clear-cache hook in Pipeline
Layer-3 has a result cache (`_ResultCache`) but Pipeline neither surfaces its
stats nor lets callers clear it between runs.
— Fixed: `PipelineResult.stats["layer3_cache"]` populated when `check_google_204=True`;
`Pipeline.clear_caches()` added; tests added in `tests/test_pipeline_cache_stats.py`
(duplicate test fixed, `HealthChecker` patch path corrected, object-identity reuse test added).

---

## 5. Keep As-Is (well-designed, don't touch)
- [x] normalizer.py structural fingerprinting + deduplicate_across_sources — correct and well-tested.
- [x] scoring_curves.py / probes.py shared helpers (A4) — clean single source of truth.
- [x] sources.py SourceEntry / SourceTrust / get_enabled_sources — solid, filterable.
- [x] exceptions.py hierarchy with to_dict/details — comprehensive.
- [x] result.py Ok/Err — keep as the low-level fetch error type.
- [x] cache.py backend abstraction (FIFO documented per Q2) — fine for v1.0.0.
- [x] StopController / threading.Event cancellation model (A2) — correct, reused everywhere.

---

## Recommended Execution Order for v1.0.0
1. V1-C1, V1-C2 (correctness + pooling — both inside pipeline, do together)
2. V1-D1 (collapse the two fetch paths; subsumes part of C2/C3 cleanup)
3. V1-C3, V1-C4 (rate-limit + memory caps on the unified fetch path)
4. V1-A1, V1-A2 (CLI + GUI Pipeline wiring — the headline v1.0.0 deliverables)
5. V1-A3, V1-A4, V1-D2 (public API surface + serialization + error model)
6. V1-D3, V1-D4 (typing marker + xray retry)
7. V1-Q1..Q4 (changelog, README, determinism, cache stats)
