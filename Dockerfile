# ═══════════════════════════════════════════════════════════════════════
# Data Analyst Platform v2.0 — Dockerfile
# ═══════════════════════════════════════════════════════════════════════
# Multi-stage build: slim Python image, non-root user, health checks.
#
# Build:
#   docker build -t data-analyst-platform .
#
# Run (FastAPI):
#   docker run -p 8000:8000 --env-file .env data-analyst-platform
#
# Run (Streamlit):
#   docker run -p 8501:8501 --env-file .env data-analyst-platform streamlit
# ═══════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS base

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd --create-home --shell /bin/bash analyst
WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create required directories
RUN mkdir -p /app/outputs /app/data \
    && chown -R analyst:analyst /app

USER analyst

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Default: FastAPI
EXPOSE 8000
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Entrypoint script for flexible startup
COPY <<'EOF' /app/entrypoint.sh
#!/bin/bash
set -e

if [ "$1" = "streamlit" ]; then
    exec streamlit run ui/streamlit_app.py \
        --server.port=8501 \
        --server.address=0.0.0.0 \
        --server.headless=true
elif [ "$1" = "api" ] || [ -z "$1" ]; then
    exec uvicorn api.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --workers 1
else
    exec "$@"
fi
EOF

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["api"]
