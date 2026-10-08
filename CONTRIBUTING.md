# Contributing to Delaxis

Thanks for your interest in contributing! This document covers the essentials.

## Development setup

Backend (Python 3.11+, managed with [uv](https://docs.astral.sh/uv/)):

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

CI runs all of these on every push; run them locally first.

```bash
uv run ruff check src tests scripts && uv run ruff format --check src tests scripts
uv run mypy src                         # strict; must stay at zero errors
uv run pytest -q                        # all tests must pass
uv run python scripts/check_configs.py  # shipped configs load and round-trip

cd workflow-editor
npm run lint -- --max-warnings 0
npx tsc -b && npm test && npm run build
npx playwright test                     # end-to-end against the real API
```

If you change how a workflow behaves, run `uv run python scripts/eval_starters.py`
(needs a provider key) and keep it at or above its threshold.

If your change affects the Docker image, run `scripts/smoke_docker.sh` after
`docker build -t delaxis .`: it boots the image, exercises the API and checks
that configs survive recreating the container.

## Conventions

- **Configs are contracts** — `configs/*.json` shapes are validated by the pydantic models
  in `src/config/`. Change both together, and add/extend a unit test.
- **No fake results** — endpoints and UI components must surface real errors, never
  fabricated success output. An endpoint that cannot do something says so; it does
  not answer 201 and do nothing.
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
