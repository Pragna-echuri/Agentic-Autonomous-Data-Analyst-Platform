"""
MCP Connection Tests
====================
Verifies that MCP servers, database, tools, and modules work correctly.

Usage:
    .venv\\Scripts\\python.exe tests/test_mcp_connection.py
    .venv\\Scripts\\python.exe -m pytest tests/test_mcp_connection.py -v
"""

import os
import sys
import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "mcp_servers"))


# ═══════════════════════════════════════════════════════════════════════
# Test: Database
# ═══════════════════════════════════════════════════════════════════════

def test_database_exists():
    db = PROJECT_ROOT / "data" / "example.db"
    assert db.exists(), f"DB not found at {db}. Run: python data/init_db.py"


def test_database_has_tables():
    db = PROJECT_ROOT / "data" / "example.db"
    if not db.exists():
        import subprocess
        subprocess.run([sys.executable, str(PROJECT_ROOT / "data" / "init_db.py")], check=True)
    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert {"customers", "products", "orders", "order_items"}.issubset(tables)


def test_database_has_data():
    db = PROJECT_ROOT / "data" / "example.db"
    conn = sqlite3.connect(str(db))
    for t in ["customers", "products", "orders", "order_items"]:
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] > 0, f"{t} is empty"
    conn.close()


# ═══════════════════════════════════════════════════════════════════════
# Test: File Existence
# ═══════════════════════════════════════════════════════════════════════

def test_sqlite_server_exists():
    assert (PROJECT_ROOT / "mcp_servers" / "sqlite_server.py").exists()

def test_filesystem_server_exists():
    assert (PROJECT_ROOT / "mcp_servers" / "filesystem_server.py").exists()

def test_sample_csv_exists():
    csv = PROJECT_ROOT / "data" / "sample.csv"
    assert csv.exists()
    import csv as csvmod
    with open(csv) as f:
        assert len(list(csvmod.reader(f))) > 1

def test_mcp_config_valid():
    cfg = PROJECT_ROOT / "mcp_config.json"
    assert cfg.exists()
    config = json.loads(cfg.read_text())
    assert "mcpServers" in config
    assert "filesystem" in config["mcpServers"]
    assert "database" in config["mcpServers"]

def test_env_file_exists():
    assert (PROJECT_ROOT / ".env").exists()


# ═══════════════════════════════════════════════════════════════════════
# Test: SQLite MCP Server (Direct Import)
# ═══════════════════════════════════════════════════════════════════════

def test_sqlite_list_tables():
    os.environ["SQLITE_DB_PATH"] = str(PROJECT_ROOT / "data" / "example.db")
    from sqlite_server import list_tables
    r = json.loads(list_tables())
    assert "tables" in r, f"Got: {r}"
    assert len(r["tables"]) >= 4


def test_sqlite_describe_table():
    os.environ["SQLITE_DB_PATH"] = str(PROJECT_ROOT / "data" / "example.db")
    from sqlite_server import describe_table
    r = json.loads(describe_table("customers"))
    assert "columns" in r
    assert r["row_count"] > 0


def test_sqlite_query_data():
    os.environ["SQLITE_DB_PATH"] = str(PROJECT_ROOT / "data" / "example.db")
    from sqlite_server import query_data
    r = json.loads(query_data("SELECT COUNT(*) as cnt FROM customers"))
    assert "rows" in r
    assert r["rows"][0]["cnt"] > 0


def test_sqlite_blocks_unsafe():
    os.environ["SQLITE_DB_PATH"] = str(PROJECT_ROOT / "data" / "example.db")
    from sqlite_server import query_data
    r = json.loads(query_data("DROP TABLE customers"))
    assert "error" in r


def test_sqlite_get_database_info():
    os.environ["SQLITE_DB_PATH"] = str(PROJECT_ROOT / "data" / "example.db")
    from sqlite_server import get_database_info
    r = json.loads(get_database_info())
    assert "tables" in r
    assert "customers" in r["tables"]


# ═══════════════════════════════════════════════════════════════════════
# Test: Filesystem MCP Server (Direct Import)
# ═══════════════════════════════════════════════════════════════════════

def test_fs_list_directory():
    from filesystem_server import list_directory
    r = json.loads(list_directory("data"))
    assert "contents" in r
    assert r["count"] > 0


def test_fs_read_csv_preview():
    from filesystem_server import read_csv_preview
    r = json.loads(read_csv_preview("sample.csv", 5))
    assert "columns" in r
    assert len(r["preview_rows"]) > 0


def test_fs_get_csv_stats():
    from filesystem_server import get_csv_stats
    r = json.loads(get_csv_stats("sample.csv"))
    assert "numeric_columns" in r
    assert len(r["numeric_columns"]) > 0


def test_fs_write_and_read():
    from filesystem_server import write_file, read_file
    wr = json.loads(write_file("_test_output.txt", "hello mcp"))
    assert wr.get("status") == "success"

    rd = json.loads(read_file("outputs/_test_output.txt"))
    assert "hello mcp" in rd.get("content", "")

    # Clean up
    p = PROJECT_ROOT / "outputs" / "_test_output.txt"
    if p.exists():
        p.unlink()


# ═══════════════════════════════════════════════════════════════════════
# Test: Legacy Tools
# ═══════════════════════════════════════════════════════════════════════

def test_tools_eda():
    from tools import run_pandas_eda
    result = run_pandas_eda("sample.csv")
    assert "EDA Report" in result
    assert "Shape" in result


def test_tools_chart():
    from tools import generate_chart
    result = json.loads(generate_chart("histogram", "sample.csv", "Age", title="Test"))
    assert result.get("status") == "success"
    # Clean up
    fp = PROJECT_ROOT / result["file_path"]
    if fp.exists():
        fp.unlink()


def test_tools_export():
    from tools import export_report
    result = json.loads(export_report("Test content", "test_rpt", "markdown"))
    assert result.get("status") == "success"
    fp = PROJECT_ROOT / result["file_path"]
    if fp.exists():
        fp.unlink()


# ═══════════════════════════════════════════════════════════════════════
# Test: Modules Import
# ═══════════════════════════════════════════════════════════════════════

def test_reflection_imports():
    from reflection import ReflectionEngine, ReflectionResult
    assert ReflectionEngine is not None

def test_agents_imports():
    from agents import MCPHost, DataAnalystOrchestrator
    assert MCPHost is not None
    assert DataAnalystOrchestrator is not None

def test_tools_imports():
    from tools import LEGACY_TOOLS, execute_legacy_tool
    assert len(LEGACY_TOOLS) == 3
    assert execute_legacy_tool is not None


# ─── Runner ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🧪 MCP Data Analyst Agent — Test Suite\n")

    tests = [
        test_database_exists,
        test_database_has_tables,
        test_database_has_data,
        test_sqlite_server_exists,
        test_filesystem_server_exists,
        test_sample_csv_exists,
        test_mcp_config_valid,
        test_env_file_exists,
        test_sqlite_list_tables,
        test_sqlite_describe_table,
        test_sqlite_query_data,
        test_sqlite_blocks_unsafe,
        test_sqlite_get_database_info,
        test_fs_list_directory,
        test_fs_read_csv_preview,
        test_fs_get_csv_stats,
        test_fs_write_and_read,
        test_tools_eda,
        test_tools_chart,
        test_tools_export,
        test_reflection_imports,
        test_agents_imports,
        test_tools_imports,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1

    print(f"\n{'═' * 55}")
    print(f"  Results: {passed} passed, {failed} failed, {len(tests)} total")
    print(f"{'═' * 55}")
    sys.exit(1 if failed > 0 else 0)
