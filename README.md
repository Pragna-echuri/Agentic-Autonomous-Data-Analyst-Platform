# 🤖 Autonomous Data Analyst Platform

> An enterprise-grade autonomous data analysis platform powered by MCP, LLMs, and a sandboxed execution engine — built to the engineering standards of top-tier AI companies.

---

## Overview

The **Autonomous Data Analyst Platform** transforms a prototype MCP-powered chatbot into a production-ready system for autonomous data analysis. It combines:

- **MCP (Model Context Protocol)** for persistent, low-overhead tool sessions
- **Groq LLM backend** with circuit-breaker resilience
- **Sandboxed code execution** with AST-level static analysis
- **Multi-format data ingestion** (CSV, XLSX, JSON, PDF, images, Parquet)
- **Stateful conversational memory** backed by SQLite
- **FastAPI service layer** with structured observability
- **Streamlit UI** for interactive data analysis

---

## Key Features

**Data Ingestion**
Multi-format support (CSV, XLSX, JSON, PDF, images, Parquet) with graceful degradation when optional OCR dependencies are unavailable.

**Security-First Execution**
All LLM-generated Python and SQL code passes through an AST-based static analyser before execution. Dangerous constructs (`eval`, `exec`, `subprocess`, `__import__`) are blocked at the syntax tree level — before any runtime is involved.

**Persistent MCP Sessions**
`AsyncExitStack` manages MCP server lifecycles, eliminating per-call subprocess overhead and guaranteeing clean shutdown across API and Streamlit surfaces.

**Resilient LLM Calls**
Circuit breaker with exponential backoff + jitter prevents cascading failures when the LLM provider is degraded. Half-open probing detects recovery automatically.

**Token-Aware Memory**
Conversational context is trimmed using a token estimator so sessions never silently overflow the model's context window.

**Structured Observability**
`structlog` JSON logging, OpenTelemetry tracing, and thread-safe in-process metrics (counters, histograms, timers) across every service boundary.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Clients                              │
│          Streamlit UI          FastAPI REST Layer           │
└────────────────┬───────────────────────┬────────────────────┘
                 │                       │
                 ▼                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator                             │
