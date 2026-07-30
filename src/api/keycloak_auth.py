"""Keycloak JWKS-based token validation and authentication utilities."""

import json
from typing import Any, Optional

import httpx
import structlog
from cachetools import TTLCache
from fastapi import HTTPException, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel

from src.config.settings import get_settings

logger = structlog.get_logger(__name__)

# Cache for JWKS keys - will be initialized with TTL from settings
_jwks_cache: TTLCache | None = None


def _get_jwks_cache() -> TTLCache:
    """Get or initialize the JWKS cache with configured TTL."""
    global _jwks_cache
    if _jwks_cache is None:
        settings = get_settings()
        _jwks_cache = TTLCache(maxsize=1, ttl=settings.keycloak.jwks_cache_ttl)
    return _jwks_cache


class KeycloakTokenData(BaseModel):
    """Decoded Keycloak token claims."""

    sub: str
    preferred_username: Optional[str] = None
    email: Optional[str] = None
    email_verified: Optional[bool] = None
    name: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    realm_access: Optional[dict[str, Any]] = None
    resource_access: Optional[dict[str, Any]] = None
    authorities: Optional[list[str]] = None  # Direct authorities claim (custom Keycloak mappers)
    scope: Optional[str] = None
    azp: Optional[str] = None  # Authorized party (client_id)
    iss: Optional[str] = None  # Issuer
    exp: Optional[int] = None  # Expiration
    iat: Optional[int] = None  # Issued at

    @property
    def roles(self) -> list[str]:
        """Extract roles from token - checks authorities first, then realm_access."""
        # Check authorities claim first (custom Keycloak setups)
        if self.authorities:
            return self.authorities
        # Fall back to realm_access.roles
        if self.realm_access and "roles" in self.realm_access:
            return self.realm_access["roles"]
        return []

    @property
    def client_roles(self) -> dict[str, list[str]]:
        """Extract client-specific roles from token."""
        if self.resource_access:
            return {
                client: access.get("roles", [])
                for client, access in self.resource_access.items()
            }
        return {}

    def has_role(self, role: str) -> bool:
        """Check if user has a specific realm role."""
        return role in self.roles

    def has_client_role(self, client_id: str, role: str) -> bool:
        """Check if user has a specific client role."""
        client_roles = self.client_roles.get(client_id, [])
        return role in client_roles


class KeycloakAuthContext(BaseModel):
    """Authentication context extracted from request."""

    token_data: Optional[KeycloakTokenData] = None
    client_roles: Optional[list[str]] = None  # From x-client-ref header
    client_username: Optional[str] = None  # From x-client-username header
    is_keycloak_authenticated: bool = False
    raw_token: Optional[str] = None


async def fetch_jwks() -> dict[str, Any]:
    """Fetch JWKS from Keycloak (cached)."""
    settings = get_settings()
    cache = _get_jwks_cache()

    if "jwks" in cache:
        logger.debug("jwks_cache_hit")
        return cache["jwks"]

    logger.info("fetching_jwks", jwks_uri=settings.keycloak.jwks_uri)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(settings.keycloak.jwks_uri, timeout=10)
            response.raise_for_status()
            jwks_data = response.json()
            cache["jwks"] = jwks_data
            logger.info("jwks_fetched_successfully", key_count=len(jwks_data.get("keys", [])))
            return jwks_data
    except httpx.HTTPError as e:
        logger.error("jwks_fetch_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to fetch JWKS from Keycloak",
        )


def clear_jwks_cache() -> None:
    """Clear the JWKS cache (useful for testing or forced refresh)."""
    global _jwks_cache
    if _jwks_cache is not None:
        _jwks_cache.clear()
    logger.info("jwks_cache_cleared")


