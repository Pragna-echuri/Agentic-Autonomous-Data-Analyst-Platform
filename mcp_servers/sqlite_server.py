"""
SQLite MCP Server
=================
A pure Python MCP server using FastMCP that exposes SQLite database
operations as tools. Runs over stdio transport — no Node.js required.

Usage:
    python mcp_servers/sqlite_server.py

The server exposes these tools:
    - list_tables: Show all tables in the database
    - describe_table: Show schema for a specific table
    - query_data: Execute safe SELECT queries
    - execute_write: Execute INSERT/UPDATE/DELETE operations
"""

import os
import sys
import sqlite3
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# ─── Configuration ───────────────────────────────────────────────────────────
DB_PATH = os.environ.get(
    "SQLITE_DB_PATH",
    str(Path(__file__).parent.parent / "data" / "example.db")
)

# Initialize the FastMCP server
mcp = FastMCP(
    "sqlite-explorer",
    instructions=(
        "A SQLite database server. Use list_tables to discover tables, "
        "describe_table to understand schema, and query_data to run SELECT queries. "
        "Use execute_write only when the user explicitly requests data modifications."
    ),
)


# ─── Tools ───────────────────────────────────────────────────────────────────

@mcp.tool()
def list_tables() -> str:
    """List all tables in the SQLite database.

    Returns a JSON array of table names available for querying.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
            )
            tables = [row[0] for row in cursor.fetchall()]
            return json.dumps({"tables": tables, "count": len(tables)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def describe_table(table_name: str) -> str:
    """Describe the schema of a specific table.

    Args:
        table_name: Name of the table to describe.

    Returns columns with their types, primary key info, and row count.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Get column info
            cursor = conn.execute(f"PRAGMA table_info({table_name});")
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

            # Get row count
            count_cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name};")
            row_count = count_cursor.fetchone()[0]

            # Get sample rows
            sample_cursor = conn.execute(f"SELECT * FROM {table_name} LIMIT 3;")
            sample_rows = sample_cursor.fetchall()
            col_names = [desc[0] for desc in sample_cursor.description]

            return json.dumps({
                "table": table_name,
                "columns": columns,
                "row_count": row_count,
                "sample_rows": [dict(zip(col_names, row)) for row in sample_rows],
            })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def query_data(sql: str) -> str:
    """Execute a read-only SQL query (SELECT) against the database.

    Args:
        sql: A valid SQL SELECT query string.

    Returns the query results as a JSON object with columns and rows.
    Only SELECT statements are allowed for safety.
    """
    # Safety: only allow SELECT queries
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
        return json.dumps({
            "error": "Only SELECT / WITH queries are allowed. "
                     "Use execute_write for modifications."
        })

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []

            result_rows = [dict(row) for row in rows]
            return json.dumps({
                "columns": columns,
                "rows": result_rows,
                "row_count": len(result_rows),
            })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def execute_write(sql: str) -> str:
    """Execute a write SQL statement (INSERT, UPDATE, DELETE, CREATE).

    Args:
        sql: A valid SQL DML/DDL statement.

    Returns the number of rows affected. Use with caution.
    """
    stripped = sql.strip().upper()
    if stripped.startswith("SELECT"):
        return json.dumps({
            "error": "Use query_data for SELECT queries."
        })

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(sql)
            conn.commit()
            return json.dumps({
                "status": "success",
                "rows_affected": cursor.rowcount,
            })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_database_info() -> str:
    """Get overview information about the database.

    Returns all tables with their schemas and row counts.
    Useful for understanding the full database structure at once.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Get all tables
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
            )
            tables = [row[0] for row in cursor.fetchall()]

            db_info = {"database": DB_PATH, "tables": {}}
            for table in tables:
                # Schema
                schema_cursor = conn.execute(f"PRAGMA table_info({table});")
                columns = [
                    {"name": row[1], "type": row[2], "pk": bool(row[5])}
                    for row in schema_cursor.fetchall()
                ]
                # Row count
                count = conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
                db_info["tables"][table] = {
                    "columns": columns,
                    "row_count": count,
                }
            return json.dumps(db_info)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Run via stdio transport
    mcp.run()
