"""
End-to-End Agent Test
=====================
Tests the full MCP infrastructure: tool discovery, MCP server calls,
and legacy tool execution. Does NOT require a Groq API key.
"""
import os
import sys
import json
import asyncio
from pathlib import Path

# Setup
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["SQLITE_DB_PATH"] = str(PROJECT_ROOT / "data" / "example.db")
os.environ["REFLECTION_ENABLED"] = "false"

from agents import MCPHost
from tools import execute_legacy_tool

async def test_mcp_tool_discovery():
    """Test: Can the MCPHost discover tools from both MCP servers?"""
    print("=" * 60)
    print("TEST 1: MCP Tool Discovery")
    print("=" * 60)
    
    host = MCPHost()
    tools = await host.discover_tools()
    
    print(f"\nDiscovered {len(tools)} MCP tools:")
    for t in tools:
        fn = t["function"]
        server = host.get_server_for_tool(fn["name"])
        print(f"  [{server}] {fn['name']}: {fn['description'][:60]}...")
    
    assert len(tools) >= 8, f"Expected at least 8 MCP tools, got {len(tools)}"
    print(f"\n✅ PASSED — {len(tools)} MCP tools discovered from 2 servers\n")
    return host


async def test_mcp_sqlite_calls(host: MCPHost):
    """Test: Can we call SQLite MCP server tools?"""
    print("=" * 60)
    print("TEST 2: SQLite MCP Server Calls")
    print("=" * 60)
    
    # list_tables
    print("\n  Calling list_tables...")
    result = await host.call_tool("list_tables", {})
    data = json.loads(result)
    print(f"  → Tables: {data.get('tables', 'ERROR')}")
    assert "tables" in data
    assert len(data["tables"]) >= 4
    
    # describe_table
    print("\n  Calling describe_table('customers')...")
    result = await host.call_tool("describe_table", {"table_name": "customers"})
    data = json.loads(result)
    print(f"  → Columns: {[c['name'] for c in data.get('columns', [])]}")
    print(f"  → Row count: {data.get('row_count')}")
    assert data["row_count"] == 15
    
    # query_data
    print("\n  Calling query_data('SELECT country, COUNT(*) as cnt FROM customers GROUP BY country')...")
    result = await host.call_tool("query_data", {
        "sql": "SELECT country, COUNT(*) as cnt FROM customers GROUP BY country ORDER BY cnt DESC"
    })
    data = json.loads(result)
    print(f"  → Results ({data.get('row_count')} rows):")
    for row in data.get("rows", [])[:5]:
        print(f"     {row['country']}: {row['cnt']}")
    assert data["row_count"] > 0
    
    # query_data safety
    print("\n  Calling query_data with unsafe DROP TABLE...")
    result = await host.call_tool("query_data", {"sql": "DROP TABLE customers"})
    data = json.loads(result)
    print(f"  → Blocked: {data.get('error', 'NOT BLOCKED!')}")
    assert "error" in data
    
    print("\n✅ PASSED — All SQLite MCP calls working\n")


async def test_mcp_filesystem_calls(host: MCPHost):
    """Test: Can we call Filesystem MCP server tools?"""
    print("=" * 60)
    print("TEST 3: Filesystem MCP Server Calls")
    print("=" * 60)
    
    # list_directory
    print("\n  Calling list_directory('data')...")
    result = await host.call_tool("list_directory", {"path": "data"})
    data = json.loads(result)
    print(f"  → Files in data/: {[f['name'] for f in data.get('contents', [])]}")
    assert data["count"] > 0
    
    # read_csv_preview
    print("\n  Calling read_csv_preview('sample.csv', 3)...")
    result = await host.call_tool("read_csv_preview", {"path": "sample.csv", "max_rows": 3})
    data = json.loads(result)
    print(f"  → Columns: {data.get('columns')}")
    print(f"  → Total rows: {data.get('total_rows')}")
    print(f"  → Preview (first row): {data.get('preview_rows', [{}])[0]}")
    assert data["total_rows"] == 20
    
    # get_csv_stats
    print("\n  Calling get_csv_stats('sample.csv')...")
    result = await host.call_tool("get_csv_stats", {"path": "sample.csv"})
    data = json.loads(result)
    numeric = data.get("numeric_columns", {})
    print(f"  → Numeric columns found: {list(numeric.keys())}")
    if "Salary" in numeric:
        s = numeric["Salary"]
        print(f"  → Salary stats: min={s['min']}, max={s['max']}, mean={s['mean']}")
    assert len(numeric) > 0
    
    # write_file + read_file roundtrip
    print("\n  Calling write_file then read_file roundtrip...")
    write_result = await host.call_tool("write_file", {
        "path": "_agent_test.txt",
        "content": "MCP agent test file - hello from the orchestrator!"
    })
    wr = json.loads(write_result)
    print(f"  → Write: {wr.get('status')}")
    
    read_result = await host.call_tool("read_file", {"path": "outputs/_agent_test.txt"})
    rd = json.loads(read_result)
    print(f"  → Read back: '{rd.get('content', '')[:50]}'")
    assert "hello from the orchestrator" in rd.get("content", "")
    
    # Cleanup
    test_file = PROJECT_ROOT / "outputs" / "_agent_test.txt"
    if test_file.exists():
        test_file.unlink()
    
    print("\n✅ PASSED — All Filesystem MCP calls working\n")


