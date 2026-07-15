"""
Metrics Collection
==================
Lightweight, thread-safe counters and histograms for runtime telemetry.

Backed by in-memory storage for simplicity.  Values are exposed via the
``/metrics`` FastAPI endpoint and can be scraped by Prometheus or read
by internal health checks.

Usage::

    from observability.metrics import metrics
    metrics.increment("tool_calls_total", tags={"tool": "query_data"})
    metrics.observe("mcp_latency_ms", 42.1, tags={"server": "database"})
    snapshot = metrics.snapshot()
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class _HistogramBucket:
    """Accumulates observations for a single metric name + tag set."""

    count: int = 0
    total: float = 0.0
    min_val: float = float("inf")
    max_val: float = float("-inf")

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        if value < self.min_val:
            self.min_val = value
        if value > self.max_val:
            self.max_val = value

    @property
    def mean(self) -> float:
        return self.total / self.count if self.count else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "total": round(self.total, 4),
            "min": round(self.min_val, 4) if self.count else None,
            "max": round(self.max_val, 4) if self.count else None,
            "mean": round(self.mean, 4),
        }


def _tag_key(tags: dict[str, str] | None) -> str:
    if not tags:
        return ""
    return ",".join(f"{k}={v}" for k, v in sorted(tags.items()))


class MetricsCollector:
    """In-process metrics store — counters and histograms."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._histograms: dict[str, dict[str, _HistogramBucket]] = defaultdict(
            lambda: defaultdict(_HistogramBucket)
        )
        self._start_time = time.monotonic()

    # ── Counters ─────────────────────────────────────────────────────

    def increment(
        self,
        name: str,
        value: int = 1,
        *,
        tags: dict[str, str] | None = None,
    ) -> None:
        key = _tag_key(tags)
        with self._lock:
            self._counters[name][key] += value

    # ── Histograms ───────────────────────────────────────────────────

    def observe(
        self,
        name: str,
        value: float,
        *,
        tags: dict[str, str] | None = None,
    ) -> None:
        key = _tag_key(tags)
        with self._lock:
            self._histograms[name][key].observe(value)

    # ── Timer Context Manager ────────────────────────────────────────

    class _Timer:
        """Context manager that records elapsed milliseconds."""

        def __init__(
            self,
            collector: "MetricsCollector",
            name: str,
            tags: dict[str, str] | None,
        ) -> None:
            self._collector = collector
            self._name = name
            self._tags = tags
            self._start: float = 0.0

        def __enter__(self) -> "_Timer":
            self._start = time.perf_counter()
            return self

        def __exit__(self, *exc: object) -> None:
            elapsed_ms = (time.perf_counter() - self._start) * 1000
            self._collector.observe(
                self._name, elapsed_ms, tags=self._tags
            )

    def timer(
        self,
        name: str,
        *,
        tags: dict[str, str] | None = None,
    ) -> _Timer:
        """Return a context manager that records elapsed time in ms."""
        return self._Timer(self, name, tags)

    # ── Snapshot ─────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of all metrics."""
        with self._lock:
            return {
                "uptime_seconds": round(
                    time.monotonic() - self._start_time, 2
                ),
                "counters": {
                    name: dict(buckets)
                    for name, buckets in self._counters.items()
                },
                "histograms": {
                    name: {
                        tag_key: bucket.to_dict()
                        for tag_key, bucket in buckets.items()
                    }
                    for name, buckets in self._histograms.items()
                },
            }

    def reset(self) -> None:
        """Clear all collected metrics (for testing)."""
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._start_time = time.monotonic()


# Module-level singleton
metrics = MetricsCollector()
