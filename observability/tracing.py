"""
Distributed Tracing
===================
Thin OpenTelemetry wrapper for distributed tracing across the platform.

If the ``opentelemetry`` SDK is installed the module produces real spans;
otherwise it falls back to **no-op** implementations so the rest of the
codebase never needs ``try/except ImportError`` guards.

Usage::

    from observability.tracing import tracer
    with tracer.start_as_current_span("orchestrator.run") as span:
        span.set_attribute("query", user_query)
        ...
"""

from __future__ import annotations

import contextlib
from typing import Any, Generator

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )

    _HAS_OTEL = True
except ImportError:  # pragma: no cover
    _HAS_OTEL = False


_CONFIGURED = False


def configure_tracing(
    service_name: str = "data-analyst-platform",
    *,
    enable_console_export: bool = False,
) -> None:
    """Initialise the OpenTelemetry tracer provider (idempotent)."""
    global _CONFIGURED  # noqa: PLW0603
    if _CONFIGURED or not _HAS_OTEL:
        return
    _CONFIGURED = True

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if enable_console_export:
        provider.add_span_processor(
            BatchSpanProcessor(ConsoleSpanExporter())
        )

    trace.set_tracer_provider(provider)


# ── No-Op Fallbacks ──────────────────────────────────────────────────

class _NoOpSpan:
    """Minimal stand-in when OpenTelemetry is unavailable."""

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: ARG002
        pass

    def set_status(self, *args: object, **kwargs: object) -> None:
        pass

    def record_exception(self, exc: BaseException) -> None:  # noqa: ARG002
        pass

    def end(self) -> None:
        pass


class _NoOpTracer:
    """Drop-in tracer that does nothing."""

    @contextlib.contextmanager
    def start_as_current_span(
        self,
        name: str,  # noqa: ARG002
        **kwargs: Any,
    ) -> Generator[_NoOpSpan, None, None]:
        yield _NoOpSpan()


def get_tracer(name: str = "data-analyst-platform") -> Any:
    """Return an OpenTelemetry tracer or a no-op stand-in."""
    if _HAS_OTEL:
        configure_tracing()
        return trace.get_tracer(name)
    return _NoOpTracer()


tracer = get_tracer()
