"""Rate limiting middleware and utilities."""

import time
from typing import Dict, Optional

import structlog
from fastapi import Request, status
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.config.settings import get_settings

logger = structlog.get_logger(__name__)


def get_user_id_for_rate_limiting(request: Request) -> str:
    """
    Get user identifier for rate limiting.
    
    Priority:
    1. API key ID (if authenticated with API key)
    2. User ID (if authenticated with JWT)
    3. IP address (fallback for unauthenticated requests)
    """
    # Check if user is authenticated
    if hasattr(request.state, 'current_user'):
        current_user = request.state.current_user
        
        # Use API key ID if available (more specific)
        if current_user.api_key_id:
            return f"api_key:{current_user.api_key_id}"
        
        # Use user ID if available
        if current_user.user_id:
            return f"user:{current_user.user_id}"
    
    # Fallback to IP address
    return f"ip:{get_remote_address(request)}"


def get_api_key_id_for_rate_limiting(request: Request) -> Optional[str]:
    """Get API key ID for API key specific rate limiting."""
    if hasattr(request.state, 'current_user'):
        current_user = request.state.current_user
        if current_user.api_key_id:
            return str(current_user.api_key_id)
    return None


# Create limiter instance
settings = get_settings()
limiter = Limiter(
    key_func=get_user_id_for_rate_limiting,
    default_limits=[
        f"{settings.security.requests_per_minute}/minute",
        f"{settings.security.requests_per_hour}/hour"
    ]
)


class RateLimitingMiddleware:
    """Custom rate limiting middleware with different limits for different user types."""
    
    def __init__(self):
        self.settings = get_settings()
        self._rate_limit_store: Dict[str, Dict[str, float]] = {}
    
    def _get_rate_limit_key(self, identifier: str, window: str) -> str:
        """Generate rate limit key."""
        return f"{identifier}:{window}"
    
    def _is_rate_limited(self, identifier: str, requests_per_window: int, window_seconds: int) -> bool:
        """Check if identifier is rate limited."""
        now = time.time()
        window_start = now - window_seconds
        
        # Clean old entries
        if identifier not in self._rate_limit_store:
            self._rate_limit_store[identifier] = {}
        
        # Remove old timestamps
        self._rate_limit_store[identifier] = {
            k: v for k, v in self._rate_limit_store[identifier].items()
            if v > window_start
        }
        
        # Check current count
        current_count = len(self._rate_limit_store[identifier])
        
        if current_count >= requests_per_window:
            return True
        
        # Add current request
        request_key = f"{now}:{hash(str(now))}"
        self._rate_limit_store[identifier][request_key] = now
        
        return False
    
    @staticmethod
    def _too_many_requests(
        request: Request,
        message: str,
        retry_after: int,
        limit: int,
        window: str,
    ) -> JSONResponse:
        """Build the 429 response.

        This returns rather than raises. An HTTPException raised inside an
        ``app.middleware("http")`` function never reaches FastAPI's exception
        handlers — those are installed inside the routing layer, below this —
        so it fell through to ServerErrorMiddleware and the client was told
        every throttled request was a 500. Returning the response keeps the
        status honest and preserves the Retry-After header, which a client
        needs in order to back off correctly.
        """
        import uuid

        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error_code": "RATE_LIMIT_EXCEEDED",
                "error_message": message,
                "error_type": "RateLimitExceeded",
                "request_id": request_id,
                "timestamp": time.time(),
                "details": {"limit": limit, "window": window, "retry_after_seconds": retry_after},
            },
            headers={"Retry-After": str(retry_after)},
        )

    async def __call__(self, request: Request, call_next):
        """Apply rate limiting based on user type."""
        # Skip rate limiting for health checks and static files
        if request.url.path in ["/health", "/metrics"] or request.url.path.startswith("/static"):
            return await call_next(request)
        
        # Get user identifier
        user_id = get_user_id_for_rate_limiting(request)
        api_key_id = get_api_key_id_for_rate_limiting(request)
        
        # Determine rate limits based on authentication method
        if api_key_id:
            # API key users get higher limits
            requests_per_minute = self.settings.security.api_key_requests_per_minute
            requests_per_hour = self.settings.security.api_key_requests_per_hour
        else:
            # Regular users and unauthenticated requests
            requests_per_minute = self.settings.security.requests_per_minute
            requests_per_hour = self.settings.security.requests_per_hour
        
        # Check minute-based rate limit
        if self._is_rate_limited(f"{user_id}:minute", requests_per_minute, 60):
            logger.warning(
                "rate_limit_exceeded_minute",
                user_id=user_id,
                api_key_id=api_key_id,
                limit=requests_per_minute,
                path=request.url.path
            )
            return self._too_many_requests(
                request,
                f"Rate limit exceeded: {requests_per_minute} requests per minute",
                retry_after=60,
                limit=requests_per_minute,
                window="minute",
            )

        # Check hour-based rate limit
        if self._is_rate_limited(f"{user_id}:hour", requests_per_hour, 3600):
            logger.warning(
                "rate_limit_exceeded_hour",
                user_id=user_id,
                api_key_id=api_key_id,
                limit=requests_per_hour,
                path=request.url.path
            )
            return self._too_many_requests(
                request,
                f"Rate limit exceeded: {requests_per_hour} requests per hour",
                retry_after=3600,
                limit=requests_per_hour,
                window="hour",
            )
        
        # Log successful rate limit check
        logger.debug(
            "rate_limit_check_passed",
            user_id=user_id,
            api_key_id=api_key_id,
            path=request.url.path
        )
        
        return await call_next(request)


# Global rate limiting middleware instance
rate_limiting_middleware = RateLimitingMiddleware()


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Custom rate limit exceeded handler."""
    user_id = get_user_id_for_rate_limiting(request)
    api_key_id = get_api_key_id_for_rate_limiting(request)
    
    logger.warning(
        "slowapi_rate_limit_exceeded",
        user_id=user_id,
        api_key_id=api_key_id,
        path=request.url.path,
        detail=str(exc.detail)
    )
    
    return _rate_limit_exceeded_handler(request, exc)


# Decorator for endpoint-specific rate limiting
def endpoint_rate_limit(rate: str):
    """Decorator for endpoint-specific rate limiting."""
    return limiter.limit(rate)


# Common rate limit decorators
def strict_rate_limit(rate: str = "10/minute"):
    """Strict rate limit for sensitive endpoints."""
    return limiter.limit(rate)


def api_key_rate_limit(rate: str = "100/minute"):
    """Rate limit for API key authenticated endpoints."""
    def decorator(func):
        return limiter.limit(
            rate,
            key_func=lambda request: get_api_key_id_for_rate_limiting(request) or get_remote_address(request)
        )(func)
    return decorator


def user_rate_limit(rate: str = "60/minute"):
    """Rate limit for user authenticated endpoints."""
    return limiter.limit(rate)