# Contributing to Delaxis

Thanks for your interest in contributing! This document covers the essentials.

## Development setup

Backend (Python 3.10+, managed with [uv](https://docs.astral.sh/uv/)):

```bash
uv sync --extra dev
uv run uvicorn src.api.main:app --reload
```

Studio frontend (Node 22+):

```bash
cd workflow-editor
npm ci
npm run dev
```

The Vite dev server proxies `/api`, `/health`, and `/d` to `http://localhost:8000`.

## Before you open a PR

```bash
uv run pytest tests/unit -q            # all unit tests must pass
uv run ruff check src                  # backend lint
cd workflow-editor && npm run lint     # frontend lint (0 errors)
npm run build                          # frontend must build
```

If your change affects the Docker image, verify `docker build -t delaxis .` succeeds
and the container boots (`docker run -p 8000:8000 delaxis`, then check `/health`).

## Conventions

- **Configs are contracts** — `configs/*.json` shapes are validated by the pydantic models
  in `src/config/`. Change both together, and add/extend a unit test.
- **No fake results** — endpoints and UI components must surface real errors, never
  fabricated success output.
- **Same-origin by default** — the SPA and deployed chat pages use relative URLs;
  never hardcode hosts or ports.
- **Database** — schema lives in `src/infrastructure/database/schema.py` (dialect-neutral:
  SQLite + PostgreSQL). Generate migrations with
  `DATABASE_URL=sqlite:///./data/delaxis.db uv run alembic revision --autogenerate -m "..."`.

## Reporting issues

Use GitHub Issues. Include reproduction steps, expected vs. actual behavior, and
relevant log output (`LOG_LEVEL=DEBUG` gives verbose logs).

## Security

Please report security vulnerabilities privately — see [SECURITY.md](SECURITY.md).
