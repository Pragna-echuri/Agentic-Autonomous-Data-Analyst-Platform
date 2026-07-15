"""
Exception Hierarchy
===================
Structured exception types for the Data Analyst Platform.

Every exception carries a machine-readable ``error_code`` and an optional
``details`` dict so that upstream handlers (API layer, observability) can
produce actionable diagnostics without parsing free-text messages.

Hierarchy
---------
::

    DataAnalystError
    ├── ConfigurationError
    ├── MCPError
    │   ├── MCPConnectionError
    │   ├── MCPToolError
    │   └── MCPTimeoutError
    ├── LLMError
    │   ├── LLMRateLimitError
    │   ├── LLMContextOverflowError
    │   └── LLMProviderError
    ├── ToolError
    │   ├── ToolNotFoundError
    │   ├── ToolExecutionError
    │   └── ToolValidationError
    ├── SecurityError
    │   ├── PathTraversalError
    │   ├── SandboxViolationError
    │   └── SQLInjectionError
    ├── IngestionError
    │   ├── UnsupportedFormatError
    │   └── FileProcessingError
    └── SessionError
        └── SessionNotFoundError
"""

from __future__ import annotations

from typing import Any


# ═══════════════════════════════════════════════════════════════════════
#  Base
# ═══════════════════════════════════════════════════════════════════════

class DataAnalystError(Exception):
    """Base exception for every platform error."""

    error_code: str = "PLATFORM_ERROR"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.details: dict[str, Any] = details or {}
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON responses and structured logs."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }

    def __repr__(self) -> str:
        detail_str = f", details={self.details}" if self.details else ""
        return f"{type(self).__name__}({self.message!r}{detail_str})"


# ═══════════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════════

class ConfigurationError(DataAnalystError):
    """Invalid or missing configuration."""

    error_code = "CONFIG_ERROR"


# ═══════════════════════════════════════════════════════════════════════
#  MCP
# ═══════════════════════════════════════════════════════════════════════

class MCPError(DataAnalystError):
    """Base for MCP-related failures."""

    error_code = "MCP_ERROR"


class MCPConnectionError(MCPError):
    """Cannot establish or maintain an MCP server connection."""

    error_code = "MCP_CONNECTION_ERROR"


class MCPToolError(MCPError):
    """An MCP tool invocation failed."""

    error_code = "MCP_TOOL_ERROR"


class MCPTimeoutError(MCPError):
    """An MCP operation exceeded its deadline."""

    error_code = "MCP_TIMEOUT"


# ═══════════════════════════════════════════════════════════════════════
#  LLM
# ═══════════════════════════════════════════════════════════════════════

class LLMError(DataAnalystError):
    """Base for LLM provider failures."""

    error_code = "LLM_ERROR"


class LLMRateLimitError(LLMError):
    """Provider rate-limit hit — caller should back off."""

    error_code = "LLM_RATE_LIMIT"


class LLMContextOverflowError(LLMError):
    """Request exceeded the model's context window."""

    error_code = "LLM_CONTEXT_OVERFLOW"


class LLMProviderError(LLMError):
    """Unrecoverable provider-side error (5xx, network, etc.)."""

    error_code = "LLM_PROVIDER_ERROR"


# ═══════════════════════════════════════════════════════════════════════
#  Tools
# ═══════════════════════════════════════════════════════════════════════

class ToolError(DataAnalystError):
    """Base for tool execution failures."""

    error_code = "TOOL_ERROR"


class ToolNotFoundError(ToolError):
    """Requested tool does not exist in any registry."""

    error_code = "TOOL_NOT_FOUND"


class ToolExecutionError(ToolError):
    """A tool raised an exception during execution."""

    error_code = "TOOL_EXECUTION_ERROR"


class ToolValidationError(ToolError):
    """Tool arguments failed Pydantic validation."""

    error_code = "TOOL_VALIDATION_ERROR"


# ═══════════════════════════════════════════════════════════════════════
#  Security
# ═══════════════════════════════════════════════════════════════════════

class SecurityError(DataAnalystError):
    """Base for security-boundary violations."""

    error_code = "SECURITY_ERROR"


class PathTraversalError(SecurityError):
    """Attempted file access outside the sandbox boundary."""

    error_code = "PATH_TRAVERSAL"


class SandboxViolationError(SecurityError):
    """Generated code contains disallowed operations."""

    error_code = "SANDBOX_VIOLATION"


class SQLInjectionError(SecurityError):
    """Detected potential SQL injection pattern."""

    error_code = "SQL_INJECTION"


# ═══════════════════════════════════════════════════════════════════════
#  Ingestion
# ═══════════════════════════════════════════════════════════════════════

class IngestionError(DataAnalystError):
    """Base for file ingestion failures."""

    error_code = "INGESTION_ERROR"


class UnsupportedFormatError(IngestionError):
    """File type is not supported by the ingestion pipeline."""

    error_code = "UNSUPPORTED_FORMAT"


class FileProcessingError(IngestionError):
    """An error occurred while parsing or profiling a file."""

    error_code = "FILE_PROCESSING_ERROR"


# ═══════════════════════════════════════════════════════════════════════
#  Session / Memory
# ═══════════════════════════════════════════════════════════════════════

class SessionError(DataAnalystError):
    """Base for session management failures."""

    error_code = "SESSION_ERROR"


class SessionNotFoundError(SessionError):
    """Requested session does not exist or has expired."""

    error_code = "SESSION_NOT_FOUND"
