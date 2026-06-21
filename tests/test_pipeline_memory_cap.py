"""Tests for V1-C4: per-source and global config caps in Pipeline.

Covers:
- max_configs_per_source truncates oversized sources
- dropped_per_source stat is correct
- warning is emitted on per-source cap
- max_total_configs truncates after dedup
- dropped_global stat is correct
- both caps work together
- caps of 0 are edge-case safe
- max_total_configs=None disables global cap
- default values are the documented constants (5000 / 50000)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Any

import pytest

from v2ray_finder.pipeline import (
    Pipeline,
    _DEFAULT_MAX_CONFIGS_PER_SOURCE,
    _DEFAULT_MAX_TOTAL_CONFIGS,
)
from v2ray_finder.sources import SourceEntry, SourceTrust


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source(url: str, trust: SourceTrust = SourceTrust.MEDIUM) -> SourceEntry:
    return SourceEntry(url=url, trust=trust)


def _configs(prefix: str, n: int) -> List[str]:
    """Generate n unique vmess:// config strings."""
    return [f"vmess://{prefix}-{i:06d}" for i in range(n)]


def _stub(data: Dict[str, List[str]]):
    """Return a _fetch_all_sync replacement that returns *data* directly."""
    def _fetch(stop_event, progress_callback):
        return dict(data)
    return _fetch


# ---------------------------------------------------------------------------
# Per-source cap
# ---------------------------------------------------------------------------

class TestPerSourceCap:
    def test_per_source_cap_truncates(self):
        src = _make_source("http://src-a")
        p = Pipeline(sources=[src], check_health=False, max_configs_per_source=3)
        p._fetch_all_sync = _stub({"http://src-a": _configs("a", 10)})
        result = p.run()
        assert len(result.configs) == 3

    def test_per_source_dropped_stat(self):
        src = _make_source("http://src-a")
        p = Pipeline(sources=[src], check_health=False, max_configs_per_source=4)
        p._fetch_all_sync = _stub({"http://src-a": _configs("a", 10)})
        result = p.run()
        assert result.stats["dropped_per_source"] == 6

    def test_per_source_cap_emits_warning(self, caplog):
        src = _make_source("http://src-a")
        p = Pipeline(sources=[src], check_health=False, max_configs_per_source=2)
        p._fetch_all_sync = _stub({"http://src-a": _configs("a", 5)})
        with caplog.at_level(logging.WARNING, logger="v2ray_finder.pipeline"):
            p.run()
        assert any("capped" in r.message for r in caplog.records)

    def test_per_source_no_drop_when_under_cap(self):
        src = _make_source("http://src-a")
        p = Pipeline(sources=[src], check_health=False, max_configs_per_source=100)
        p._fetch_all_sync = _stub({"http://src-a": _configs("a", 5)})
        result = p.run()
        assert result.stats["dropped_per_source"] == 0
        assert len(result.configs) == 5

    def test_per_source_cap_multiple_sources(self):
        src_a = _make_source("http://src-a")
        src_b = _make_source("http://src-b")
        p = Pipeline(sources=[src_a, src_b], check_health=False, max_configs_per_source=3)
        p._fetch_all_sync = _stub({
            "http://src-a": _configs("a", 10),
            "http://src-b": _configs("b", 7),
        })
        result = p.run()
        # Each source capped at 3 → 6 unique configs post-dedup
        assert len(result.configs) == 6
        assert result.stats["dropped_per_source"] == (10 - 3) + (7 - 3)

    def test_per_source_cap_exact_boundary(self):
        """Source with exactly max_configs_per_source entries must not be truncated."""
        src = _make_source("http://src-a")
        p = Pipeline(sources=[src], check_health=False, max_configs_per_source=5)
        p._fetch_all_sync = _stub({"http://src-a": _configs("a", 5)})
        result = p.run()
        assert len(result.configs) == 5
        assert result.stats["dropped_per_source"] == 0


# ---------------------------------------------------------------------------
# Global cap
# ---------------------------------------------------------------------------

