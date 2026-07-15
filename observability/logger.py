"""
Structured Logging
==================
Configures ``structlog`` for the entire platform.

* **Development** (``log_format=console``): human-readable coloured output.
* **Production** (``log_format=json``): machine-parseable JSON lines for
  log aggregators (Datadog, ELK, CloudWatch).

Every log entry automatically carries:

* ``timestamp`` — ISO-8601 UTC
* ``level`` — DEBUG / INFO / WARNING / ERROR / CRITICAL
* ``logger`` — the module that emitted the event
* ``correlation_id`` — propagated across the request lifecycle

Usage::

    from observability.logger import get_logger
    log = get_logger(__name__)
    log.info("tool_called", tool="query_data", latency_ms=42)
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

from core.config import get_settings

# ── Context Variables ────────────────────────────────────────────────

correlation_id_ctx: ContextVar[str] = ContextVar(
    "correlation_id", default="no-correlation-id"
)
session_id_ctx: ContextVar[str] = ContextVar(
    "session_id", default="no-session"
)
request_id_ctx: ContextVar[str] = ContextVar(
    "request_id", default="no-request"
)


def _add_context_vars(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Inject correlation / session / request IDs into every log entry."""
    event_dict["correlation_id"] = correlation_id_ctx.get()
    event_dict["session_id"] = session_id_ctx.get()
    event_dict["request_id"] = request_id_ctx.get()
    return event_dict


_CONFIGURED = False


def configure_logging() -> None:
    """One-time structlog + stdlib logging configuration.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _CONFIGURED  # noqa: PLW0603
    if _CONFIGURED:
        return
    _CONFIGURED = True

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_context_vars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.log_format == "json":
        renderer: structlog.types.Processor = (
            structlog.processors.JSONRenderer()
        )
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure stdlib root logger so third-party libs also emit
    # structured output through the same pipeline.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )

    # Quiet noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger, auto-configuring on first call."""
    configure_logging()
    return structlog.get_logger(name or __name__)
