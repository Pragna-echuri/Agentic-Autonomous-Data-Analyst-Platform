"""
MCP-Powered Data Analyst Agent
==============================
A lightweight orchestrator that uses:
    1. MCP Python SDK for database & filesystem access (via stdio servers)
    2. Groq LLM for reasoning and tool-calling
    3. Reflection module for code self-critique
    4. Legacy tools for visualization and EDA

Architecture:
    User query → LLM reasons → Selects tool → Route to MCP server or legacy tool
    → Get result → LLM synthesizes answer → Return to user

NO CrewAI dependency — uses raw MCP Python SDK + Groq function calling.
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from groq import Groq

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tools import LEGACY_TOOLS, execute_legacy_tool
from reflection import ReflectionEngine

load_dotenv()

# ─── Configuration ───────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
REFLECTION_ENABLED = os.getenv("REFLECTION_ENABLED", "true").lower() == "true"
PYTHON_EXE = sys.executable


# ═══════════════════════════════════════════════════════════════════════
# MCP Host — Manages connections to MCP servers
# ═══════════════════════════════════════════════════════════════════════

class MCPHost:
    """
    Manages MCP server connections and provides a unified tool interface.

    Each MCP server runs as a subprocess via stdio transport. The host
    discovers available tools from ALL servers and routes tool calls
    to the correct server session.
    """

    def __init__(self):
        self.server_configs = {
            "database": StdioServerParameters(
                command=PYTHON_EXE,
                args=[str(PROJECT_ROOT / "mcp_servers" / "sqlite_server.py")],
                env={
                    "SQLITE_DB_PATH": str(PROJECT_ROOT / "data" / "example.db"),
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONPATH": str(PROJECT_ROOT),
                },
            ),
            "filesystem": StdioServerParameters(
                command=PYTHON_EXE,
                args=[str(PROJECT_ROOT / "mcp_servers" / "filesystem_server.py")],
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONPATH": str(PROJECT_ROOT),
                },
            ),
        }
        # Cache: tool_name → server_name
        self._tool_server_map: dict[str, str] = {}
        # Cache: tool definitions for Groq
        self._tool_definitions: list[dict] = []

    async def discover_tools(self) -> list[dict]:
        """Connect to all MCP servers, discover their tools, and return Groq-compatible definitions."""
        all_tools = []

        for server_name, params in self.server_configs.items():
            try:
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        response = await session.list_tools()

                        for tool in response.tools:
                            # Map tool → server for routing
                            self._tool_server_map[tool.name] = server_name

                            # Convert MCP tool schema to Groq function-calling format
                            tool_def = {
                                "type": "function",
                                "function": {
                                    "name": tool.name,
                                    "description": tool.description or f"MCP tool from {server_name}",
                                    "parameters": tool.inputSchema if tool.inputSchema else {
                                        "type": "object",
                                        "properties": {},
                                    },
                                },
                            }
                            all_tools.append(tool_def)

            except Exception as e:
                print(f"⚠️ Failed to connect to {server_name} MCP server: {e}", file=sys.stderr)

        self._tool_definitions = all_tools
        return all_tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the appropriate MCP server."""
        server_name = self._tool_server_map.get(tool_name)
        if not server_name:
            return json.dumps({"error": f"Unknown MCP tool: {tool_name}"})

        params = self.server_configs[server_name]

        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)

                    # Extract text content from result
                    if result.content:
                        texts = [c.text for c in result.content if hasattr(c, "text")]
                        return "\n".join(texts) if texts else str(result.content)
                    return json.dumps({"result": "Tool executed successfully (no output)"})

        except Exception as e:
            return json.dumps({"error": f"MCP tool call failed: {str(e)}"})

    def get_tool_definitions(self) -> list[dict]:
        """Get cached Groq-compatible tool definitions."""
        return self._tool_definitions

    def get_server_for_tool(self, tool_name: str) -> Optional[str]:
        """Get which server a tool belongs to."""
        return self._tool_server_map.get(tool_name)


# ═══════════════════════════════════════════════════════════════════════
# Data Analyst Orchestrator
# ═══════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are an expert Data Analyst Agent with access to powerful tools for database querying, file operations, data analysis, and visualization.

## Your Capabilities:
1. **Database Tools** (via MCP SQLite Server):
   - `list_tables`: See all tables in the database
   - `describe_table`: Get schema and sample data for a table
   - `query_data`: Run SELECT queries safely
   - `execute_write`: Run INSERT/UPDATE/DELETE (use carefully)
   - `get_database_info`: Get full database overview

2. **Filesystem Tools** (via MCP Filesystem Server):
   - `list_directory`: See available files in data/ and outputs/
   - `read_file`: Read text/CSV files
   - `write_file`: Save files to outputs/
   - `read_csv_preview`: Quick preview of CSV data
   - `get_csv_stats`: Summary statistics for CSV numeric columns

3. **Analysis & Visualization Tools** (Legacy):
   - `generate_chart`: Create bar/scatter/line/histogram/box/heatmap/pie charts from CSV data
   - `run_pandas_eda`: Comprehensive Exploratory Data Analysis on CSV files
   - `export_report`: Save analysis as Markdown or HTML reports

## Your Workflow:
1. **Understand** the user's question
2. **Explore** the data first (list tables, preview CSVs)
3. **Query/Analyze** using the appropriate tools
4. **Visualize** if helpful
5. **Synthesize** a clear, insightful answer

