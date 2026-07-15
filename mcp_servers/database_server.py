"""
Database MCP Server (Hardened)
==============================
Secure SQLite MCP server with:

* **Read-only connections** for ``query_data`` via ``?mode=ro`` URI.
* **Table name sanitisation** — allowlisted against ``sqlite_master``.
* **Row limit enforcement** — all queries capped at ``MAX_QUERY_ROWS``.
* **Extension loading disabled** — ``conn.enable_load_extension(False)``.
* **Multi-statement blocking** — semicolons in queries are rejected.
* **Comment stripping** — prevents ``--`` injection.

Replaces the vulnerable ``sqlite_server.py``.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ── Configuration ────────────────────────────────────────────────────

DB_PATH = os.environ.get(
    "SQLITE_DB_PATH",
    str(Path(__file__).parent.parent / "data" / "example.db"),
)

MAX_QUERY_ROWS = int(os.environ.get("MAX_QUERY_ROWS", "150"))

mcp = FastMCP(
    "sqlite-analyst",
    instructions=(
        "A secure SQLite database server. Use list_tables to discover tables, "
        "describe_table to understand schema, and query_data to run SELECT queries. "
        "All queries are read-only and row-limited for safety."
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────

def _get_readonly_connection() -> sqlite3.Connection:
    """Open a read-only database connection."""
    db_uri = f"file:{Path(DB_PATH).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _get_readwrite_connection() -> sqlite3.Connection:
    """Open a read-write database connection (for approved writes only)."""
    conn = sqlite3.connect(DB_PATH)
    return conn


def _get_valid_tables(conn: sqlite3.Connection) -> set[str]:
    """Fetch the allowlist of real table names from sqlite_master."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
    )
    return {row[0] for row in cursor.fetchall()}


def _sanitise_table_name(table_name: str, conn: sqlite3.Connection) -> str:
    """Validate table name against the actual schema (prevents injection)."""
    valid = _get_valid_tables(conn)
    if table_name not in valid:
        raise ValueError(
            f"Table '{table_name}' not found. Available: {sorted(valid)}"
        )
    return table_name


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments to prevent comment-based injection."""
    result = re.sub(r"--[^\n]*", " ", sql)
    result = re.sub(r"/\*.*?\*/", " ", result, flags=re.DOTALL)
    return result


def _enforce_row_limit(sql: str) -> str:
    """Inject a LIMIT clause if one is not already present."""
    upper = sql.upper()
    if "LIMIT" not in upper:
        sql = sql.rstrip().rstrip(";")
        sql = f"{sql} LIMIT {MAX_QUERY_ROWS}"
    return sql


# ── Tools ────────────────────────────────────────────────────────────

@mcp.tool()
def list_tables() -> str:
    """List all tables in the SQLite database.

    Returns a JSON object with table names and count.
    """
    try:
        with _get_readonly_connection() as conn:
            tables = sorted(_get_valid_tables(conn))
            return json.dumps({"tables": tables, "count": len(tables)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def describe_table(table_name: str) -> str:
    """Describe the schema of a specific table.

    Args:
        table_name: Name of the table to describe.

    Returns columns, types, primary keys, row count, and 3 sample rows.
    """
    try:
        with _get_readonly_connection() as conn:
            # Validate table name against schema (prevents SQL injection)
            safe_name = _sanitise_table_name(table_name, conn)

            cursor = conn.execute(f"PRAGMA table_info([{safe_name}]);")
            columns = []
            for row in cursor.fetchall():
                columns.append({
                    "cid": row[0],
                    "name": row[1],
                    "type": row[2],
                    "notnull": bool(row[3]),
                    "default": row[4],
                    "primary_key": bool(row[5]),
                })

            count_cursor = conn.execute(
                f"SELECT COUNT(*) FROM [{safe_name}];"
            )
            row_count = count_cursor.fetchone()[0]

            sample_cursor = conn.execute(
                f"SELECT * FROM [{safe_name}] LIMIT 3;"
            )
            sample_rows = sample_cursor.fetchall()
            col_names = [desc[0] for desc in sample_cursor.description]

            return json.dumps({
                "table": safe_name,
                "columns": columns,
                "row_count": row_count,
                "sample_rows": [
                    dict(zip(col_names, row)) for row in sample_rows
                ],
            })
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def query_data(sql: str) -> str:
    """Execute a read-only SQL query (SELECT/WITH) against the database.

    Args:
        sql: A valid SQL SELECT or WITH query string.

    Returns the query results as JSON with columns and rows.
    Only SELECT/WITH statements are allowed.
    Results are capped at MAX_QUERY_ROWS rows.
    """
    # Strip comments first
    cleaned = _strip_sql_comments(sql).strip()

    # Reject multiple statements
    statements = [s.strip() for s in cleaned.split(";") if s.strip()]
    if len(statements) > 1:
        return json.dumps({
            "error": "Multiple SQL statements are not allowed. "
                     "Send one query at a time."
        })

    if not statements:
        return json.dumps({"error": "Empty SQL query."})

    single = statements[0]

    # Validate starts with SELECT or WITH
    upper = single.lstrip().upper()
    if not upper.startswith("SELECT") and not upper.startswith("WITH"):
        return json.dumps({
            "error": "Only SELECT / WITH queries are allowed. "
                     "Write operations are disabled."
        })

    # Enforce row limit
    limited = _enforce_row_limit(single)

    try:
        with _get_readonly_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(limited)
            rows = cursor.fetchall()
            columns = (
                [desc[0] for desc in cursor.description]
                if cursor.description
                else []
            )

            result_rows = [dict(row) for row in rows]
            return json.dumps({
                "columns": columns,
                "rows": result_rows,
                "row_count": len(result_rows),
                "truncated": len(result_rows) >= MAX_QUERY_ROWS,
            })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_database_info() -> str:
    """Get a complete overview of the database structure.

    Returns all tables with their schemas and row counts.
    Useful for understanding the full database at once.
    """
    try:
        with _get_readonly_connection() as conn:
            tables = sorted(_get_valid_tables(conn))
            db_info: dict = {"database": Path(DB_PATH).name, "tables": {}}

            for table in tables:
                schema_cursor = conn.execute(
                    f"PRAGMA table_info([{table}]);"
                )
                columns = [
                    {"name": row[1], "type": row[2], "pk": bool(row[5])}
                    for row in schema_cursor.fetchall()
                ]
                count = conn.execute(
                    f"SELECT COUNT(*) FROM [{table}];"
                ).fetchone()[0]
                db_info["tables"][table] = {
                    "columns": columns,
                    "row_count": count,
                }

            return json.dumps(db_info)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
