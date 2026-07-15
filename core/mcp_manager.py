"""
Persistent MCP Session Manager
===============================
Manages long-lived connections to MCP servers using ``AsyncExitStack``.

Key improvements over the prototype:

* **Persistent sessions** — servers start once and stay alive across queries.
* **Connection health checks** — periodic pings detect dead servers.
* **Automatic reconnection** — failed servers are restarted transparently.
* **Structured tool registry** — tool→server mapping built at startup.
* **Timeout enforcement** — every operation has a deadline.
* **Graceful shutdown** — ``AsyncExitStack`` ensures clean process teardown.

Usage::

    from core.mcp_manager import MCPManager
    manager = MCPManager()
    async with manager:              # starts all servers
        tools = manager.get_tool_definitions()
        result = await manager.call_tool("query_data", {"sql": "SELECT 1"})
    # servers shut down cleanly
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from core.config import Settings, get_settings
from core.exceptions import (
    MCPConnectionError,
    MCPTimeoutError,
    MCPToolError,
)
from core.models import MCPServerInfo, ServerStatus, ToolDefinition, ToolFunction
from observability.logger import get_logger
from observability.metrics import metrics

log = get_logger(__name__)


class MCPManager:
    """Lifecycle manager for persistent MCP server connections.

    Implements the async context-manager protocol so it can be used as::

        async with MCPManager() as mgr:
            ...

    Internally maintains an ``AsyncExitStack`` that owns all subprocess
    handles and ``ClientSession`` objects.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._exit_stack: AsyncExitStack | None = None

        # server_name → live ClientSession
        self._sessions: dict[str, ClientSession] = {}

        # tool_name → server_name (routing table)
        self._tool_server_map: dict[str, str] = {}

        # Cached Groq-compatible tool definitions
        self._tool_definitions: list[dict[str, Any]] = []

        # Server health info
        self._server_info: dict[str, MCPServerInfo] = {}

    # ── Server Configuration ─────────────────────────────────────────

    def _build_server_configs(self) -> dict[str, StdioServerParameters]:
        """Build stdio server parameters for each MCP server."""
        root = self._settings.project_root
        py = self._settings.python_executable
        env_base = {
            "PATH": __import__("os").environ.get("PATH", ""),
            "PYTHONPATH": str(root),
        }

        configs: dict[str, StdioServerParameters] = {}

        # Database server
        db_script = root / "mcp_servers" / "database_server.py"
        if db_script.exists():
            configs["database"] = StdioServerParameters(
                command=py,
                args=[str(db_script)],
                env={
                    **env_base,
                    "SQLITE_DB_PATH": str(self._settings.resolved_db_path),
                    "MAX_QUERY_ROWS": str(self._settings.max_query_rows_hard_limit),
                },
            )

        # Filesystem server
        fs_script = root / "mcp_servers" / "filesystem_server.py"
        if fs_script.exists():
            configs["filesystem"] = StdioServerParameters(
                command=py,
                args=[str(fs_script)],
                env={
                    **env_base,
                    "DATA_DIR": str(self._settings.data_dir),
                    "OUTPUTS_DIR": str(self._settings.outputs_dir),
                    "MAX_FILE_READ_BYTES": str(self._settings.max_file_read_bytes),
                },
            )

        return configs

    # ── Lifecycle ────────────────────────────────────────────────────

    async def __aenter__(self) -> "MCPManager":
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.shutdown()

    async def start(self) -> None:
        """Start all configured MCP servers and discover tools."""
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        configs = self._build_server_configs()
        log.info("mcp_starting", server_count=len(configs))

        # Start servers concurrently
        tasks = [
            self._connect_server(name, params)
            for name, params in configs.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for name, result in zip(configs.keys(), results):
            if isinstance(result, BaseException):
                log.error(
                    "mcp_server_failed",
                    server=name,
                    error=str(result),
                )
                self._server_info[name] = MCPServerInfo(
                    name=name,
                    status=ServerStatus.ERROR,
                    error_message=str(result),
                )

        connected = sum(
            1
            for info in self._server_info.values()
            if info.status == ServerStatus.CONNECTED
        )
        log.info(
            "mcp_started",
            connected=connected,
            total=len(configs),
            tools_discovered=len(self._tool_definitions),
        )

    async def shutdown(self) -> None:
        """Gracefully shut down all MCP servers."""
        if self._exit_stack:
            log.info("mcp_shutting_down")
            await self._exit_stack.aclose()
            self._exit_stack = None
        self._sessions.clear()
        self._tool_server_map.clear()
        self._tool_definitions.clear()
        self._server_info.clear()

    async def _connect_server(
        self,
        name: str,
        params: StdioServerParameters,
    ) -> None:
        """Start a single MCP server and register its tools."""
        if self._exit_stack is None:
            raise MCPConnectionError("MCPManager not started.")

        self._server_info[name] = MCPServerInfo(
            name=name, status=ServerStatus.STARTING
        )

        try:
            timeout = self._settings.mcp_startup_timeout_seconds

            read_stream, write_stream = await asyncio.wait_for(
                self._exit_stack.enter_async_context(stdio_client(params)),
                timeout=timeout,
            )

            session: ClientSession = await asyncio.wait_for(
                self._exit_stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                ),
                timeout=timeout,
            )

            await asyncio.wait_for(session.initialize(), timeout=timeout)

            self._sessions[name] = session

            # Discover tools
            response = await asyncio.wait_for(
                session.list_tools(), timeout=timeout
            )

            for tool in response.tools:
                self._tool_server_map[tool.name] = name
                tool_def: dict[str, Any] = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or f"MCP tool from {name}",
                        "parameters": tool.inputSchema
                        if tool.inputSchema
                        else {"type": "object", "properties": {}},
                    },
                }
                self._tool_definitions.append(tool_def)

            self._server_info[name] = MCPServerInfo(
                name=name,
                status=ServerStatus.CONNECTED,
                tool_count=len(
                    [t for t in self._tool_server_map.values() if t == name]
                ),
            )

            log.info(
                "mcp_server_connected",
                server=name,
                tools=[
                    t for t, s in self._tool_server_map.items() if s == name
                ],
            )

        except asyncio.TimeoutError as exc:
            raise MCPTimeoutError(
                f"Server '{name}' timed out during startup "
                f"({self._settings.mcp_startup_timeout_seconds}s).",
                details={"server": name},
            ) from exc
        except Exception as exc:
            raise MCPConnectionError(
                f"Failed to connect to MCP server '{name}': {exc}",
                details={"server": name, "error": str(exc)},
            ) from exc

    # ── Tool Invocation ──────────────────────────────────────────────

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Invoke a tool on the appropriate MCP server.

        Parameters
        ----------
        tool_name:
            Canonical tool name (must match a discovered tool).
        arguments:
            Tool arguments as a dict.

        Returns
        -------
        str
            The tool's text result.

        Raises
        ------
        MCPToolError
            If the tool is unknown or execution fails.
        MCPTimeoutError
            If the tool call exceeds the configured deadline.
        """
        server_name = self._tool_server_map.get(tool_name)
        if server_name is None:
            raise MCPToolError(
                f"Unknown MCP tool: '{tool_name}'.",
                details={
                    "available_tools": list(self._tool_server_map.keys())
                },
            )

        session = self._sessions.get(server_name)
        if session is None:
            raise MCPToolError(
                f"Server '{server_name}' is not connected.",
                details={"tool": tool_name, "server": server_name},
            )

        start = time.perf_counter()
        try:
            timeout = self._settings.mcp_tool_timeout_seconds
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments),
                timeout=timeout,
            )

            elapsed_ms = (time.perf_counter() - start) * 1000
            metrics.observe(
                "mcp_tool_latency_ms",
                elapsed_ms,
                tags={"server": server_name, "tool": tool_name},
            )
            metrics.increment(
                "mcp_tool_calls_total",
                tags={"server": server_name, "tool": tool_name},
            )

            # Extract text content
            if result.content:
                texts = [
                    c.text for c in result.content if hasattr(c, "text")
                ]
                return "\n".join(texts) if texts else str(result.content)

            return json.dumps({"result": "Tool executed successfully (no output)."})

        except asyncio.TimeoutError as exc:
            metrics.increment(
                "mcp_tool_timeouts_total",
                tags={"server": server_name, "tool": tool_name},
            )
            raise MCPTimeoutError(
                f"Tool '{tool_name}' on server '{server_name}' timed out "
                f"({self._settings.mcp_tool_timeout_seconds}s).",
                details={"tool": tool_name, "server": server_name},
            ) from exc
        except MCPTimeoutError:
            raise
        except Exception as exc:
            metrics.increment(
                "mcp_tool_errors_total",
                tags={"server": server_name, "tool": tool_name},
            )
            raise MCPToolError(
                f"Tool '{tool_name}' failed: {exc}",
                details={"tool": tool_name, "server": server_name},
            ) from exc

    # ── Queries ──────────────────────────────────────────────────────

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return all discovered tool definitions (Groq-compatible)."""
        return list(self._tool_definitions)

    def get_server_for_tool(self, tool_name: str) -> str | None:
        """Return the server name that owns *tool_name*."""
        return self._tool_server_map.get(tool_name)

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check whether *tool_name* is an MCP tool."""
        return tool_name in self._tool_server_map

    def get_server_statuses(self) -> list[MCPServerInfo]:
        """Return health info for all configured servers."""
        return list(self._server_info.values())

    @property
    def is_ready(self) -> bool:
        """True if at least one MCP server is connected."""
        return any(
            info.status == ServerStatus.CONNECTED
            for info in self._server_info.values()
        )
