import os, sys, json, asyncio
sys.path.insert(0, ".")
os.environ["SQLITE_DB_PATH"] = "data/example.db"
os.environ["REFLECTION_ENABLED"] = "false"

from agents import MCPHost
from tools import execute_legacy_tool

async def test():
    h = MCPHost()
    tools = await h.discover_tools()
    print(f"MCP tools discovered: {len(tools)}")
    names = [t["function"]["name"] for t in tools]
    print(f"Tools: {names}")

    r = await h.call_tool("list_tables", {})
    d = json.loads(r)
    print(f"DB tables: {d['tables']}")

    r2 = await h.call_tool("query_data", {"sql": "SELECT COUNT(*) as n FROM customers"})
    d2 = json.loads(r2)
    print(f"Customer count: {d2['rows'][0]['n']}")

    r3 = await h.call_tool("query_data", {"sql": "SELECT status, COUNT(*) as cnt, ROUND(AVG(total_amount),2) as avg FROM orders GROUP BY status"})
    d3 = json.loads(r3)
    print("Order stats:")
    for row in d3["rows"]:
        print(f"  {row['status']}: {row['cnt']} orders, avg ${row['avg']}")

    r4 = await h.call_tool("read_csv_preview", {"path": "sample.csv", "max_rows": 2})
    d4 = json.loads(r4)
    print(f"CSV columns: {d4['columns']}")
    print(f"CSV total rows: {d4['total_rows']}")

    eda = execute_legacy_tool("run_pandas_eda", {"csv_path": "sample.csv"})
    print(f"EDA report: {len(eda)} chars")
    for line in eda.split("\n"):
        if "Shape" in line:
            print(f"  {line.strip()}")
            break

    chart = execute_legacy_tool("generate_chart", {"chart_type": "histogram", "csv_path": "sample.csv", "x_column": "Salary", "title": "Test"})
    cd = json.loads(chart)
    print(f"Chart: {cd.get('status')} -> {cd.get('file_path')}")

    print("\nALL AGENT TESTS PASSED")

asyncio.run(test())
