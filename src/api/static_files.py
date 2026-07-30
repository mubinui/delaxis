"""Serve the built Studio SPA from FastAPI.

The production Docker image copies the Vite build output to ``./static``.
When that directory exists, the SPA is served at ``/`` with an index.html
fallback for client-side routes. API routes, docs, health checks, metrics,
and deployed chatbot pages (``/d/...``) are never shadowed.

In development the directory is usually absent — the Vite dev server
(``npm run dev`` in workflow-editor/) proxies API calls instead.
"""

from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.config.env_compat import env

logger = structlog.get_logger(__name__)

# Path prefixes owned by the backend — the SPA fallback must never swallow them
RESERVED_PREFIXES = ("api", "docs", "redoc", "openapi.json", "health", "metrics", "d")


def mount_spa(app: FastAPI) -> bool:
    """Mount the built SPA if a static directory is present.

    Returns True when the SPA was mounted.
    """
    static_dir = Path(env("DELAXIS_STATIC_DIR", "./static") or "./static").resolve()
    index_file = static_dir / "index.html"

    if not index_file.exists():
        logger.info(
            "spa_not_mounted",
            hint="build the studio (cd workflow-editor && npm run build) and copy dist/ to ./static, "
            "or use the Docker image which bundles it",
            static_dir=str(static_dir),
        )
        return False

    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="spa-assets")

    @app.get("/", include_in_schema=False)
    async def spa_index() -> FileResponse:
        return FileResponse(index_file, media_type="text/html")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa_fallback(path: str) -> FileResponse:
        first_segment = path.split("/", 1)[0]
        if first_segment in RESERVED_PREFIXES:
            # Let FastAPI's normal 404 handling apply to backend paths
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not Found")

        candidate = (static_dir / path).resolve()
        # Serve real static files (favicon, manifest, ...) if they exist
        if candidate.is_file() and str(candidate).startswith(str(static_dir)):
            return FileResponse(candidate)
        # Everything else falls back to the SPA entry point
        return FileResponse(index_file, media_type="text/html")

    logger.info("spa_mounted", static_dir=str(static_dir))
    return True
