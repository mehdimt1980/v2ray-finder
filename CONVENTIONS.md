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
