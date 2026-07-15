"""
Unit Tests — Metrics Collector
===============================
Tests for the in-process metrics system in ``observability.metrics``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

from observability.metrics import MetricsCollector


@pytest.fixture
def collector() -> MetricsCollector:
    """Fresh metrics collector per test."""
    return MetricsCollector()


# ═══════════════════════════════════════════════════════════════════════
#  Counters
# ═══════════════════════════════════════════════════════════════════════

class TestCounters:
    def test_increment_default(self, collector: MetricsCollector) -> None:
        collector.increment("test_counter")
        snap = collector.snapshot()
        assert snap["counters"]["test_counter"][""] == 1

    def test_increment_by_value(self, collector: MetricsCollector) -> None:
        collector.increment("test_counter", 5)
        snap = collector.snapshot()
        assert snap["counters"]["test_counter"][""] == 5

    def test_increment_with_tags(self, collector: MetricsCollector) -> None:
        collector.increment("requests", tags={"method": "GET"})
        collector.increment("requests", tags={"method": "POST"})
        collector.increment("requests", tags={"method": "GET"})
        snap = collector.snapshot()
        assert snap["counters"]["requests"]["method=GET"] == 2
        assert snap["counters"]["requests"]["method=POST"] == 1

    def test_multiple_counters(self, collector: MetricsCollector) -> None:
        collector.increment("a")
        collector.increment("b", 3)
        snap = collector.snapshot()
        assert snap["counters"]["a"][""] == 1
        assert snap["counters"]["b"][""] == 3


# ═══════════════════════════════════════════════════════════════════════
#  Histograms
# ═══════════════════════════════════════════════════════════════════════

class TestHistograms:
    def test_single_observation(self, collector: MetricsCollector) -> None:
        collector.observe("latency_ms", 42.5)
        snap = collector.snapshot()
        hist = snap["histograms"]["latency_ms"][""]
        assert hist["count"] == 1
        assert hist["min"] == 42.5
        assert hist["max"] == 42.5
        assert hist["mean"] == 42.5

    def test_multiple_observations(self, collector: MetricsCollector) -> None:
        collector.observe("latency_ms", 10.0)
        collector.observe("latency_ms", 20.0)
        collector.observe("latency_ms", 30.0)
        snap = collector.snapshot()
        hist = snap["histograms"]["latency_ms"][""]
        assert hist["count"] == 3
        assert hist["min"] == 10.0
        assert hist["max"] == 30.0
        assert hist["mean"] == 20.0

    def test_histogram_with_tags(self, collector: MetricsCollector) -> None:
        collector.observe("latency", 10.0, tags={"server": "db"})
        collector.observe("latency", 50.0, tags={"server": "fs"})
        snap = collector.snapshot()
        assert snap["histograms"]["latency"]["server=db"]["count"] == 1
        assert snap["histograms"]["latency"]["server=fs"]["count"] == 1


# ═══════════════════════════════════════════════════════════════════════
#  Timer
# ═══════════════════════════════════════════════════════════════════════

class TestTimer:
    def test_timer_records_value(self, collector: MetricsCollector) -> None:
        with collector.timer("test_timer"):
            _ = sum(range(100))
        snap = collector.snapshot()
        hist = snap["histograms"]["test_timer"][""]
        assert hist["count"] == 1
        assert hist["min"] >= 0  # Time should be non-negative

    def test_timer_with_tags(self, collector: MetricsCollector) -> None:
        with collector.timer("op_time", tags={"op": "read"}):
            pass
        snap = collector.snapshot()
        assert snap["histograms"]["op_time"]["op=read"]["count"] == 1


# ═══════════════════════════════════════════════════════════════════════
#  Snapshot & Reset
# ═══════════════════════════════════════════════════════════════════════

class TestSnapshotReset:
    def test_snapshot_has_uptime(self, collector: MetricsCollector) -> None:
        snap = collector.snapshot()
        assert "uptime_seconds" in snap
        assert snap["uptime_seconds"] >= 0

    def test_reset_clears_all(self, collector: MetricsCollector) -> None:
        collector.increment("counter")
        collector.observe("hist", 1.0)
        collector.reset()
        snap = collector.snapshot()
        assert snap["counters"] == {}
        assert snap["histograms"] == {}

    def test_empty_snapshot(self, collector: MetricsCollector) -> None:
        snap = collector.snapshot()
        assert snap["counters"] == {}
        assert snap["histograms"] == {}
