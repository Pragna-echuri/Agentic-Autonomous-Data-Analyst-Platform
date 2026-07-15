"""
Data Analyst Platform v2 — Streamlit Interface
================================================
Modern dark-themed Streamlit app wired to the new async orchestrator,
persistent MCP sessions, and session memory.

Features:
    - Chat-based query interface with Groq LLM
    - Auto-routed MCP tool calls (database + filesystem servers)
    - Reflection mode toggle for SQL self-critique
    - Multi-format file upload (CSV, XLSX, JSON, PDF, images)
    - Inline chart rendering from outputs/
    - Expandable tool call & reflection logs
    - Session memory persistence across page reloads
    - Real-time server health display

Usage::

    streamlit run ui/streamlit_app.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from core.config import get_settings  # noqa: E402

settings = get_settings()

OUTPUTS_DIR = settings.outputs_dir
DATA_DIR = settings.data_dir
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════
#  Async Helpers
# ═══════════════════════════════════════════════════════════════════════

def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """Get running event loop or create a new one."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
        return loop
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def run_async(coro):
    """Run an async coroutine from sync context."""
    loop = _get_or_create_event_loop()
    return loop.run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════════
#  Orchestrator Lifecycle
# ═══════════════════════════════════════════════════════════════════════

@st.cache_resource
def get_orchestrator():
    """Create and start the orchestrator once per Streamlit session."""
    from core.orchestrator import DataAnalystOrchestrator  # noqa: E402

    orch = DataAnalystOrchestrator()
    run_async(orch.start())
    return orch


@st.cache_resource
def get_session_store():
    """Create the session store once per Streamlit session."""
    from memory.session_store import SessionStore  # noqa: E402

    return SessionStore()