## Rules:
- Always explore the data structure BEFORE querying
- Write efficient SQL queries
- Explain your reasoning and findings
- If a question is ambiguous, make reasonable assumptions and state them
- Format numbers nicely (currency, percentages, etc.)
"""


class DataAnalystOrchestrator:
    """
    Main orchestrator that coordinates MCP servers and Groq LLM.

    Flow:
        1. Discover tools from MCP servers + legacy tools
        2. Send user query + tool list to Groq
        3. Groq selects and calls tools
        4. Route tool calls to MCP or legacy handler
        5. Feed results back to Groq for synthesis
        6. Return final answer
    """

    def __init__(self):
        self.groq = Groq(api_key=GROQ_API_KEY)
        self.mcp_host = MCPHost()
        self.reflection = ReflectionEngine(self.groq) if REFLECTION_ENABLED else None
        self._tools_discovered = False

    async def _ensure_tools_discovered(self):
        """Lazily discover MCP tools on first query."""
        if not self._tools_discovered:
            await self.mcp_host.discover_tools()
            self._tools_discovered = True

    def _get_all_tools(self) -> list[dict]:
        """Get combined tool definitions from MCP + legacy."""
        return self.mcp_host.get_tool_definitions() + LEGACY_TOOLS

    async def _handle_tool_call(self, tool_name: str, arguments: dict) -> str:
        """Route a tool call to MCP server or legacy handler."""
        # Check if it's an MCP tool
        server = self.mcp_host.get_server_for_tool(tool_name)
        if server:
            return await self.mcp_host.call_tool(tool_name, arguments)

        # Otherwise, try legacy tools
        return execute_legacy_tool(tool_name, arguments)

    async def run(self, query: str) -> dict:
        """Execute a query through the full agent pipeline.

        Args:
            query: Natural language question from the user.

        Returns:
            dict with: result, tool_calls, reflection_log, error
        """
        await self._ensure_tools_discovered()

        result = {
            "query": query,
            "result": "",
            "tool_calls": [],
            "reflection_log": [],
            "error": None,
        }

        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ]

            all_tools = self._get_all_tools()
            max_iterations = 10  # Safety limit for tool-calling loops

            for iteration in range(max_iterations):
                # Call Groq with tool definitions
                response = self.groq.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=messages,
                    tools=all_tools if all_tools else None,
                    tool_choice="auto" if all_tools else None,
                    temperature=0.3,
                    max_tokens=4096,
                )

                msg = response.choices[0].message

                # If no tool calls, we have the final answer
                if not msg.tool_calls:
                    result["result"] = msg.content or "No response generated."
                    break

                # Process tool calls
                messages.append(msg)  # Add assistant message with tool calls

                for tool_call in msg.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments)

                    # Reflection step for SQL queries
                    if self.reflection and fn_name == "query_data" and "sql" in fn_args:
                        reflection_result = self.reflection.reflect_on_sql(
                            fn_args["sql"],
                            user_intent=query,
                        )
                        result["reflection_log"].extend(reflection_result.critique_log)
                        fn_args["sql"] = reflection_result.final_code

                    # Execute the tool
                    tool_result = await self._handle_tool_call(fn_name, fn_args)

                    result["tool_calls"].append({
                        "tool": fn_name,
                        "arguments": fn_args,
                        "server": self.mcp_host.get_server_for_tool(fn_name) or "legacy",
                        "result_preview": tool_result[:500] if tool_result else "",
                    })

                    # Add tool result back to conversation
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result,
                    })

            else:
                # Max iterations reached
                result["result"] = msg.content or "Agent reached maximum iterations."

        except Exception as e:
            result["error"] = str(e)
            result["result"] = f"❌ Error: {str(e)}"

        return result

    def run_sync(self, query: str) -> dict:
        """Synchronous wrapper for run()."""
        return asyncio.run(self.run(query))


# ═══════════════════════════════════════════════════════════════════════
# Convenience Functions
# ═══════════════════════════════════════════════════════════════════════

def run_query(query: str) -> dict:
    """Run a query through the Data Analyst Agent.

    Args:
        query: Natural language data question.

    Returns:
        dict with result, tool_calls, reflection_log, error.
    """
    orchestrator = DataAnalystOrchestrator()
    return orchestrator.run_sync(query)


# ─── CLI Entry Point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🔬 Data Analyst Agent (MCP + Groq)")
    print("═" * 55)
    print(f"   Model: {GROQ_MODEL}")
    print(f"   Reflection: {'ON' if REFLECTION_ENABLED else 'OFF'}")
    print("═" * 55)

    orchestrator = DataAnalystOrchestrator()

    while True:
        query = input("\n💬 Your question (or 'exit'): ").strip()
        if query.lower() in ("exit", "quit", "q"):
            print("👋 Goodbye!")
            break

        print(f"\n🔄 Processing...\n")
        result = orchestrator.run_sync(query)

        if result["error"]:
            print(f"❌ Error: {result['error']}")
        else:
            # Show tool calls
            if result["tool_calls"]:
                print("🔧 Tools Used:")
                for tc in result["tool_calls"]:
                    print(f"   • {tc['tool']} ({tc['server']})")

            # Show reflection
            if result["reflection_log"]:
                print("\n🔍 Reflection Steps:")
                for entry in result["reflection_log"]:
                    iteration = entry.get("iteration", "?")
                    reflection = entry.get("reflection", {})
                    approved = reflection.get("approved", "?")
                    print(f"   Iteration {iteration}: {'✅ Approved' if approved else '🔄 Corrected'}")

            print(f"\n{'─' * 55}")
            print(result["result"])
            print(f"{'─' * 55}")
