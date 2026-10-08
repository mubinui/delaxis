#!/usr/bin/env bash
# Start the API for the end-to-end suite in a throwaway working directory.
#
# Config, session and database paths are relative to the working directory,
# so running from a temp dir that holds a *copy* of configs/ means a test that
# saves a workflow can never modify the shipped files, and every run starts
# from the same state. No .env is read and Redis is off, so nothing on the
# developer's machine leaks into the run.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/delaxis-e2e.XXXXXX")"
cp -R "$REPO/configs" "$WORK/configs"
cp "$REPO/alembic.ini" "$WORK/alembic.ini"
cp -R "$REPO/alembic" "$WORK/alembic"
mkdir -p "$WORK/data"

cd "$WORK"
export ENVIRONMENT=development
export REDIS_URL=""
export LOG_LEVEL=WARNING
# One browser replaying every page several times a minute is not a user; the
# limiter's behaviour is covered by tests/unit/test_rate_limit_response.py.
export REQUESTS_PER_MINUTE=100000
export REQUESTS_PER_HOUR=1000000
export READ_REQUESTS_PER_MINUTE=100000
export READ_REQUESTS_PER_HOUR=1000000
export DELAXIS_STATIC_DIR="$REPO/workflow-editor/dist"
export PYTHONPATH="$REPO"
exec uv run --project "$REPO" --no-sync uvicorn src.api.main:app --host 127.0.0.1 --port "${E2E_PORT:-8799}"