│   ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│   │  LLM Client │  │  MCP Manager │  │  Tool Registry   │  │
│   │ (Groq/CB)   │  │(AsyncExitStack│  │ (Groq-compat.)  │  │
│   └──────┬──────┘  └──────┬───────┘  └────────┬─────────┘  │
│          │                │                   │             │
│   ┌──────▼────────────────▼───────────────────▼──────────┐  │
│   │              Reflection Engine (AST pre-screen)      │  │
│   └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                 │                       │
    ┌────────────▼──────┐    ┌───────────▼─────────────┐
    │   MCP Servers     │    │   Core Tools            │
    │  ┌─────────────┐  │    │  ┌────────────────────┐ │
    │  │  Database   │  │    │  │  Visualization     │ │
    │  │  (SQLite RO)│  │    │  │  Analysis (EDA)    │ │
    │  ├─────────────┤  │    │  │  Reporting (MD/HTML│ │
    │  │ Filesystem  │  │    │  └────────────────────┘ │
    │  │ (Sandboxed) │  │    └─────────────────────────┘
    │  └─────────────┘  │
    └───────────────────┘
                 │
    ┌────────────▼──────────────────────────────────────────┐
    │                  Infrastructure                        │
    │  Memory (SQLite)  │  Ingestion Pipeline  │  Security  │
    │  Context Manager  │  (6 formats)         │  (AST+Path)│
    └───────────────────────────────────────────────────────┘
```

---

## Project Structure

```
autonomous-data-analyst/
│
├── core/
│   ├── config.py              # Pydantic v2 BaseSettings, env-aware
│   ├── exceptions.py          # 16-class exception hierarchy with error codes
│   ├── models.py              # 15+ Pydantic domain models (frozen, validated)
│   ├── llm_client.py          # Async Groq wrapper, circuit breaker, backoff+jitter
│   ├── mcp_manager.py         # Persistent MCP sessions via AsyncExitStack
│   ├── orchestrator.py        # Async orchestrator (MCP + LLM + Tools + Reflection)
│   ├── reflection.py          # Async reflection engine with AST pre-screening
│   ├── prompts.py             # Centralised prompts with injection defences
│   └── tools/
│       ├── registry.py        # Groq-compatible tool definitions, Pydantic dispatch
│       ├── visualization.py   # Type-safe matplotlib charting, context-manager figures
│       ├── analysis.py        # Bounded EDA with output truncation
│       └── reporting.py       # Markdown/HTML report export
│
├── security/
│   ├── sandbox.py             # AST-based Python + SQL static analysis
│   └── path_validator.py      # Path containment, symlink rejection
│
├── mcp_servers/
│   ├── database_server.py     # Read-only SQLite, row-limited, comment-stripped
│   └── filesystem_server.py   # Sandboxed reads/writes, extension allowlist
│
├── observability/
│   ├── logger.py              # structlog, JSON/console modes, correlation IDs
│   ├── metrics.py             # Thread-safe counters, histograms, timers
│   └── tracing.py             # OpenTelemetry with no-op fallback
│
├── memory/
│   ├── session_store.py       # SQLite-backed session persistence
│   └── context_manager.py     # Token-aware message trimming
│
├── ingestion/
│   └── processor.py           # Multi-format ingestion with graceful degradation
│
├── api/
│   └── main.py                # FastAPI with lifespan, CORS, health/metrics endpoints
│
├── ui/
│   └── streamlit_app.py       # Async-wired Streamlit UI, multi-format upload
│
├── tests/
│   └── unit/
│       ├── test_sandbox.py         # 47 tests (Python + SQL validation)
│       ├── test_path_validator.py  # 17 tests (read/write/symlink)
│       ├── test_metrics.py         # 11 tests (counters/histograms/timer)
│       ├── test_models.py          # 18 tests (Pydantic models)
│       ├── test_config.py          # 17 tests (settings validation)
│       └── test_context_manager.py # 10 tests (token estimation/trimming)
│
├── pyproject.toml
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Getting Started

### Prerequisites

- Python **3.11+**
- [pip](https://pip.pypa.io/) or [uv](https://github.com/astral-sh/uv)
- Docker & Docker Compose (optional, for containerised deployment)
- A **Groq API key** — [get one free](https://console.groq.com/)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-org/autonomous-data-analyst.git
cd autonomous-data-analyst

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) Install OCR extras for image/PDF ingestion
pip install ".[ocr]"
```

### Configuration

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | -- | — | Groq LLM API key |
| `DATA_DIR` | | `./data` | Root directory for data files |
| `DB_PATH` | | `./data/sessions.db` | SQLite session store path |
| `LOG_FORMAT` | | `console` | `console` or `json` |
| `LOG_LEVEL` | | `INFO` | Logging level |
| `MAX_ROWS_RETURNED` | | `1000` | Row cap for database queries |
| `CIRCUIT_BREAKER_THRESHOLD` | | `5` | Failures before circuit opens |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | | — | OpenTelemetry collector URL (optional) |

All settings are validated at startup via Pydantic v2 `BaseSettings`. Invalid configuration will raise a descriptive error before the server starts.

---

## Running the Platform

### Unit Tests

```bash
python -m pytest tests/unit/ -v
# Expected: 129 passed, 0 failed, 1 skipped (symlink on Windows)
```

Run with coverage report:

```bash
python -m pytest tests/unit/ -v \
  --cov=core --cov=security --cov=memory --cov=observability \
  --cov-report=term-missing
```

### FastAPI Server

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

Interactive API docs available at `http://127.0.0.1:8000/docs`.

### Streamlit UI

```bash
streamlit run ui/streamlit_app.py
```

Opens at `http://localhost:8501` by default. Upload a dataset and start analysing interactively.

### Docker

Build and start all services (API + Streamlit) with shared volumes:

```bash
docker-compose up --build
```

| Service | URL |
|---|---|
| FastAPI | `http://localhost:8000` |
| Streamlit | `http://localhost:8501` |

To run only the API service:

```bash
docker-compose up api
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check — returns service status |
| `GET` | `/metrics` | In-process metrics snapshot |
| `POST` | `/analyse` | Submit a natural-language analysis request |
| `POST` | `/upload` | Upload a data file for ingestion |
| `GET` | `/sessions/{session_id}` | Retrieve session history |
| `DELETE` | `/sessions/{session_id}` | Delete a session |

Full interactive documentation is served by FastAPI at `/docs` (Swagger UI) and `/redoc` (ReDoc).

---

## Security Model

Security is applied at multiple independent layers so that no single bypass compromises the system.

**Layer 1 — Prompt Injection Defence**
All user input is sanitised in `core/prompts.py` before being composed into LLM prompts. Delimiter injection and instruction override attempts are neutralised at the prompt construction stage.

**Layer 2 — AST Static Analysis**
Before any LLM-generated Python or SQL code is executed, `security/sandbox.py` parses it into an Abstract Syntax Tree and rejects code containing dangerous constructs including `eval`, `exec`, `os.system`, `subprocess`, `__import__`, and shell metacharacters in SQL. This check is deterministic and cannot be bypassed by obfuscation tricks that rely on runtime evaluation.

**Layer 3 — Filesystem Sandboxing**
`security/path_validator.py` uses `Path.is_relative_to()` for structural path containment. Symlinks and traversal sequences (`../`) are rejected. Read and write permissions are checked independently against their respective allowed roots.

**Layer 4 — Database Read-Only Mode**
The database MCP server opens SQLite connections with the `?mode=ro` URI flag. This is enforced at the database driver level and cannot be overridden by SQL statements.

**Layer 5 — Row Limits**
All database queries are capped at `MAX_ROWS_RETURNED` (default: 1000). This prevents accidental or deliberate exfiltration of large datasets through the query interface.

---

## Observability

**Structured Logging**
`observability/logger.py` wraps `structlog` with correlation IDs injected at request boundaries. Output format is switchable between human-readable console (development) and newline-delimited JSON (production / log aggregators).

**Metrics**
`observability/metrics.py` exposes thread-safe in-process counters, histograms, and timers. Metrics are served at `/metrics` for scraping by Prometheus or compatible collectors.

**Distributed Tracing**
`observability/tracing.py` instruments the orchestrator, LLM client, and MCP manager with OpenTelemetry spans. A no-op fallback is used when no OTLP exporter is configured, so the application runs without any tracing infrastructure.

---
