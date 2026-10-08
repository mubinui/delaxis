"""Reusable FastAPI middleware functions."""

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response

from src.api.context import set_request_user
from src.audit_logging import bind_correlation_ids, clear_correlation_ids
from src.config.settings import get_settings
from src.observability.metrics import track_http_request

logger = structlog.get_logger(__name__)

CallNext = Callable[[Request], Awaitable[Response]]

PUBLIC_PATHS = {
    "/",
    "/docs",
    "/openapi.json",
    "/health",
    "/metrics",
    "/api/v1/auth/token",
}


async def request_logging_middleware(request: Request, call_next: CallNext) -> Response:
    """Log requests with correlation IDs, timing, and metrics."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    bind_correlation_ids(request_id=request_id)

    start_time = time.time()
    logger.info(
        "request_started",
        method=request.method,
        path=request.url.path,
        client_host=request.client.host if request.client else None,
    )

    try:
        response = await call_next(request)
        duration = time.time() - start_time
        track_http_request(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code,
            duration=duration,
        )
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_seconds=duration,
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        duration = time.time() - start_time
        track_http_request(
            method=request.method,
            endpoint=request.url.path,
            status=500,
            duration=duration,
        )
        logger.error(
            "request_failed",
            method=request.method,
            path=request.url.path,
            duration_seconds=duration,
            error=str(exc),
            exc_info=True,
        )
        raise
    finally:
        clear_correlation_ids()


async def jwt_validation_middleware(request: Request, call_next: CallNext) -> Response:
    """Validate JWT tokens and add user context to request state."""
    settings = get_settings()

    if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/static"):
        return await call_next(request)

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        request.state.auth_token = token

        from src.api.keycloak_auth import extract_client_headers

        roles, username = extract_client_headers(request)
        request.state.client_roles = roles
        request.state.client_username = username

        if settings.keycloak.enabled:
            from src.api.auth import CurrentUser, UserRole
            from src.api.keycloak_auth import validate_keycloak_token

            try:
                token_data = await validate_keycloak_token(token)
                request.state.keycloak_user = token_data
                request.state.keycloak_authenticated = True

                primary_role = UserRole.ADMIN if "admin" in token_data.roles else UserRole.USER
                effective_username = username or token_data.preferred_username
                effective_roles = roles if roles else token_data.roles

                set_request_user(
                    CurrentUser(
                        user_id=None,
                        username=effective_username,
                        role=primary_role,
                        roles=effective_roles,
                        auth_method="keycloak",
                        raw_token=token,
                    )
                )

                logger.debug(
                    "keycloak_token_validated",
                    username=effective_username,
                    roles=effective_roles,
                    primary_role=primary_role.value,
                )
            except Exception as exc:
                logger.warning("keycloak_validation_failed", error=str(exc))
                request.state.keycloak_authenticated = False
        else:
            logger.debug("jwt_validation_attempt", path=request.url.path)

    return await call_next(request)