# ═══════════════════════════════════════════════════════════════════════
#  Page Configuration
# ═══════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Data Analyst Platform",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════════════
#  Custom CSS
# ═══════════════════════════════════════════════════════════════════════

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
    .status-degraded {
        background: rgba(255, 165, 0, 0.15); color: #ffa500;
        border: 1px solid rgba(255, 165, 0, 0.3);
    }

    /* Tool call badge */
    .tool-badge {
        display: inline-block; padding: 2px 10px; border-radius: 8px;
        font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.5px; margin-right: 4px;
    }
    .tool-database { background: #1e3a5f; color: #4da6ff; }
    .tool-filesystem { background: #1e3a3a; color: #4dd4ff; }
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

    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, rgba(123, 104, 238, 0.08), rgba(0, 212, 255, 0.05));
        border: 1px solid rgba(123, 104, 238, 0.2);
        border-radius: 12px;
        padding: 0.8rem 1.2rem;
        text-align: center;
    }
    .metric-card .metric-value {
        font-size: 1.5rem; font-weight: 700; color: #00d4ff;
    }
    .metric-card .metric-label {
        font-size: 0.75rem; color: #808090; text-transform: uppercase;
        letter-spacing: 0.8px; margin-top: 4px;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
#  Session State Initialization
# ═══════════════════════════════════════════════════════════════════════

if "messages" not in st.session_state:
    st.session_state.messages = []
if "query_count" not in st.session_state:
    st.session_state.query_count = 0
if "reflection_enabled" not in st.session_state:
    st.session_state.reflection_enabled = True
if "session_id" not in st.session_state:
    import uuid
    st.session_state.session_id = uuid.uuid4().hex[:16]


# ═══════════════════════════════════════════════════════════════════════
#  Helper Functions
# ═══════════════════════════════════════════════════════════════════════

def server_exists(name: str) -> bool:
    paths = {
        "filesystem": PROJECT_ROOT / "mcp_servers" / "filesystem_server.py",
        "database": PROJECT_ROOT / "mcp_servers" / "database_server.py",
    }
    return paths.get(name, Path("")).exists()


def db_exists() -> bool:
    return settings.resolved_db_path.exists()


def get_output_files() -> list[Path]:
    if OUTPUTS_DIR.exists():
        return sorted(OUTPUTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    return []


def _badge_class(server: str) -> str:
    if server in ("database", "sqlite-analyst"):
        return "tool-database"
    if server in ("filesystem", "filesystem-manager"):
        return "tool-filesystem"
    if server == "reflection":
        return "tool-reflection"
    return "tool-legacy"


# ═══════════════════════════════════════════════════════════════════════
#  Sidebar
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
    db_ok = server_exists("database") and db_exists()

    st.markdown(
        f'<span class="status-badge {"status-online" if fs_ok else "status-offline"}">'
        f'{"●" if fs_ok else "○"} Filesystem Server</span>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<span class="status-badge {"status-online" if db_ok else "status-offline"}">'
        f'{"●" if db_ok else "○"} Database Server</span>',
        unsafe_allow_html=True,
    )

    if not db_exists():
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

    st.markdown(f"**Session**: `{st.session_state.session_id[:8]}…`")

    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.query_count = 0
        st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

    # ── File Upload ──────────────────────────────────────────────────
    st.markdown('<div class="sidebar-title">📁 Data Files</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)

    uploaded = st.file_uploader(
        "Upload data file",
        type=["csv", "xlsx", "xls", "json", "jsonl", "parquet", "pdf"],
        help="Adds file to data/ for analysis",
    )
    if uploaded:
        save_path = DATA_DIR / uploaded.name
        save_path.write_bytes(uploaded.getvalue())
        st.success(f"✅ Saved: {uploaded.name}")

    data_files = sorted(
        [f for f in DATA_DIR.iterdir() if f.is_file() and not f.name.startswith(".")],
        key=lambda p: p.name,
    )
    if data_files:
        st.markdown("**Available:**")
        for f in data_files[:15]:
            sz = f.stat().st_size
            label = f"{sz / 1024:.1f} KB" if sz > 1024 else f"{sz} B"
            st.markdown(f"- `{f.name}` ({label})")

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Outputs ──────────────────────────────────────────────────────
    outs = get_output_files()
    if outs:
        st.markdown('<div class="sidebar-title">📤 Generated Outputs</div>', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        for f in outs[:10]:
            if not f.name.startswith("."):
                st.markdown(f"- `{f.name}`")
        st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
#  Main Content
# ═══════════════════════════════════════════════════════════════════════

# ── Header ───────────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>🔬 Data Analyst Platform</h1>
    <p>Enterprise-grade · MCP Protocol · Groq LLM · Async Engine · Reflection Safety</p>
</div>
""", unsafe_allow_html=True)

# ── Metrics ──────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Queries", st.session_state.query_count)
with c2:
    n_servers = sum([fs_ok, db_ok])
    st.metric("MCP Servers", f"{n_servers}/2")
with c3:
    st.metric("Model", settings.groq_model.split("-")[0].title())
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
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                with st.expander(f"🔧 Tool Calls ({len(tool_calls)})"):
                    for tc in tool_calls:
                        server = tc.get("server", "legacy")
                        badge_cls = _badge_class(server)
                        st.markdown(
                            f'<span class="tool-badge {badge_cls}">{server}</span> '
                            f'**{tc["tool_name"]}** '
                            f'`{json.dumps(tc.get("arguments", {}))[:120]}`',
                            unsafe_allow_html=True,
                        )
                        if tc.get("result_preview"):
                            st.code(tc["result_preview"][:400], language="json")

            # Reflection log
            reflection_log = msg.get("reflection_log", [])
            if reflection_log:
                with st.expander("🔍 Reflection Log"):
                    for entry in reflection_log:
                        it = entry.get("iteration", "?")
                        verdict = entry.get("verdict", {})
                        approved = verdict.get("approved", True)
                        risk = verdict.get("risk_level", "unknown")
                        status = "✅ Approved" if approved else "🔄 Corrected"
                        st.markdown(
                            f"**Iteration {it}**: {status} "
                            f"(risk: `{risk}`)"
                        )
                        if verdict.get("issues"):
                            for issue in verdict["issues"]:
                                st.markdown(f"  - {issue}")
                        if verdict.get("explanation"):
                            st.caption(verdict["explanation"])

            # Inline charts
            chart_paths = msg.get("chart_paths", [])
            for cp in chart_paths:
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
                orchestrator = get_orchestrator()
                session_store = get_session_store()

                # Load session context
                session_ctx = ""
                ctx = session_store.get_or_create(st.session_state.session_id)
                if ctx.memory_summary:
                    session_ctx = ctx.memory_summary

                # Run the query
                result = run_async(orchestrator.run(
                    user_query,
                    session_context=session_ctx,
                ))

                response_text = result.result or "No response generated."
                st.markdown(response_text)

                if result.error:
                    st.error(f"⚠️ {result.error}")

                # Convert tool calls to serialisable dicts
                tool_calls = [tc.model_dump() for tc in result.tool_calls]
                if tool_calls:
                    with st.expander(f"🔧 Tool Calls ({len(tool_calls)})"):
                        for tc in tool_calls:
                            server = tc.get("server", "legacy")
                            badge_cls = _badge_class(server)
                            st.markdown(
                                f'<span class="tool-badge {badge_cls}">{server}</span> '
                                f'**{tc["tool_name"]}** '
                                f'`{json.dumps(tc.get("arguments", {}))[:120]}`',
                                unsafe_allow_html=True,
                            )
                            if tc.get("result_preview"):
                                st.code(tc["result_preview"][:400], language="json")

                # Show reflection log
                reflection_log = [e.model_dump() for e in result.reflection_log]
                if reflection_log:
                    with st.expander("🔍 Reflection Log"):
                        for entry in reflection_log:
                            it = entry.get("iteration", "?")
                            verdict = entry.get("verdict", {})
                            approved = verdict.get("approved", True)
                            risk = verdict.get("risk_level", "unknown")
                            status = "✅ Approved" if approved else "🔄 Corrected"
                            st.markdown(
                                f"**Iteration {it}**: {status} "
                                f"(risk: `{risk}`)"
                            )
                            if verdict.get("issues"):
                                for issue in verdict["issues"]:
                                    st.markdown(f"  - {issue}")

                # Detect & show new charts
                chart_paths: list[str] = []
                for tc in tool_calls:
                    if tc["tool_name"] == "generate_chart":
                        try:
                            r = json.loads(tc.get("result_preview", "{}"))
                            if r.get("file_path"):
                                fp = PROJECT_ROOT / r["file_path"]
                                if fp.exists() and fp.suffix == ".png":
                                    st.image(str(fp), caption=fp.name)
                                    chart_paths.append(r["file_path"])
                        except Exception:
                            pass

                # Persist query in session memory
                ctx.previous_queries.append(user_query)
                ctx.total_queries += 1
                session_store.save(ctx)

                # Save to chat history
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
                import traceback
                st.code(traceback.format_exc(), language="python")
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
- *"Generate a comprehensive report on sample.csv"*
        """)


# ── Footer ───────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<p style="text-align: center; color: #555; font-size: 0.8rem;">'
    'Data Analyst Platform v2.0 · MCP Protocol · Groq LLM · '
    'Async Engine · Reflection Safety · Persistent Sessions'
    '</p>',
    unsafe_allow_html=True,
)
