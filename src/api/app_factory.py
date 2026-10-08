"""FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from src import __version__
from src.api.exception_handlers import register_exception_handlers
from src.api.lifespan import lifespan
from src.api.middleware import jwt_validation_middleware, request_logging_middleware
from src.api.rate_limiting import limiter, rate_limit_exceeded_handler, rate_limiting_middleware
from src.api.router_registry import register_routers
from src.api.static_files import mount_spa
from src.audit_logging import configure_logging, get_logger
from src.config.paths import config_dir, seed_config_dir
from src.config.settings import get_settings
from src.infrastructure.redis_guard import ensure_redis_or_disable

logger = get_logger(__name__)

# The configs the code ships with. The Docker image keeps its working copy on
# the data volume (DELAXIS_CONFIG_DIR) so Studio edits outlive the container,
# and fills it from here on first boot.
_BUNDLED_CONFIGS = Path(__file__).resolve().parents[2] / "configs"


def _seed_config_dir() -> None:
    from src.config.env_compat import env

    bundled = Path(env("DELAXIS_BUNDLED_CONFIG_DIR", str(_BUNDLED_CONFIGS)) or _BUNDLED_CONFIGS)
    copied = seed_config_dir(bundled)
    if copied:
        logger.info("config_dir_seeded", config_dir=str(config_dir()), files=copied)


def create_app() -> FastAPI:
    """Create and configure the Delaxis API."""
    configure_logging()
    ensure_redis_or_disable()
    _seed_config_dir()

    app = FastAPI(
        # Delaxis configures OpenTelemetry itself (src/observability/tracing.py).
        # FastAPI 0.142 would also build exporters from OTEL_* variables, and
        # with no collector listening it then waited out a 15-second flush on
        # every shutdown.
        telemetry={"auto_configure": False},
        title="Delaxis",
        description="Open-source multi-agent development kit for building, testing, and deploying AI agent workflows",
        version=__version__,
        lifespan=lifespan,
    )

    settings = get_settings()
    cors_origins = [
        origin.strip() for origin in settings.app.frontend_url.split(",") if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.middleware("http")(request_logging_middleware)
    app.middleware("http")(jwt_validation_middleware)
    app.middleware("http")(rate_limiting_middleware)

    register_exception_handlers(app)
    register_routers(app)

    api_info = {
        "service": "Delaxis",
        "product": "Delaxis",
        "version": __version__,
        "description": "Open-source multi-agent development kit for building, testing, and deploying AI agent workflows",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }

    @app.get("/api")
    async def api_root() -> dict[str, str]:
        """API information endpoint."""
        return api_info

    @app.get("/health", include_in_schema=False)
    async def health_alias() -> dict[str, str]:
        """Lightweight liveness alias used by container healthchecks."""
        return {"status": "healthy", "service": "delaxis"}

    # Serve the built Studio SPA (if present) — registered last so its
    # catch-all route never shadows API endpoints. When no SPA build is
    # available (dev mode), the root serves API info instead.
    spa_mounted = mount_spa(app)
    if not spa_mounted:

        @app.get("/")
        async def root() -> dict[str, str]:
            """Root endpoint with API information (replaced by the Studio SPA when built)."""
            return api_info

    return app
