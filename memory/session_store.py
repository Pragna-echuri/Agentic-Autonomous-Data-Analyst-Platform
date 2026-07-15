"""
Session Store
=============
SQLite-backed persistent session memory.

Stores user goals, data schemas, previous queries, generated files,
and LLM-generated session summaries.  Survives browser refreshes
and server restarts.

Usage::

    from memory.session_store import SessionStore
    store = SessionStore()
    ctx = store.get_or_create("session-abc")
    ctx.previous_queries.append("SELECT ...")
    store.save(ctx)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.config import get_settings
from core.models import SessionContext
from observability.logger import get_logger

log = get_logger(__name__)


class SessionStore:
    """SQLite-backed session persistence."""

    def __init__(self, db_path: Path | None = None) -> None:
        settings = get_settings()
        self._db_path = db_path or (settings.outputs_dir / ".sessions.db")
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path))

    def _ensure_schema(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def get_or_create(self, session_id: str) -> SessionContext:
        """Load an existing session or create a new one."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT data FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()

        if row:
            try:
                return SessionContext.model_validate_json(row[0])
            except Exception:
                log.warning("session_corrupt", session_id=session_id)

        return SessionContext(session_id=session_id)

    def save(self, ctx: SessionContext) -> None:
        """Persist a session context."""
        ctx.updated_at = datetime.now(timezone.utc)
        data = ctx.model_dump_json()
        now = datetime.now(timezone.utc).isoformat()

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, data, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (ctx.session_id, data, ctx.created_at.isoformat(), now),
            )
            conn.commit()

        log.debug("session_saved", session_id=ctx.session_id)

    def delete(self, session_id: str) -> None:
        """Delete a session."""
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()

    def list_sessions(self) -> list[str]:
        """Return all session IDs."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT session_id FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
        return [r[0] for r in rows]
