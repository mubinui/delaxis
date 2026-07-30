"""Health check and metrics endpoints."""

import time
from typing import Any, Dict

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

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
        version="0.1.0",
    )


@router.get("/health/ready")
async def readiness_check(request: Request) -> Dict[str, Any]:
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
        try:
            from src.infrastructure.cache import get_cache_manager
            
            cache_manager = get_cache_manager()
            checks["redis"] = "ok" if cache_manager.health_check() else "failed"
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            checks["redis"] = "failed"
    
    # Determine overall status
    # Fail-fast: if MongoDB is configured and fails, service is not ready
    all_ok = all(status == "ok" for status in checks.values())
    
    if not all_ok:
        logger.warning(f"Readiness check failed: {checks}")
    
    return {
        "status": "ready" if all_ok else "not_ready",
        "service": "delaxis",
        "version": "0.1.0",
        "timestamp": time.time(),
        "checks": checks,
    }


@router.get("/health/live")
async def liveness_check(request: Request) -> Dict[str, Any]:
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
        "version": "0.1.0",
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
async def dashboard_metrics(request: Request) -> Dict[str, Any]:
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
            "openrouter_presets": config.get_openrouter_presets() if config.provider.value == "openrouter" else None,
        }
    except Exception as e:
        llm_info = {"error": str(e)}
    
    return {
        "total_agents": 0,
        "total_tools": 0,
        "total_workflows": 0,
        "active_sessions": 0,
        "total_messages": 0,
        "cache_hit_rate": 0.0,
        "avg_response_time": 0.0,
        "error_rate": 0.0,
        "llm_provider": llm_info,
    }
