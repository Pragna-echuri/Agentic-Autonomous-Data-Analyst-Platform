"""
Tool Registry
=============
Central registry that provides:

* Groq-compatible tool definitions (JSON schema) for all legacy tools.
* Type-safe dispatch with input validation.
* A single source of truth for tool metadata.

The registry auto-generates tool schemas from the implementations in
``visualization``, ``analysis``, and ``reporting``.  The orchestrator
merges these with MCP-discovered tools before sending to the LLM.

Usage::

    from core.tools.registry import ToolRegistry
    registry = ToolRegistry()
    definitions = registry.get_definitions()
    result = registry.execute("generate_chart", {"chart_type": "bar", ...})
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from core.exceptions import ToolExecutionError, ToolNotFoundError, ToolValidationError
from core.models import ToolCallRecord
from core.tools.analysis import run_pandas_eda
from core.tools.reporting import export_report
from core.tools.visualization import generate_chart
from observability.logger import get_logger
from observability.metrics import metrics

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  Tool Schema Definitions (Groq function-calling format)
# ═══════════════════════════════════════════════════════════════════════

_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "generate_chart",
            "description": (
                "Generate a chart from CSV data and save it as a PNG image. "
                "Supported types: bar, scatter, line, histogram, box, heatmap, pie."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "enum": ["bar", "scatter", "line", "histogram", "box", "heatmap", "pie"],
                        "description": "The type of chart to create.",
                    },
                    "csv_path": {
                        "type": "string",
                        "description": "Path to CSV file relative to data/ directory (e.g., 'sample.csv').",
                    },
                    "x_column": {
                        "type": "string",
                        "description": "Column name for the x-axis.",
                    },
                    "y_column": {
                        "type": "string",
                        "description": "Column name for the y-axis (optional for histogram/pie).",
                        "default": "",
                    },
                    "title": {
                        "type": "string",
                        "description": "Title for the chart.",
                        "default": "Chart",
                    },
                    "hue_column": {
                        "type": "string",
                        "description": "Optional column for colour grouping.",
                        "default": "",
                    },
                },
                "required": ["chart_type", "csv_path", "x_column"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_pandas_eda",
            "description": (
                "Perform comprehensive Exploratory Data Analysis on a CSV file. "
                "Returns shape, dtypes, summary statistics, missing values, "
                "correlations, and categorical summaries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "csv_path": {
                        "type": "string",
                        "description": "Path to CSV file relative to data/ directory.",
                    },
                },
                "required": ["csv_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_report",
            "description": "Export analysis content as a Markdown or HTML report file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The report content to export.",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Name for the output file (without extension).",
                        "default": "report",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["markdown", "html"],
                        "description": "Output format.",
                        "default": "markdown",
                    },
                },
                "required": ["content"],
            },
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════
#  Registry
# ═══════════════════════════════════════════════════════════════════════

class ToolRegistry:
    """Manages legacy (non-MCP) tool definitions and dispatch."""

    def __init__(self) -> None:
        self._dispatch: dict[str, Callable[..., str]] = {
            "generate_chart": generate_chart,
            "run_pandas_eda": run_pandas_eda,
            "export_report": export_report,
        }

    def get_definitions(self) -> list[dict[str, Any]]:
        """Return Groq-compatible tool definitions."""
        return list(_TOOL_DEFINITIONS)

    def has_tool(self, name: str) -> bool:
        """Check if *name* is a registered legacy tool."""
        return name in self._dispatch

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallRecord:
        """Execute a legacy tool with validated arguments.

        Returns
        -------
        ToolCallRecord
            Contains the result preview, latency, and error info.

        Raises
        ------
        ToolNotFoundError
            If the tool name is not registered.
        """
        func = self._dispatch.get(tool_name)
        if func is None:
            raise ToolNotFoundError(
                f"Unknown legacy tool: '{tool_name}'.",
                details={"available": list(self._dispatch.keys())},
            )

        start = time.perf_counter()
        error_msg: str | None = None
        result_str = ""

        try:
            result_str = func(**arguments)
        except TypeError as exc:
            error_msg = f"Invalid arguments for '{tool_name}': {exc}"
            result_str = json.dumps({"error": error_msg})
            log.warning(
                "tool_validation_error",
                tool=tool_name,
                error=str(exc),
            )
        except Exception as exc:
            error_msg = f"Tool execution error: {exc}"
            result_str = json.dumps({"error": error_msg})
            log.error(
                "tool_execution_error",
                tool=tool_name,
                error=str(exc),
                exc_info=True,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000

        metrics.observe(
            "tool_latency_ms",
            elapsed_ms,
            tags={"tool": tool_name},
        )
        metrics.increment("tool_calls_total", tags={"tool": tool_name})

        return ToolCallRecord(
            tool_name=tool_name,
            arguments=arguments,
            server="legacy",
            result_preview=result_str[:500],
            latency_ms=round(elapsed_ms, 2),
            error=error_msg,
        )
