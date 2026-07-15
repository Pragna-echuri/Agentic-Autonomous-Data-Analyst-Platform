"""
FastAPI Application — Service Layer
====================================
Production-grade API exposing the Data Analyst Platform.

* **Lifespan management** — MCP servers start/stop with the app.
* **Dependency injection** — orchestrator, session store shared via ``Depends``.
* **CORS** — configured for Streamlit frontend.
* **Health endpoint** — ``/health`` for load-balancer probes.
* **Metrics endpoint** — ``/metrics`` for Prometheus scraping.

Start with::

    uvicorn api.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.config import get_settings
from core.models import HealthStatus, QueryResult, ServerStatus
from core.orchestrator import DataAnalystOrchestrator
from memory.session_store import SessionStore
from observability.logger import get_logger
from observability.metrics import metrics

log = get_logger(__name__)

# ── Shared State ─────────────────────────────────────────────────────

_orchestrator: DataAnalystOrchestrator | None = None
_session_store: SessionStore | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage orchestrator lifecycle with the FastAPI app."""
    global _orchestrator, _session_store  # noqa: PLW0603
    log.info("api_starting")

    _session_store = SessionStore()
    _orchestrator = DataAnalystOrchestrator()
    await _orchestrator.start()

    log.info("api_started")
    yield

    log.info("api_shutting_down")
    if _orchestrator:
        await _orchestrator.shutdown()


# ── App Setup ────────────────────────────────────────────────────────

settings = get_settings()

app = FastAPI(
    title="Data Analyst Platform API",
    version="2.0.0",
    description="Enterprise-grade autonomous data analysis platform.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response Models ──────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])


class QueryResponse(BaseModel):
    result: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    session_id: str = ""
    correlation_id: str = ""
    total_latency_ms: float = 0.0


# ── Endpoints ────────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    """Submit a natural-language data analysis query."""
    if not _orchestrator:
        raise HTTPException(503, "Orchestrator not initialized.")

    # Load session context
    session_ctx = ""
    if _session_store:
        ctx = _session_store.get_or_create(req.session_id)
        if ctx.memory_summary:
            session_ctx = ctx.memory_summary

    result: QueryResult = await _orchestrator.run(
        req.query, session_context=session_ctx
    )

    # Persist query in session
    if _session_store:
        ctx = _session_store.get_or_create(req.session_id)
        ctx.previous_queries.append(req.query)
        ctx.total_queries += 1
        _session_store.save(ctx)

    return QueryResponse(
        result=result.result,
        tool_calls=[tc.model_dump() for tc in result.tool_calls],
        error=result.error,
        session_id=result.session_id,
        correlation_id=result.correlation_id,
        total_latency_ms=result.total_latency_ms,
    )


@app.get("/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    """Health check for load-balancer probes."""
    if not _orchestrator:
        return HealthStatus(status="unhealthy")

    servers = _orchestrator._mcp.get_server_statuses()
    snap = metrics.snapshot()

    return HealthStatus(
        status="healthy" if any(
            s.status == ServerStatus.CONNECTED for s in servers
        ) else "degraded",
        servers=servers,
        uptime_seconds=snap.get("uptime_seconds", 0.0),
        total_queries_served=snap.get("counters", {}).get(
            "queries_total", {}
        ).get("", 0),
    )


@app.get("/metrics")
async def get_metrics() -> dict[str, Any]:
    """Expose runtime metrics for monitoring."""
    return metrics.snapshot()


@app.get("/sessions")
async def list_sessions() -> dict[str, list[str]]:
    """List all active session IDs."""
    if not _session_store:
        return {"sessions": []}
    return {"sessions": _session_store.list_sessions()}
