"""Structured FastAPI exception handlers."""

import time
import uuid

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors with a stable response shape."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.warning(
        "validation_error",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        errors=exc.errors(),
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error_code": "VALIDATION_ERROR",
            "error_message": "Request validation failed",
            "error_type": "ValidationError",
            "request_id": request_id,
            "timestamp": time.time(),
            "details": exc.errors(),
        },
    )


async def general_exception_handler(request: Request, exc: Exception):
    """Handle unhandled exceptions without exposing internals."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.error(
        "unhandled_exception",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        error=str(exc),
        exc_info=True,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error_code": "INTERNAL_SERVER_ERROR",
            "error_message": "An unexpected error occurred",
            "error_type": type(exc).__name__,
            "request_id": request_id,
            "timestamp": time.time(),
            "details": None,
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach project exception handlers to the FastAPI app."""
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
