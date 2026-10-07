"""Authentication and authorization API endpoints."""

from datetime import timedelta
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

from src.api.auth import (
    APIKeyCreate,
    APIKeyInfo,
    APIKeyManager,
    APIKeyResponse,
    CurrentUser,
    Token,
    UserCreate,
    UserManager,
    UserResponse,
    create_access_token,
    get_current_user,
    require_admin,
    require_user,
)
from src.config.settings import get_settings

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token")


class AuthConfig(BaseModel):
    """Public authentication configuration for frontend."""

    enabled: bool
    server_url: str
    realm: str
    client_id: str


@router.get("/config", response_model=AuthConfig)
async def get_auth_config():
    """Get public authentication configuration."""
    settings = get_settings()
    return AuthConfig(
        enabled=settings.keycloak.enabled,
        server_url=settings.keycloak.server_url,
        realm=settings.keycloak.realm,
        client_id=settings.keycloak.client_id,
    )


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """Authenticate user and return JWT token."""
    try:
        user_manager = UserManager()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication database is not available",
        ) from exc

    user = user_manager.authenticate_user(form_data.username, form_data.password)

    if not user:
        logger.warning("login_failed", username=form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    access_token_expires = timedelta(minutes=settings.security.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id), "username": user.username, "role": user.role.value},
        expires_delta=access_token_expires,
    )

    logger.info("login_successful", user_id=str(user.id), username=user.username)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.security.access_token_expire_minutes * 60,
    }


@router.post("/users", response_model=UserResponse)
async def create_user(user_data: UserCreate, current_user: CurrentUser = Depends(require_admin)):
    """Create a new user (admin only)."""
    try:
        user_manager = UserManager()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication database is not available",
        ) from exc
    return user_manager.create_user(user_data)


@router.get("/users/me", response_model=dict)
async def read_users_me(current_user: CurrentUser = Depends(get_current_user)):
    """Get current user information."""
    return {
        "user_id": current_user.user_id,
        "username": current_user.username,
        "api_key_id": current_user.api_key_id,
        "role": current_user.role,
        "auth_method": current_user.auth_method,
    }


@router.post("/api-keys", response_model=APIKeyResponse)
async def create_api_key(
    api_key_data: APIKeyCreate, current_user: CurrentUser = Depends(require_admin)
):
    """Create a new API key (admin only)."""
    try:
        api_key_manager = APIKeyManager()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication database is not available",
        ) from exc
    return api_key_manager.create_api_key(api_key_data)


@router.get("/api-keys", response_model=list[APIKeyInfo])
async def list_api_keys(user_id: str = None, current_user: CurrentUser = Depends(require_user)):
    """List API keys. Non-admin users can only see their own keys."""
    try:
        api_key_manager = APIKeyManager()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication database is not available",
        ) from exc

    # Non-admin users can only see their own keys
    if current_user.role != "admin" and current_user.user_id:
        user_id = str(current_user.user_id)

    return api_key_manager.list_api_keys(user_id)


@router.delete("/api-keys/{api_key_id}")
async def revoke_api_key(api_key_id: UUID, current_user: CurrentUser = Depends(require_admin)):
    """Revoke an API key (admin only)."""
    try:
        api_key_manager = APIKeyManager()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication database is not available",
        ) from exc

    success = api_key_manager.revoke_api_key(api_key_id)

    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    return {"message": "API key revoked successfully"}


@router.post("/api-keys/{api_key_id}/rotate", response_model=APIKeyResponse)
async def rotate_api_key(api_key_id: UUID, current_user: CurrentUser = Depends(require_admin)):
    """Rotate an API key (admin only)."""
    try:
        api_key_manager = APIKeyManager()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication database is not available",
        ) from exc

    rotated_key = api_key_manager.rotate_api_key(api_key_id)

    if not rotated_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    return rotated_key


@router.get("/validate")
async def validate_token(current_user: CurrentUser = Depends(get_current_user)):
    """Validate current authentication token."""
    return {
        "valid": True,
        "user_id": current_user.user_id,
        "username": current_user.username,
        "role": current_user.role,
        "auth_method": current_user.auth_method,
    }
