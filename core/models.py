"""
Domain Models
=============
Pydantic v2 models shared across the platform.  These are the canonical
data-transfer objects for tool calls, LLM interactions, query results,
session state, and ingestion artifacts.

Every model uses ``model_config = ConfigDict(frozen=True)`` where
immutability is desirable, and explicit ``Field(...)`` declarations for
every attribute — no bare annotations.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════════════════════════════════════
#  Enums
# ═══════════════════════════════════════════════════════════════════════

class RiskLevel(str, Enum):
    """Risk assessment for generated code."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class ChartType(str, Enum):
    """Supported chart types."""

    BAR = "bar"
    SCATTER = "scatter"
    LINE = "line"
    HISTOGRAM = "histogram"
    BOX = "box"
    HEATMAP = "heatmap"
    PIE = "pie"


class ReportFormat(str, Enum):
    """Report export formats."""

    MARKDOWN = "markdown"
    HTML = "html"


class ServerStatus(str, Enum):
    """MCP server connection state."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    STARTING = "starting"


class FileCategory(str, Enum):
    """Broad categories for ingested files."""

    TABULAR = "tabular"
    DOCUMENT = "document"
    IMAGE = "image"
    UNKNOWN = "unknown"


# ═══════════════════════════════════════════════════════════════════════
#  Tool Models
# ═══════════════════════════════════════════════════════════════════════

class ToolCallRecord(BaseModel):
    """Record of a single tool invocation during a query."""

    model_config = ConfigDict(frozen=True)

    tool_name: str = Field(..., description="Canonical tool name.")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Arguments passed to the tool."
    )
    server: str = Field(
        default="legacy",
        description="MCP server name or 'legacy' for host-side tools.",
    )
    result_preview: str = Field(
        default="",
        max_length=500,
        description="Truncated tool result for UI display.",
    )
    latency_ms: float = Field(
        default=0.0, description="Wall-clock execution time in ms."
    )
    error: str | None = Field(
        default=None, description="Error message if the call failed."
    )


class ToolDefinition(BaseModel):
    """Groq-compatible function-calling tool definition."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(default="function")
    function: ToolFunction = Field(...)  # type: ignore[assignment]


class ToolFunction(BaseModel):
    """Function metadata within a tool definition."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Tool function name.")
    description: str = Field(default="", description="Tool description.")
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON Schema for the function parameters.",
    )


# Fix forward reference — ToolDefinition needs ToolFunction defined first
ToolDefinition.model_rebuild()


# ═══════════════════════════════════════════════════════════════════════
#  Reflection Models
# ═══════════════════════════════════════════════════════════════════════

class ReflectionVerdict(BaseModel):
    """Structured output from the reflection engine's LLM review."""

    model_config = ConfigDict(frozen=True)

    approved: bool = Field(
        default=True, description="Whether the code passed review."
    )
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    issues: list[str] = Field(
        default_factory=list,
        description="List of issues found during review.",
    )
    corrected_code: str = Field(
        default="",
        description="Corrected code if changes were needed.",
    )
    explanation: str = Field(
        default="", description="Brief review explanation."
    )


class ReflectionCycleEntry(BaseModel):
    """One iteration of the reflection loop."""

    model_config = ConfigDict(frozen=True)

    iteration: int = Field(..., ge=1)
    verdict: ReflectionVerdict = Field(...)


class ReflectionResult(BaseModel):
    """Complete result of a reflection cycle."""

    model_config = ConfigDict(frozen=True)

    original_code: str = Field(...)
    final_code: str = Field(...)
    is_approved: bool = Field(default=True)
    iterations: int = Field(default=1, ge=1)
    critique_log: list[ReflectionCycleEntry] = Field(default_factory=list)
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)


# ═══════════════════════════════════════════════════════════════════════
#  Query / Orchestrator Models
# ═══════════════════════════════════════════════════════════════════════

class QueryResult(BaseModel):
    """Full result from the orchestrator for a single user query."""

    query: str = Field(..., description="Original user query.")
    result: str = Field(default="", description="Final synthesized answer.")
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    reflection_log: list[ReflectionCycleEntry] = Field(default_factory=list)
    error: str | None = Field(default=None)
    session_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:16],
    )
    correlation_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:16],
    )
    total_tokens_used: int = Field(default=0)
    total_latency_ms: float = Field(default=0.0)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


# ═══════════════════════════════════════════════════════════════════════
#  MCP Server Info
# ═══════════════════════════════════════════════════════════════════════

class MCPServerInfo(BaseModel):
    """Runtime status of a single MCP server."""

    name: str = Field(...)
    status: ServerStatus = Field(default=ServerStatus.DISCONNECTED)
    tool_count: int = Field(default=0)
    error_message: str | None = Field(default=None)
    last_health_check: datetime | None = Field(default=None)


# ═══════════════════════════════════════════════════════════════════════
#  Ingestion Models
# ═══════════════════════════════════════════════════════════════════════

class ColumnProfile(BaseModel):
    """Statistical profile of a single column."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(...)
    dtype: str = Field(default="unknown")
    null_count: int = Field(default=0)
    null_percentage: float = Field(default=0.0)
    unique_count: int = Field(default=0)
    sample_values: list[str] = Field(default_factory=list)
    # Numeric-only
    min_val: float | None = Field(default=None)
    max_val: float | None = Field(default=None)
    mean_val: float | None = Field(default=None)
    median_val: float | None = Field(default=None)
    std_val: float | None = Field(default=None)
    # Categorical-only
    top_values: dict[str, int] | None = Field(default=None)


class IngestionResult(BaseModel):
    """Metadata returned after ingesting a file (no raw data)."""

    filename: str = Field(...)
    file_category: FileCategory = Field(default=FileCategory.UNKNOWN)
    file_size_bytes: int = Field(default=0)
    row_count: int | None = Field(default=None)
    column_count: int | None = Field(default=None)
    columns: list[ColumnProfile] = Field(default_factory=list)
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)
    text_content: str | None = Field(
        default=None,
        description="Extracted text for PDFs/images (truncated).",
    )
    quality_warnings: list[str] = Field(default_factory=list)
    processing_time_ms: float = Field(default=0.0)


# ═══════════════════════════════════════════════════════════════════════
#  Session / Memory Models
# ═══════════════════════════════════════════════════════════════════════

class SessionContext(BaseModel):
    """Persisted session state for conversational memory."""

    session_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:16],
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    user_goal: str = Field(default="")
    data_schemas: list[dict[str, Any]] = Field(default_factory=list)
    previous_queries: list[str] = Field(default_factory=list)
    generated_files: list[str] = Field(default_factory=list)
    business_context: str = Field(default="")
    total_queries: int = Field(default=0)
    total_tokens: int = Field(default=0)
    memory_summary: str = Field(
        default="",
        description="LLM-generated summary of session history.",
    )


# ═══════════════════════════════════════════════════════════════════════
#  Health / API Models
# ═══════════════════════════════════════════════════════════════════════

class HealthStatus(BaseModel):
    """Platform health check response."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(default="healthy")
    version: str = Field(default="2.0.0")
    servers: list[MCPServerInfo] = Field(default_factory=list)
    uptime_seconds: float = Field(default=0.0)
    total_queries_served: int = Field(default=0)