class TestGlobalCap:
    def test_global_cap_truncates_after_dedup(self):
        src_a = _make_source("http://src-a")
        src_b = _make_source("http://src-b")
        p = Pipeline(
            sources=[src_a, src_b],
            check_health=False,
            max_configs_per_source=100,
            max_total_configs=5,
        )
        p._fetch_all_sync = _stub({
            "http://src-a": _configs("a", 8),
            "http://src-b": _configs("b", 8),
        })
        result = p.run()
        assert len(result.configs) == 5

    def test_global_dropped_stat(self):
        src = _make_source("http://src-a")
        p = Pipeline(
            sources=[src],
            check_health=False,
            max_configs_per_source=1000,
            max_total_configs=3,
        )
        p._fetch_all_sync = _stub({"http://src-a": _configs("a", 10)})
        result = p.run()
        assert result.stats["dropped_global"] == 7

    def test_global_cap_none_disables_limit(self):
        src = _make_source("http://src-a")
        p = Pipeline(
            sources=[src],
            check_health=False,
            max_configs_per_source=1000,
            max_total_configs=None,
        )
        p._fetch_all_sync = _stub({"http://src-a": _configs("a", 200)})
        result = p.run()
        assert len(result.configs) == 200
        assert result.stats["dropped_global"] == 0

    def test_global_cap_no_drop_when_under_limit(self):
        src = _make_source("http://src-a")
        p = Pipeline(
            sources=[src],
            check_health=False,
            max_configs_per_source=1000,
            max_total_configs=50,
        )
        p._fetch_all_sync = _stub({"http://src-a": _configs("a", 10)})
        result = p.run()
        assert result.stats["dropped_global"] == 0
        assert len(result.configs) == 10

    def test_global_cap_exact_boundary(self):
        src = _make_source("http://src-a")
        p = Pipeline(
            sources=[src],
            check_health=False,
            max_configs_per_source=1000,
            max_total_configs=10,
        )
        p._fetch_all_sync = _stub({"http://src-a": _configs("a", 10)})
        result = p.run()
        assert len(result.configs) == 10
        assert result.stats["dropped_global"] == 0


# ---------------------------------------------------------------------------
# Both caps together
# ---------------------------------------------------------------------------

class TestBothCaps:
    def test_per_source_applied_before_global(self):
        """per-source fires first → global cap sees already-trimmed data."""
        src_a = _make_source("http://src-a")
        src_b = _make_source("http://src-b")
        p = Pipeline(
            sources=[src_a, src_b],
            check_health=False,
            max_configs_per_source=4,   # 10→4 and 8→4 per source
            max_total_configs=6,         # 8 unique after dedup → 6
        )
        p._fetch_all_sync = _stub({
            "http://src-a": _configs("a", 10),
            "http://src-b": _configs("b", 8),
        })
        result = p.run()
        assert len(result.configs) == 6
        assert result.stats["dropped_per_source"] == (10 - 4) + (8 - 4)
        assert result.stats["dropped_global"] == 2  # 8 unique → 6

    def test_dropped_stats_are_independent(self):
        src = _make_source("http://src-a")
        p = Pipeline(
            sources=[src],
            check_health=False,
            max_configs_per_source=5,
            max_total_configs=3,
        )
        p._fetch_all_sync = _stub({"http://src-a": _configs("a", 10)})
        result = p.run()
        # per-source: 10 → 5  (dropped 5)
        # global:      5 → 3  (dropped 2)
        assert result.stats["dropped_per_source"] == 5
        assert result.stats["dropped_global"] == 2
        assert len(result.configs) == 3


# ---------------------------------------------------------------------------
# Default constants
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_default_max_configs_per_source(self):
        assert _DEFAULT_MAX_CONFIGS_PER_SOURCE == 5_000

    def test_default_max_total_configs(self):
        assert _DEFAULT_MAX_TOTAL_CONFIGS == 50_000

    def test_pipeline_default_params(self):
        p = Pipeline(sources=[], check_health=False)
        assert p.max_configs_per_source == _DEFAULT_MAX_CONFIGS_PER_SOURCE
        assert p.max_total_configs == _DEFAULT_MAX_TOTAL_CONFIGS

    def test_pipeline_accepts_custom_caps(self):
        p = Pipeline(
            sources=[],
            check_health=False,
            max_configs_per_source=100,
            max_total_configs=500,
        )
        assert p.max_configs_per_source == 100
        assert p.max_total_configs == 500

    def test_pipeline_accepts_none_global_cap(self):
        p = Pipeline(sources=[], check_health=False, max_total_configs=None)
        assert p.max_total_configs is None
