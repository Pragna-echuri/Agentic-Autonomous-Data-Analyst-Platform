"""
Application Configuration
=========================
Pydantic v2 ``BaseSettings`` providing type-safe, environment-aware
configuration for every platform subsystem.

Values are resolved in this order (highest-priority first):

1. Explicit constructor kwargs
2. Environment variables (case-insensitive)
3. ``.env`` file in the project root
4. Field defaults defined below

Usage::

    from core.config import get_settings
    settings = get_settings()          # cached singleton
    print(settings.groq_model)
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_project_root() -> Path:
    """Walk upward from this file to find the repository root.

    The root is identified by the presence of a ``data/`` directory
    (the data asset folder).  Falls back to the parent of ``core/``.
    """
    anchor = Path(__file__).resolve().parent.parent
    if (anchor / "data").is_dir():
        return anchor
    return anchor


class Settings(BaseSettings):
    """Centralised, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── LLM Provider ─────────────────────────────────────────────────
    groq_api_key: str = Field(
        default="",
        description="Groq API key for LLM inference.",
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model identifier.",
    )
    llm_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for LLM calls.",
    )
    llm_max_tokens: int = Field(
        default=4096,
        ge=256,
        le=32768,
        description="Maximum tokens in LLM response.",
    )
    llm_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="HTTP timeout for a single LLM API call.",
    )
    llm_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Max retry attempts for transient LLM failures.",
    )

    # ── Paths ────────────────────────────────────────────────────────
    project_root: Path | None = Field(default=None)
    data_dir: Path | None = Field(default=None)
    outputs_dir: Path | None = Field(default=None)
    sqlite_db_path: str = Field(
        default="data/example.db",
        description="Relative path to the SQLite demo database.",
    )

    # ── Reflection ───────────────────────────────────────────────────
    reflection_enabled: bool = Field(
        default=True,
        description="Enable the LLM self-critique loop for generated code.",
    )
    reflection_max_iterations: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Max reflection iterations before accepting code.",
    )

    # ── Safety Limits ────────────────────────────────────────────────
    max_tool_iterations: int = Field(
        default=10,
        ge=1,
        le=25,
        description="Max LLM ↔ tool round-trips per user query.",
    )
    max_query_rows: int = Field(
        default=100,
        ge=1,
        le=150,
        description="Soft cap on rows returned from database queries.",
    )
    max_query_rows_hard_limit: int = Field(
        default=150,
        ge=1,
        le=500,
        description="Absolute maximum rows — enforced by the DB server.",
    )
    max_file_read_bytes: int = Field(
        default=1_000_000,
        ge=1024,
        description="Max file size (bytes) for full-content reads.",
    )
    max_context_tokens: int = Field(
        default=6000,
        ge=500,
        le=30_000,
        description="Token budget for tool-result context injection.",
    )
    max_upload_size_bytes: int = Field(
        default=50_000_000,
        description="Max upload file size (50 MB default).",
    )

    # ── Logging ──────────────────────────────────────────────────────
    log_level: str = Field(
        default="INFO",
        description="Root log level (DEBUG, INFO, WARNING, ERROR).",
    )
    log_format: Literal["json", "console"] = Field(
        default="console",
        description="Log output format.",
    )

    # ── MCP ──────────────────────────────────────────────────────────
    mcp_startup_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Max wait for an MCP server subprocess to initialize.",
    )
    mcp_tool_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        description="Max wait for a single MCP tool call.",
    )
    mcp_health_check_interval_seconds: float = Field(
        default=60.0,
        gt=0,
        description="Interval between MCP server health pings.",
    )
    mcp_max_reconnect_attempts: int = Field(
        default=3,
        ge=0,
        description="Max consecutive reconnect attempts per server.",
    )

    # ── FastAPI ──────────────────────────────────────────────────────
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8501"],
        description="Allowed CORS origins (Streamlit default port).",
    )

    # ── Allowed Extensions ───────────────────────────────────────────
    allowed_upload_extensions: frozenset[str] = Field(
        default_factory=lambda: frozenset(
            {
                ".csv",
                ".xlsx",
                ".xls",
                ".json",
                ".jsonl",
                ".xml",
                ".pdf",
                ".png",
                ".jpg",
                ".jpeg",
                ".parquet",
                ".feather",
            }
        ),
        description="File extensions accepted by the ingestion pipeline.",
    )

    allowed_write_extensions: frozenset[str] = Field(
        default_factory=lambda: frozenset(
            {
                ".csv",
                ".json",
                ".md",
                ".html",
                ".txt",
                ".png",
                ".jpg",
                ".svg",
                ".pdf",
            }
        ),
        description="File extensions the agent is allowed to write.",
    )

    # ── Path Resolution ──────────────────────────────────────────────

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        if self.project_root is None:
            self.project_root = _find_project_root()

        if self.data_dir is None:
            self.data_dir = self.project_root / "data"

        if self.outputs_dir is None:
            self.outputs_dir = self.project_root / "outputs"

        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def resolved_db_path(self) -> Path:
        """Absolute path to the SQLite database file."""
        p = Path(self.sqlite_db_path)
        if p.is_absolute():
            return p
        return (self.project_root / p).resolve()

    @property
    def python_executable(self) -> str:
        """Path to the running Python interpreter."""
        return sys.executable


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application-wide settings singleton."""
    return Settings()
