"""Health check and metrics endpoints."""

import time
from typing import Any

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src import __version__
from src.api.models import HealthResponse
from src.audit_logging import get_logger
from src.observability.metrics import get_metrics_registry

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """
    Health check endpoint for liveness probes.

    Args:
        request: FastAPI request object

    Returns:
        Health status information

    Requirements: 6.3, 14.1, 14.2
    """
    return HealthResponse(
        status="healthy",
        service="delaxis",
        version=__version__,
    )


@router.get("/health/ready")
async def readiness_check(request: Request) -> dict[str, Any]:
    """
    Readiness check endpoint for readiness probes.

    This endpoint checks if the service is ready to accept traffic
    by verifying that all dependencies are available.

    Args:
        request: FastAPI request object

    Returns:
        Readiness status information

    Requirements: 6.3, 14.1, 14.2, 16.3, 16.4
    """
    from src.config.settings import get_settings

    settings = get_settings()
    checks = {}

    # MongoDB removed - no longer required
    # Using PostgreSQL for all storage needs

    # Check Redis cache
    if settings.memory.redis_url:
        from src.infrastructure.redis_guard import redis_reachable

        checks["redis"] = "ok" if redis_reachable(settings.memory.redis_url) else "failed"

    # Determine overall status
    # Fail-fast: if MongoDB is configured and fails, service is not ready
    all_ok = all(status == "ok" for status in checks.values())

    if not all_ok:
        logger.warning(f"Readiness check failed: {checks}")

    return {
        "status": "ready" if all_ok else "not_ready",
        "service": "delaxis",
        "version": __version__,
        "timestamp": time.time(),
        "checks": checks,
    }


@router.get("/health/live")
async def liveness_check(request: Request) -> dict[str, Any]:
    """
    Liveness check endpoint for liveness probes.

    This endpoint checks if the service is alive and responding.
    It should return quickly and not depend on external services.

    Args:
        request: FastAPI request object

    Returns:
        Liveness status information

    Requirements: 6.3, 14.1, 14.2
    """
    return {
        "status": "alive",
        "service": "delaxis",
        "version": __version__,
        "timestamp": time.time(),
    }


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    """
    Prometheus metrics endpoint.

    This endpoint exposes metrics in Prometheus text format.

    Args:
        request: FastAPI request object

    Returns:
        Prometheus metrics in text format

    Requirements: 6.3, 14.1, 14.2
    """
    registry = get_metrics_registry()
    metrics_output = generate_latest(registry)

    return Response(
        content=metrics_output,
        media_type=CONTENT_TYPE_LATEST,
    )


@router.get("/metrics/dashboard")
async def dashboard_metrics(request: Request) -> dict[str, Any]:
    """
    Dashboard metrics endpoint for frontend UI.

    This endpoint provides a JSON structure with key metrics
    for the admin dashboard.

    Args:
        request: FastAPI request object

    Returns:
        Dashboard metrics as JSON
    """
    # Get LLM provider info
    llm_info = {}
    try:
        from src.config.llm_provider import get_provider_config

        config = get_provider_config()
        llm_info = {
            "provider": config.provider.value,
            "model": config.model_name,
            "openrouter_presets": config.get_openrouter_presets()
            if config.provider.value == "openrouter"
            else None,
        }
    except Exception as e:
        llm_info = {"error": str(e)}

    from src.api.session_manager import get_session_manager
    from src.config.config_loader import get_config_loader
    from src.observability.metrics import dashboard_summary

    loader = get_config_loader()
    sessions = await get_session_manager().list_sessions(active_only=False)
    return {
        "total_agents": len(loader.get_agents()),
        "total_tools": len(loader.get_tools()),
        "total_workflows": len(loader.get_workflows()),
        "active_sessions": sum(1 for session in sessions if session.active),
        "total_sessions": len(sessions),
        "total_messages": sum(len(session.messages) for session in sessions),
        **dashboard_summary(),
        "llm_provider": llm_info,
    }
