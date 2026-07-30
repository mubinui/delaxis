"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from src.api.exception_handlers import register_exception_handlers
from src.api.lifespan import lifespan
from src.api.middleware import jwt_validation_middleware, request_logging_middleware
from src.api.rate_limiting import limiter, rate_limit_exceeded_handler, rate_limiting_middleware
from src.api.router_registry import register_routers
from src.api.static_files import mount_spa
from src.audit_logging import configure_logging
from src.config.settings import get_settings


def create_app() -> FastAPI:
    """Create and configure the Delaxis API."""
    configure_logging()

    app = FastAPI(
        title="Delaxis",
        description="Open-source multi-agent development kit for building, testing, and deploying AI agent workflows",
        version="0.1.0",
        lifespan=lifespan,
    )

    settings = get_settings()
    cors_origins = [origin.strip() for origin in settings.app.frontend_url.split(",") if origin.strip()]
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
        "version": "0.1.0",
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
