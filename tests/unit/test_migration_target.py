"""Startup migrates the database the app reads, whatever DATABASE_URL says by then.

Settings are read early, from the working directory's .env. CrewAI later calls
a bare load_dotenv(), which can find a different .env (the repository's, from
inside .venv) and put its DATABASE_URL into the environment. Alembic's env.py
used to prefer that variable, so the tables were created in one file and the
app queried another, which had no tables at all.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_migrations_target_the_apps_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.api import lifespan

    app_db = tmp_path / "app.db"
    stray_db = tmp_path / "stray.db"
    monkeypatch.setattr(
        lifespan, "get_settings", lambda: SimpleNamespace(database_url=f"sqlite:///{app_db}")
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{stray_db}")
    monkeypatch.setenv("DELAXIS_AUTO_MIGRATE", "true")

    lifespan._run_database_migrations()

    tables = {
        name
        for (name,) in sqlite3.connect(app_db).execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"sessions", "integration_credentials", "alembic_version"} <= tables
    assert not stray_db.exists() or stray_db.stat().st_size == 0