def test_legacy_tools():
    """Test: Do legacy tools (charts, EDA, export) work?"""
    print("=" * 60)
    print("TEST 4: Legacy Tools")
    print("=" * 60)
    
    # EDA
    print("\n  Running run_pandas_eda on sample.csv...")
    result = execute_legacy_tool("run_pandas_eda", {"csv_path": "sample.csv"})
    assert "EDA Report" in result
    assert "Shape" in result
    # Extract key stats from the report
    for line in result.split("\n"):
        if "Shape" in line:
            print(f"  → {line.strip()}")
            break
    print(f"  → Report length: {len(result)} chars")
    
    # Chart
    print("\n  Generating histogram chart...")
    result = execute_legacy_tool("generate_chart", {
        "chart_type": "histogram",
        "csv_path": "sample.csv",
        "x_column": "Salary",
        "title": "Salary Distribution (Agent Test)"
    })
    data = json.loads(result)
    print(f"  → Status: {data.get('status')}")
    print(f"  → File: {data.get('file_path')}")
    assert data.get("status") == "success"
    # Cleanup
    fp = PROJECT_ROOT / data["file_path"]
    if fp.exists():
        fp.unlink()
    
    # Export
    print("\n  Exporting markdown report...")
    result = execute_legacy_tool("export_report", {
        "content": "Test report from agent e2e test",
        "filename": "agent_test",
        "format": "markdown"
    })
    data = json.loads(result)
    print(f"  → Status: {data.get('status')}")
    print(f"  → File: {data.get('file_path')}")
    assert data.get("status") == "success"
    # Cleanup
    fp = PROJECT_ROOT / data["file_path"]
    if fp.exists():
        fp.unlink()
    
    print("\n✅ PASSED — All legacy tools working\n")


async def test_full_pipeline():
    """Test the full MCP tool discovery + call pipeline."""
    print("=" * 60)
    print("TEST 5: Full Pipeline (Discovery → Calls)")
    print("=" * 60)
    
    host = MCPHost()
    
    # Discover
    tools = await host.discover_tools()
    mcp_tool_names = [t["function"]["name"] for t in tools]
    print(f"\n  MCP tools: {mcp_tool_names}")
    
    # Simulate what the LLM would do: query the database
    print("\n  Simulating agent flow: explore → query → answer")
    
    # Step 1: Agent explores database
    print("  Step 1: get_database_info")
    info = json.loads(await host.call_tool("get_database_info", {}))
    tables = list(info.get("tables", {}).keys())
    print(f"    → Found tables: {tables}")
    
    # Step 2: Agent queries for insights
    print("  Step 2: query_data (average order by status)")
    qr = json.loads(await host.call_tool("query_data", {
        "sql": "SELECT status, COUNT(*) as count, ROUND(AVG(total_amount),2) as avg_total FROM orders GROUP BY status"
    }))
    print(f"    → Results:")
    for row in qr.get("rows", []):
        print(f"       {row['status']}: {row['count']} orders, avg ${row['avg_total']}")
    
    # Step 3: Agent explores CSV
    print("  Step 3: read_csv_preview (sample.csv)")
    preview = json.loads(await host.call_tool("read_csv_preview", {"path": "sample.csv", "max_rows": 2}))
    print(f"    → Columns: {preview.get('columns')}")
    
    print("\n✅ PASSED — Full pipeline working end-to-end\n")


async def main():
    print("\n🧪 Data Analyst Agent — End-to-End Tests")
    print("=" * 60)
    print("Testing MCP infrastructure WITHOUT requiring Groq API key")
    print("=" * 60 + "\n")
    
    try:
        host = await test_mcp_tool_discovery()
        await test_mcp_sqlite_calls(host)
        await test_mcp_filesystem_calls(host)
        test_legacy_tools()
        await test_full_pipeline()
        
        print("=" * 60)
        print("🎉 ALL 5 TESTS PASSED — Agent infrastructure verified!")
        print("=" * 60)
        print("\nTo test with LLM (requires Groq API key):")
        print("  1. Set GROQ_API_KEY in .env")
        print("  2. Run: .venv\\Scripts\\streamlit.exe run app.py")
        print("  3. Ask: 'What tables are in the database?'")
        
    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
