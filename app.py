"""
Data Analyst MCP Agent — Streamlit Interface
=============================================
Premium dark-themed Streamlit app providing a chat-based interface
to the MCP-powered Data Analyst agent.

Features:
    - Chat-based query interface with Groq LLM
    - Auto-routed MCP tool calls (SQLite + Filesystem servers)
    - Reflection mode toggle for SQL self-critique
    - File upload for custom CSVs
    - Inline chart rendering from outputs/
    - Expandable tool call & reflection logs

Usage:
    .venv\\Scripts\\streamlit.exe run app.py
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd
from dotenv import load_dotenv

# ─── Setup ───────────────────────────────────────────────────────────────────
load_dotenv()
PROJECT_ROOT = Path(__file__).parent.resolve()
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR.mkdir(exist_ok=True)

# ─── Page Config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Data Analyst Agent — MCP",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    .stApp { font-family: 'Inter', sans-serif; }

    /* Gradient header */
    .main-header {
        background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 1.5rem;
        border: 1px solid rgba(100, 100, 255, 0.15);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    }
    .main-header h1 {
        background: linear-gradient(90deg, #00d4ff, #7b68ee, #ff6b9d);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.2rem; font-weight: 700; margin: 0;
    }
    .main-header p { color: #a0a0b8; font-size: 1rem; margin-top: 0.5rem; }

    /* Status badges */
    .status-badge {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 5px 14px; border-radius: 20px;
        font-size: 0.8rem; font-weight: 500;
    }
    .status-online {
        background: rgba(0, 212, 106, 0.15); color: #00d46a;
        border: 1px solid rgba(0, 212, 106, 0.3);
    }
    .status-offline {
        background: rgba(255, 75, 75, 0.15); color: #ff4b4b;
        border: 1px solid rgba(255, 75, 75, 0.3);
    }

    /* Tool call badge */
    .tool-badge {
        display: inline-block; padding: 2px 8px; border-radius: 8px;
        font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.5px; margin-right: 4px;
    }
    .tool-mcp { background: #1e3a5f; color: #4da6ff; }
    .tool-legacy { background: #3a1e3a; color: #ff4dff; }
    .tool-reflection { background: #1e3a1e; color: #4dff4d; }

    /* Sidebar sections */
    .sidebar-section {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 10px; padding: 1rem; margin-bottom: 1rem;
    }
    .sidebar-title {
        color: #7b68ee; font-weight: 600; font-size: 0.9rem;
        margin-bottom: 0.8rem; text-transform: uppercase; letter-spacing: 1px;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ─── Session State ───────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "query_count" not in st.session_state:
    st.session_state.query_count = 0
if "reflection_enabled" not in st.session_state:
    st.session_state.reflection_enabled = True


# ─── Helper Functions ────────────────────────────────────────────────────────

def server_exists(name: str) -> bool:
    paths = {
        "filesystem": PROJECT_ROOT / "mcp_servers" / "filesystem_server.py",
        "database": PROJECT_ROOT / "mcp_servers" / "sqlite_server.py",
    }
    return paths.get(name, Path("")).exists()


def db_exists() -> bool:
    return (DATA_DIR / "example.db").exists()


def get_output_files() -> list:
    if OUTPUTS_DIR.exists():
        return sorted(OUTPUTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    return []


# ═══════════════════════════════════════════════════════════════════════
# Sidebar
# ═══════════════════════════════════════════════════════════════════════
with st.sidebar:
    # ── API Key ──────────────────────────────────────────────────────
    st.markdown('<div class="sidebar-title">⚙️ Configuration</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
    api_key = st.text_input(
        "Groq API Key",
        value=os.getenv("GROQ_API_KEY", ""),
        type="password",
        help="Get yours at https://console.groq.com/keys",
    )
    if api_key:
        os.environ["GROQ_API_KEY"] = api_key
    st.markdown('</div>', unsafe_allow_html=True)

    # ── MCP Server Status ────────────────────────────────────────────
    st.markdown('<div class="sidebar-title">🔌 MCP Servers</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)

    fs_ok = server_exists("filesystem")
    db_script_ok = server_exists("database")
    db_file_ok = db_exists()

    st.markdown(
        f'<span class="status-badge {"status-online" if fs_ok else "status-offline"}">'
        f'{"●" if fs_ok else "○"} Filesystem Server</span>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<span class="status-badge {"status-online" if db_script_ok and db_file_ok else "status-offline"}">'
        f'{"●" if db_script_ok and db_file_ok else "○"} SQLite Server</span>',
        unsafe_allow_html=True,
    )

    if not db_file_ok:
        if st.button("🔨 Initialize Database", use_container_width=True):
            with st.spinner("Seeding database..."):
                r = subprocess.run(
                    [sys.executable, str(DATA_DIR / "init_db.py")],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                )
                if r.returncode == 0:
                    st.success("✅ Database initialized!")
                    st.rerun()
                else:
                    st.error(f"Error: {r.stderr}")
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Settings ─────────────────────────────────────────────────────
    st.markdown('<div class="sidebar-title">🛠️ Settings</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)

    st.session_state.reflection_enabled = st.toggle(
        "🔍 Reflection Mode",
        value=st.session_state.reflection_enabled,
        help="Self-critique SQL/Python code before execution",
    )
    os.environ["REFLECTION_ENABLED"] = str(st.session_state.reflection_enabled).lower()

    st.markdown('</div>', unsafe_allow_html=True)

    # ── File Upload ──────────────────────────────────────────────────
    st.markdown('<div class="sidebar-title">📁 Data Files</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)

    uploaded = st.file_uploader("Upload CSV", type=["csv"], help="Adds CSV to data/ for analysis")
    if uploaded:
        (DATA_DIR / uploaded.name).write_bytes(uploaded.getvalue())
        st.success(f"✅ Saved: {uploaded.name}")

    data_files = list(DATA_DIR.glob("*.csv")) + list(DATA_DIR.glob("*.db"))
    if data_files:
        st.markdown("**Available:**")
        for f in data_files:
            sz = f.stat().st_size
            st.markdown(f"- `{f.name}` ({sz/1024:.1f} KB)" if sz > 1024 else f"- `{f.name}` ({sz} B)")
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Outputs ──────────────────────────────────────────────────────
    outs = get_output_files()
    if outs:
        st.markdown('<div class="sidebar-title">📤 Generated Outputs</div>', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        for f in outs[:10]:
            st.markdown(f"- `{f.name}`")
        st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
# Main Content
# ═══════════════════════════════════════════════════════════════════════

# ── Header ───────────────────────────────────────────────────────────
st.title("🔬 Data Analyst Agent")
st.caption("MCP-powered · Groq LLM · Python MCP Servers · Reflection Engine")

# ── Metrics ──────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Queries", st.session_state.query_count)
with c2:
    n_servers = sum([fs_ok, db_script_ok and db_file_ok])
    st.metric("MCP Servers", f"{n_servers}/2")
with c3:
    st.metric("Model", "Llama 3.3 70B")
with c4:
    st.metric("Reflection", "ON" if st.session_state.reflection_enabled else "OFF")

st.divider()

# ── Chat History ─────────────────────────────────────────────────────
for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user", avatar="👤"):
            st.markdown(msg["content"])
    else:
        with st.chat_message("assistant", avatar="🤖"):
            st.markdown(msg["content"])

            # Tool calls
            if msg.get("tool_calls"):
                with st.expander(f"🔧 Tool Calls ({len(msg['tool_calls'])})"):
                    for tc in msg["tool_calls"]:
                        badge_cls = "tool-mcp" if tc.get("server") != "legacy" else "tool-legacy"
                        st.markdown(
                            f'<span class="tool-badge {badge_cls}">{tc.get("server","?")}</span> '
                            f'**{tc["tool"]}** `{json.dumps(tc.get("arguments",{}))[:120]}`',
                            unsafe_allow_html=True,
                        )
                        if tc.get("result_preview"):
                            st.code(tc["result_preview"][:300], language="json")

            # Reflection log
            if msg.get("reflection_log"):
                with st.expander("🔍 Reflection Log"):
                    for entry in msg["reflection_log"]:
                        it = entry.get("iteration", "?")
                        r = entry.get("reflection", {})
                        status = "✅ Approved" if r.get("approved") else "🔄 Corrected"
                        st.markdown(f"**Iteration {it}**: {status}")
                        if r.get("issues"):
                            for issue in r["issues"]:
                                st.markdown(f"  - {issue}")

            # Inline charts
            if msg.get("chart_paths"):
                for cp in msg["chart_paths"]:
                    p = OUTPUTS_DIR / cp if not Path(cp).is_absolute() else Path(cp)
                    if p.exists() and p.suffix == ".png":
                        st.image(str(p), caption=p.name)


# ── Chat Input ───────────────────────────────────────────────────────
user_query = st.chat_input(
    "Ask anything about your data… (e.g. 'What's the average salary by department?')"
)

if user_query:
    # Validate API key
    key = os.getenv("GROQ_API_KEY", "")
    if not key or key == "your_groq_api_key_here":
        st.error("⚠️ Please enter your Groq API key in the sidebar.")
        st.stop()

    # Show user message
    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user", avatar="👤"):
        st.markdown(user_query)

    # Process
    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("🔄 Agent working…"):
            try:
                from agents import DataAnalystOrchestrator
                import asyncio

                orchestrator = DataAnalystOrchestrator()
                result = asyncio.run(orchestrator.run(user_query))

                response_text = result.get("result", "No response.")
                st.markdown(response_text)

                if result.get("error"):
                    st.error(f"⚠️ {result['error']}")

                # Show tool calls
                tool_calls = result.get("tool_calls", [])
                if tool_calls:
                    with st.expander(f"🔧 Tool Calls ({len(tool_calls)})"):
                        for tc in tool_calls:
                            badge_cls = "tool-mcp" if tc.get("server") != "legacy" else "tool-legacy"
                            st.markdown(
                                f'<span class="tool-badge {badge_cls}">{tc.get("server","?")}</span> '
                                f'**{tc["tool"]}**',
                                unsafe_allow_html=True,
                            )

                # Show reflection
                reflection_log = result.get("reflection_log", [])
                if reflection_log:
                    with st.expander("🔍 Reflection Log"):
                        for entry in reflection_log:
                            st.json(entry)

                # Detect & show new charts
                chart_paths = []
                for tc in tool_calls:
                    if tc["tool"] == "generate_chart":
                        try:
                            r = json.loads(tc.get("result_preview", "{}"))
                            if r.get("file_path"):
                                fp = PROJECT_ROOT / r["file_path"]
                                if fp.exists() and fp.suffix == ".png":
                                    st.image(str(fp), caption=fp.name)
                                    chart_paths.append(r["file_path"])
                        except Exception:
                            pass

                # Also show any recently created PNGs
                recent_outputs = get_output_files()
                for f in recent_outputs[:3]:
                    if f.suffix == ".png" and f.name not in [Path(c).name for c in chart_paths]:
                        st.image(str(f), caption=f.name)
                        chart_paths.append(f"outputs/{f.name}")

                # Save to history
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response_text,
                    "tool_calls": tool_calls,
                    "reflection_log": reflection_log,
                    "chart_paths": chart_paths,
                })
                st.session_state.query_count += 1

            except Exception as e:
                err = f"❌ Error: {str(e)}"
                st.error(err)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": err,
                })

# ── Quick Actions (shown when chat is empty) ─────────────────────────
if not st.session_state.messages:
    st.markdown("### 💡 Try these example queries:")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
**📊 EDA & Analysis**
- *"Run a full EDA on sample.csv"*
- *"What are the summary statistics for sample.csv?"*
- *"Show correlations between numeric columns"*

**🗄️ Database Queries**
- *"What tables are in the database?"*
- *"What's the average order value by country?"*
- *"Show the top 5 customers by total spend"*
        """)
    with col2:
        st.markdown("""
**🎨 Visualizations**
- *"Create a bar chart of salary by department from sample.csv"*
- *"Plot a histogram of ages from sample.csv"*
- *"Create a scatter plot of age vs salary from sample.csv"*

**🔬 Combined**
- *"Analyze sample.csv and create a visualization"*
- *"Query the database for order stats and show a chart"*
        """)

# ── Footer ───────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<p style="text-align: center; color: #555; font-size: 0.8rem;">'
    'Data Analyst Agent · MCP Protocol · Groq LLM · Python MCP Servers · Streamlit'
    '</p>',
    unsafe_allow_html=True,
)
