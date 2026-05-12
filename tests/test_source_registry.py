"""Unit tests for source_registry.py.

Covers:
- SourceStats computed properties (success_rate, avg_servers_per_fetch)
- SourceRegistry.get: create-on-first-access, reuse-on-second
- record_success: counter increments and timestamp updates
- record_failure: failure counter, no success side-effects
- update_overlap: stores ratio correctly
- all_stats: sorted by total_servers_found descending
- summary: human-readable string contains key info
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from v2ray_finder.source_registry import SourceRegistry, SourceStats


# ---------------------------------------------------------------------------
# SourceStats
# ---------------------------------------------------------------------------


class TestSourceStats:
    def test_success_rate_zero_when_no_fetches(self):
        s = SourceStats(url="http://example.com")
        assert s.success_rate == 0.0

    def test_success_rate_calculation(self):
        s = SourceStats(
            url="http://example.com",
            fetch_count=10,
            success_count=7,
        )
        assert abs(s.success_rate - 0.7) < 1e-9

    def test_avg_servers_per_fetch_zero_when_no_fetches(self):
        s = SourceStats(url="http://example.com")
        assert s.avg_servers_per_fetch == 0.0

    def test_avg_servers_per_fetch_calculation(self):
        s = SourceStats(
            url="http://example.com",
            fetch_count=4,
            total_servers_found=20,
        )
        assert abs(s.avg_servers_per_fetch - 5.0) < 1e-9


# ---------------------------------------------------------------------------
# SourceRegistry.get
# ---------------------------------------------------------------------------


class TestSourceRegistryGet:
    def test_creates_new_entry_for_unknown_url(self):
        reg = SourceRegistry()
        s = reg.get("http://new")
        assert isinstance(s, SourceStats)
        assert s.url == "http://new"

    def test_reuses_existing_entry(self):
        reg = SourceRegistry()
        a = reg.get("http://same")
        b = reg.get("http://same")
        assert a is b


# ---------------------------------------------------------------------------
# record_success
# ---------------------------------------------------------------------------


class TestRecordSuccess:
    def test_increments_counters(self):
        reg = SourceRegistry()
        reg.record_success("http://s", server_count=5)
        s = reg.get("http://s")
        assert s.fetch_count == 1
        assert s.success_count == 1
        assert s.total_servers_found == 5

    def test_sets_last_fetched_and_last_success(self):
        reg = SourceRegistry()
        before = datetime.now(timezone.utc)
        reg.record_success("http://s", server_count=1)
        after = datetime.now(timezone.utc)
        s = reg.get("http://s")
        assert s.last_fetched is not None
        assert s.last_success is not None
        assert before <= s.last_fetched <= after

    def test_multiple_calls_cumulative(self):
        reg = SourceRegistry()
        for i in range(5):
            reg.record_success("http://s", server_count=2)
        s = reg.get("http://s")
        assert s.fetch_count == 5
        assert s.success_count == 5
        assert s.total_servers_found == 10


# ---------------------------------------------------------------------------
# record_failure
# ---------------------------------------------------------------------------


class TestRecordFailure:
    def test_increments_failure_counter(self):
        reg = SourceRegistry()
        reg.record_failure("http://f")
        s = reg.get("http://f")
        assert s.fetch_count == 1
        assert s.success_count == 0

    def test_sets_last_fetched(self):
        reg = SourceRegistry()
        before = datetime.now(timezone.utc)
        reg.record_failure("http://f")
        s = reg.get("http://f")
        assert s.last_fetched is not None
        assert s.last_fetched >= before

    def test_last_success_unchanged_after_failure(self):
        reg = SourceRegistry()
        reg.record_success("http://f", 5)
        success_ts = reg.get("http://f").last_success
        reg.record_failure("http://f")
        assert reg.get("http://f").last_success == success_ts


# ---------------------------------------------------------------------------
# update_overlap
# ---------------------------------------------------------------------------


class TestUpdateOverlap:
    def test_stores_overlap_ratio(self):
        reg = SourceRegistry()
        reg.update_overlap("http://o", 0.42)
        s = reg.get("http://o")
        assert abs(s.overlap_ratio - 0.42) < 1e-9

    def test_overwrites_previous_overlap(self):
        reg = SourceRegistry()
        reg.update_overlap("http://o", 0.1)
        reg.update_overlap("http://o", 0.9)
        s = reg.get("http://o")
        assert abs(s.overlap_ratio - 0.9) < 1e-9


# ---------------------------------------------------------------------------
# all_stats
# ---------------------------------------------------------------------------


class TestAllStats:
    def test_returns_all_entries(self):
        reg = SourceRegistry()
        reg.record_success("http://a", 10)
        reg.record_success("http://b", 5)
        stats = reg.all_stats()
        urls = [s.url for s in stats]
        assert "http://a" in urls
        assert "http://b" in urls

    def test_sorted_descending_by_total_servers_found(self):
        reg = SourceRegistry()
        reg.record_success("http://low", 2)
        reg.record_success("http://high", 20)
        stats = reg.all_stats()
        totals = [s.total_servers_found for s in stats]
        assert totals == sorted(totals, reverse=True)


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_contains_url(self):
        reg = SourceRegistry()
        reg.record_success("http://s", 3)
        summary = reg.summary()
        assert "http://s" in summary
