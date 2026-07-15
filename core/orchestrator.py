"""
Data Analyst Orchestrator
=========================
Central coordination engine that binds together:

* Persistent MCP sessions for database and filesystem access
* Groq LLM for reasoning and tool selection
* Reflection engine for code self-critique
* Legacy tool registry for visualization and EDA
* Session memory for conversational context
* Token governance for context-window management

Pipeline::

    User query → Build context → LLM reasoning loop →
    Tool selection → Route (MCP / Legacy) → Reflection (SQL) →
    Execute → Feed result → LLM synthesis → Return

Usage::

    async with DataAnalystOrchestrator() as orch:
        result = await orch.run("What's the average salary by department?")
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from core.config import Settings, get_settings
from core.exceptions import DataAnalystError, ToolExecutionError
from core.llm_client import LLMClient
from core.mcp_manager import MCPManager
from core.models import (
    QueryResult,
    ReflectionCycleEntry,
    ToolCallRecord,
)
from core.prompts import SYSTEM_PROMPT, build_session_context, wrap_user_message
from core.reflection import ReflectionEngine
from core.tools.registry import ToolRegistry
from observability.logger import get_logger
from observability.metrics import metrics

log = get_logger(__name__)


class DataAnalystOrchestrator:
    """Async orchestrator coordinating MCP + LLM + Tools + Reflection.

    Implements the async context-manager protocol::

        async with DataAnalystOrchestrator() as orch:
            result = await orch.run("Show me sales trends")
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._llm = LLMClient(self._settings)
        self._mcp = MCPManager(self._settings)
        self._reflection = (
            ReflectionEngine(self._llm, self._settings)
            if self._settings.reflection_enabled
            else None
        )
        self._tools = ToolRegistry()

    # ── Lifecycle ────────────────────────────────────────────────────

    async def __aenter__(self) -> "DataAnalystOrchestrator":
        await self._mcp.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._mcp.shutdown()

    async def start(self) -> None:
        """Explicitly start the orchestrator (alternative to context manager)."""
        await self._mcp.start()

    async def shutdown(self) -> None:
        """Explicitly shut down the orchestrator."""
        await self._mcp.shutdown()

    # ── Main Query Pipeline ──────────────────────────────────────────

    async def run(
        self,
        query: str,
        *,
        session_context: str = "",
    ) -> QueryResult:
        """Execute a user query through the full agent pipeline.

        Parameters
        ----------
        query:
            Natural-language question from the user.
        session_context:
            Optional session memory context string.

        Returns
        -------
        QueryResult
            Complete result with answer, tool calls, reflection log, and metrics.
        """
        correlation_id = uuid.uuid4().hex[:16]
        start_time = time.perf_counter()

        metrics.increment("queries_total")
        log.info("query_started", query=query[:100], correlation_id=correlation_id)

        result = QueryResult(
            query=query,
            correlation_id=correlation_id,
        )

        try:
            # Build message history
            system_content = SYSTEM_PROMPT
            if session_context:
                system_content += "\n" + session_context

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": wrap_user_message(query)},
            ]

            # Merge MCP + legacy tool definitions
            all_tools = self._mcp.get_tool_definitions() + self._tools.get_definitions()

            # Reasoning loop
            tool_calls_collected: list[ToolCallRecord] = []
            reflection_log: list[ReflectionCycleEntry] = []

            for iteration in range(self._settings.max_tool_iterations):
                response = await self._llm.chat_completion(
                    messages,
                    tools=all_tools if all_tools else None,
                )

                msg = response.choices[0].message

                # Final answer — no tool calls
                if not msg.tool_calls:
                    result.result = msg.content or "No response generated."
                    break

                # Process tool calls
                messages.append(self._serialize_assistant_message(msg))

                for tool_call in msg.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments)

                    # Reflection gate for SQL queries
                    if (
                        self._reflection
                        and fn_name == "query_data"
                        and "sql" in fn_args
                    ):
                        ref_result = await self._reflection.reflect_on_sql(
                            fn_args["sql"],
                            user_intent=query,
                        )
                        reflection_log.extend(ref_result.critique_log)

                        if not ref_result.is_approved:
                            log.warning(
                                "reflection_blocked_sql",
                                sql=fn_args["sql"][:100],
                                risk=ref_result.risk_level.value,
                            )
                            tool_result_str = json.dumps({
                                "error": "SQL query was blocked by the safety reflection engine.",
                                "risk_level": ref_result.risk_level.value,
                                "issues": [
                                    e.verdict.explanation
                                    for e in ref_result.critique_log
                                ],
                            })
                        else:
                            fn_args["sql"] = ref_result.final_code
                            tool_result_str = await self._execute_tool(fn_name, fn_args)
                    else:
                        tool_result_str = await self._execute_tool(fn_name, fn_args)

                    # Build tool call record
                    server = self._mcp.get_server_for_tool(fn_name) or "legacy"
                    record = ToolCallRecord(
                        tool_name=fn_name,
                        arguments=fn_args,
                        server=server,
                        result_preview=tool_result_str[:500] if tool_result_str else "",
                    )
                    tool_calls_collected.append(record)

                    # Feed result back to LLM
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": self._truncate_for_context(tool_result_str),
                    })

            else:
                # Max iterations exhausted
                result.result = msg.content or "Agent reached maximum tool-calling iterations."

            result.tool_calls = tool_calls_collected
            result.reflection_log = reflection_log

        except DataAnalystError as exc:
            result.error = exc.message
            result.result = f"❌ {exc.message}"
            log.error(
                "query_error",
                error_code=exc.error_code,
                error=exc.message,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            result.error = str(exc)
            result.result = f"❌ Error: {exc}"
            log.error(
                "query_unhandled_error",
                error=str(exc),
                correlation_id=correlation_id,
                exc_info=True,
            )

        result.total_latency_ms = round(
            (time.perf_counter() - start_time) * 1000, 2
        )
        metrics.observe("query_latency_ms", result.total_latency_ms)

        log.info(
            "query_completed",
            correlation_id=correlation_id,
            latency_ms=result.total_latency_ms,
            tool_calls=len(result.tool_calls),
            error=result.error,
        )

        return result

    # ── Tool Execution ───────────────────────────────────────────────

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Route a tool call to MCP server or legacy registry."""
        if self._mcp.is_mcp_tool(tool_name):
            return await self._mcp.call_tool(tool_name, arguments)

        if self._tools.has_tool(tool_name):
            record = self._tools.execute(tool_name, arguments)
            return record.result_preview

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    # ── Helpers ──────────────────────────────────────────────────────

    def _truncate_for_context(self, text: str) -> str:
        """Truncate tool output to fit within the token budget.

        Uses a rough 1-token ≈ 4-chars heuristic.
        """
        max_chars = self._settings.max_context_tokens * 4
        if len(text) <= max_chars:
            return text

        metrics.increment("context_truncations_total")
        return (
            text[:max_chars]
            + "\n\n... [Output truncated to fit context budget. "
            f"Showing {max_chars} of {len(text)} characters.] ..."
        )

    @staticmethod
    def _serialize_assistant_message(msg: Any) -> dict[str, Any]:
        """Convert an LLM assistant message to a dict for the messages list."""
        serialized: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content or "",
        }
        if msg.tool_calls:
            serialized["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        return serialized
