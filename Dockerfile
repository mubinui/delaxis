# Multi-stage Dockerfile for Delaxis
# Stage 1: Build the Studio SPA
FROM node:22-alpine AS frontend

WORKDIR /fe

COPY workflow-editor/package.json workflow-editor/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY workflow-editor/ ./
RUN npm run build

# Stage 2: Install Python dependencies using uv
FROM python:3.11-slim AS builder

WORKDIR /app

# Install minimal build tools - clean apt cache BEFORE downloading
RUN apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* && \
    apt-get update && \
    apt-get install -y --no-install-recommends -o Acquire::Languages=none \
        build-essential \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /tmp/* && \
    pip install --no-cache-dir uv

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install dependencies using uv (much faster than pip)
RUN uv sync --frozen --no-dev

# Stage 3: Production - minimal runtime image
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY src/ ./src/
COPY configs/ ./configs/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Copy the built Studio SPA — served by FastAPI at /
COPY --from=frontend /fe/dist ./static

# Create non-root user; /app/data holds the SQLite DB, sessions, and deployments
RUN useradd -m -u 1000 delaxis && \
    mkdir -p /app/data && \
    chown -R delaxis:delaxis /app

USER delaxis

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/app/.venv/bin:$PATH"
# development = open access out of the box; set ENVIRONMENT=production
# (plus auth) before exposing the instance publicly — see SECURITY.md
ENV ENVIRONMENT=development

VOLUME /app/data

# Expose API (+ Studio UI) and metrics ports
EXPOSE 8000 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${APP_PORT:-8000}/health || exit 1

# Run the FastAPI application — APP_PORT env var controls the listening port
CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${APP_PORT:-8000}"]