async def validate_keycloak_token(token: str) -> KeycloakTokenData:
    """
    Validate Keycloak JWT using JWKS.

    Args:
        token: The Bearer token to validate

    Returns:
        KeycloakTokenData with decoded claims

    Raises:
        HTTPException: If token is invalid or validation fails
    """
    settings = get_settings()

    try:
        # Get the key ID from the token header without verification
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing key ID (kid)",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Fetch JWKS and find matching key
        jwks_data = await fetch_jwks()
        rsa_key = None
        for key in jwks_data.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = key
                break

        if not rsa_key:
            logger.warning("jwks_key_not_found", kid=kid)
            # Clear cache and retry once in case keys were rotated
            clear_jwks_cache()
            jwks_data = await fetch_jwks()
            for key in jwks_data.get("keys", []):
                if key.get("kid") == kid:
                    rsa_key = key
                    break

        if not rsa_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find matching signing key",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Build decode options
        decode_options = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_iat": True,
            "verify_aud": settings.keycloak.verify_audience,
        }

        # Decode and validate token
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=settings.keycloak.client_id if settings.keycloak.verify_audience else None,
            issuer=settings.keycloak.issuer,
            options=decode_options,
        )

        token_data = KeycloakTokenData(**payload)
        logger.debug(
            "keycloak_token_validated",
            sub=token_data.sub,
            username=token_data.preferred_username,
            roles=token_data.roles,
        )
        return token_data

    except JWTError as e:
        logger.warning("keycloak_token_validation_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("keycloak_token_validation_error", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


def extract_client_headers(request: Request) -> tuple[Optional[list[str]], Optional[str]]:
    """
    Extract x-client-ref (roles) and x-client-username headers from request.

    These headers are used for Service2-style calls where the admin token
    carries context about the original user.

    Args:
        request: FastAPI request object

    Returns:
        Tuple of (roles list, username) - either may be None
    """
    roles_header = request.headers.get("x-client-ref")
    username_header = request.headers.get("x-client-username")

    roles = None
    if roles_header:
        try:
            # Try JSON array format first
            parsed = json.loads(roles_header)
            if isinstance(parsed, list):
                roles = parsed
            else:
                roles = [str(parsed)]
        except json.JSONDecodeError:
            # Fall back to comma-separated format
            roles = [r.strip() for r in roles_header.split(",") if r.strip()]

    return roles, username_header


async def get_keycloak_auth_context(request: Request) -> KeycloakAuthContext:
    """
    Extract full authentication context from request.

    Validates Keycloak token if present and extracts client headers.

    Args:
        request: FastAPI request object

    Returns:
        KeycloakAuthContext with all authentication information
    """
    settings = get_settings()
    context = KeycloakAuthContext()

    # Extract client headers (for Service2-style calls)
    context.client_roles, context.client_username = extract_client_headers(request)

    # Extract and validate Bearer token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        context.raw_token = auth_header.split(" ", 1)[1]

        if settings.keycloak.enabled:
            try:
                context.token_data = await validate_keycloak_token(context.raw_token)
                context.is_keycloak_authenticated = True
            except HTTPException:
                # Token validation failed - context remains unauthenticated
                pass

    return context


async def get_admin_token() -> str:
    """
    Obtain admin token from Keycloak using client_credentials grant.

    This is used for Service2-style calls where Delaxis
    needs to call downstream services with an admin/service account.

    Returns:
        Access token string

    Raises:
        HTTPException: If token acquisition fails
    """
    settings = get_settings()

    if not settings.keycloak.admin_client_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Keycloak admin client secret not configured",
        )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                settings.keycloak.token_endpoint,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.keycloak.admin_client_id,
                    "client_secret": settings.keycloak.admin_client_secret,
                },
                timeout=10,
            )
            response.raise_for_status()
            token_response = response.json()
            logger.info("admin_token_acquired", client_id=settings.keycloak.admin_client_id)
            return token_response["access_token"]

    except httpx.HTTPError as e:
        logger.error("admin_token_acquisition_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to acquire admin token from Keycloak",
        )
