"""
Unit Tests — Domain Models
===========================
Tests for Pydantic model validation in ``core.models``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

from core.models import (
    ChartType,
    ColumnProfile,
    HealthStatus,
    IngestionResult,
    MCPServerInfo,
    QueryResult,
    ReflectionResult,
    ReflectionVerdict,
    ReportFormat,
    RiskLevel,
    ServerStatus,
    SessionContext,
    ToolCallRecord,
    ToolDefinition,
    ToolFunction,
)


class TestEnums:
    def test_risk_level_values(self) -> None:
        assert RiskLevel.LOW == "low"
        assert RiskLevel.HIGH == "high"

    def test_chart_type_values(self) -> None:
        assert ChartType.BAR == "bar"
        assert ChartType.SCATTER == "scatter"

    def test_server_status_values(self) -> None:
        assert ServerStatus.CONNECTED == "connected"
        assert ServerStatus.ERROR == "error"

    def test_report_format_values(self) -> None:
        assert ReportFormat.MARKDOWN == "markdown"
        assert ReportFormat.HTML == "html"


class TestToolCallRecord:
    def test_defaults(self) -> None:
        record = ToolCallRecord(tool_name="query_data")
        assert record.server == "legacy"
        assert record.arguments == {}
        assert record.error is None
        assert record.latency_ms == 0.0

    def test_with_values(self) -> None:
        record = ToolCallRecord(
            tool_name="query_data",
            arguments={"sql": "SELECT 1"},
            server="database",
            latency_ms=42.5,
        )
        assert record.tool_name == "query_data"
        assert record.server == "database"

    def test_frozen(self) -> None:
        record = ToolCallRecord(tool_name="test")
        with pytest.raises(Exception):
            record.tool_name = "changed"  # type: ignore


class TestToolDefinition:
    def test_creation(self) -> None:
        func = ToolFunction(name="test_tool", description="A test tool")
        defn = ToolDefinition(function=func)
        assert defn.type == "function"
        assert defn.function.name == "test_tool"


class TestReflectionVerdict:
    def test_defaults(self) -> None:
        verdict = ReflectionVerdict()
        assert verdict.approved is True
        assert verdict.risk_level == RiskLevel.LOW
        assert verdict.issues == []

    def test_rejection(self) -> None:
        verdict = ReflectionVerdict(
            approved=False,
            risk_level=RiskLevel.HIGH,
            issues=["Dangerous SQL detected"],
        )
        assert verdict.approved is False
        assert len(verdict.issues) == 1


class TestReflectionResult:
    def test_approved(self) -> None:
        result = ReflectionResult(
            original_code="SELECT 1",
            final_code="SELECT 1",
            is_approved=True,
        )
        assert result.is_approved is True
        assert result.risk_level == RiskLevel.LOW


class TestQueryResult:
    def test_defaults(self) -> None:
        result = QueryResult(query="test query")
        assert result.result == ""
        assert result.error is None
        assert result.tool_calls == []
        assert result.total_tokens_used == 0

    def test_with_error(self) -> None:
        result = QueryResult(query="bad query", error="Something broke")
        assert result.error == "Something broke"

    def test_session_id_generated(self) -> None:
        r1 = QueryResult(query="q1")
        r2 = QueryResult(query="q2")
        # Each should get a unique session_id
        assert len(r1.session_id) == 16
        assert len(r2.session_id) == 16


class TestSessionContext:
    def test_defaults(self) -> None:
        ctx = SessionContext()
        assert ctx.total_queries == 0
        assert ctx.previous_queries == []
        assert len(ctx.session_id) == 16

    def test_with_values(self) -> None:
        ctx = SessionContext(
            user_goal="Analyze sales data",
            total_queries=5,
        )
        assert ctx.user_goal == "Analyze sales data"
        assert ctx.total_queries == 5


class TestColumnProfile:
    def test_numeric_column(self) -> None:
        profile = ColumnProfile(
            name="salary",
            dtype="float64",
            null_count=2,
            null_percentage=1.5,
            unique_count=95,
            min_val=30000,
            max_val=200000,
            mean_val=85000,
        )
        assert profile.name == "salary"
        assert profile.min_val == 30000
        assert profile.top_values is None

    def test_categorical_column(self) -> None:
        profile = ColumnProfile(
            name="department",
            dtype="object",
            unique_count=5,
            top_values={"Engineering": 50, "Sales": 30},
        )
        assert profile.top_values is not None
        assert profile.min_val is None


class TestIngestionResult:
    def test_defaults(self) -> None:
        result = IngestionResult(filename="test.csv")
        assert result.row_count is None
        assert result.columns == []
        assert result.quality_warnings == []


class TestHealthStatus:
    def test_healthy(self) -> None:
        status = HealthStatus()
        assert status.status == "healthy"
        assert status.version == "2.0.0"

    def test_with_servers(self) -> None:
        server = MCPServerInfo(name="database", status=ServerStatus.CONNECTED, tool_count=3)
        status = HealthStatus(servers=[server])
        assert len(status.servers) == 1
        assert status.servers[0].tool_count == 3
