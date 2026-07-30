"""FastAPI application lifecycle management."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI

from src.config.config_loader import get_config_loader
from src.config.env_compat import env
from src.config.llm_provider import get_provider_config
from src.config.settings import get_settings
from src.observability.tracing import configure_tracing, instrument_fastapi

logger = structlog.get_logger(__name__)


def _warn_on_legacy_database_file(url: str) -> None:
    """Warn when the pre-rename SQLite file exists but the new one does not.

    The default database moved from ``data/oak.db`` to ``data/delaxis.db`` in
    the Delaxis rename. Without this warning the app would happily migrate a
    brand-new empty database and the existing users, API keys and config
    snapshots would look like they had vanished. Moving the file automatically
    would be worse — silent data motion is harder to reason about than a loud
    message — so this only tells the operator what to run.
    """
    if not url.startswith("sqlite"):
        return
    _, _, path_part = url.partition(":///")
    if not path_part:
        return
    current = Path(path_part)
    legacy = current.with_name("oak.db")
    if current.exists() or not legacy.exists():
        return
    logger.warning(
        "database_legacy_file_found",
        legacy=str(legacy),
        expected=str(current),
        detail=f"Pre-rename database found. Run: mv {legacy} {current}",
    )


def _run_database_migrations() -> None:
    """Apply Alembic migrations so a fresh install works with zero setup.

    Skippable via DELAXIS_AUTO_MIGRATE=false (e.g. when migrations are managed
    externally in production).
    """
    if (env("DELAXIS_AUTO_MIGRATE", "true") or "true").lower() in ("0", "false", "no"):
        logger.info("database_auto_migration_skipped")
        return

    try:
        from alembic import command
        from alembic.config import Config

        project_root = Path(__file__).resolve().parents[2]
        alembic_cfg = Config(str(project_root / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(project_root / "alembic"))

        # Alembic needs a sync driver URL
        settings = get_settings()
        url = settings.database_url
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
        url = url.replace("sqlite+aiosqlite://", "sqlite://", 1)
        _warn_on_legacy_database_file(url)
        alembic_cfg.set_main_option("sqlalchemy.url", url)

        command.upgrade(alembic_cfg, "head")
        logger.info("database_migrations_applied", database=url.split("@")[-1])
    except Exception as exc:
        logger.error("database_migration_failed", error=str(exc), exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and clean up application-wide services."""
    settings = get_settings()
    logger.info(
        "delaxis_starting",
        log_level=settings.app.log_level,
        environment=settings.app.environment,
    )

    # Ensure the data directory exists (SQLite DB, sessions, deployments)
    Path("./data").mkdir(parents=True, exist_ok=True)

    _run_database_migrations()

    try:
        from src.api.auth import bootstrap_admin_user

        bootstrap_admin_user()
    except Exception as exc:
        logger.warning("admin_bootstrap_failed", error=str(exc))

    try:
        provider_config = get_provider_config()
        logger.info(
            "llm_provider_configured",
            provider=provider_config.provider.value,
            model=provider_config.model_name,
            fallback_provider=(
                provider_config.fallback_provider.value
                if provider_config.fallback_provider
                else None
            ),
            cache_enabled=provider_config.enable_cache,
        )
        logger.info("llm_provider_ready", note="connection_test_skipped_for_fast_startup")
    except Exception as exc:
        logger.error("llm_provider_initialization_failed", error=str(exc), exc_info=True)

    enable_hot_reload = settings.app.environment == "development"
    try:
        config_loader = get_config_loader(enable_hot_reload=enable_hot_reload)
        logger.info(
            "config_loader_initialized",
            hot_reload=enable_hot_reload,
            config_dir=str(config_loader.config_dir),
        )
    except Exception as exc:
        logger.error("config_loader_initialization_failed", error=str(exc))

    try:
        configure_tracing()
        instrument_fastapi(app)
    except Exception as exc:
        logger.warning("tracing_configuration_failed", error=str(exc))

    yield

    logger.info("delaxis_shutting_down")
    try:
        config_loader = get_config_loader()
        config_loader.stop_file_watcher()
    except Exception as exc:
        logger.warning("config_loader_cleanup_failed", error=str(exc))