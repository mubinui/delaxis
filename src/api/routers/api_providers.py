"""API provider management endpoints."""

import json
import os
import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
import httpx

from src.api.auth import CurrentUser, get_current_user, require_admin
from src.api.models import (
    APIProviderCreateRequest,
    APIProviderResponse,
    APIProviderUpdateRequest,
    ConfigHistoryEntry,
    ConfigHistoryResponse,
    ConnectionTestResponse,
    ProviderCapabilitiesResponse,
)
from src.audit_logging import get_logger
from src.config.api_provider_models import mask_api_key
from src.config.provider_registry import key_source, resolve_api_key
from src.config.provider_secrets import delete_secret, set_secret

# Versioned config service is optional and requires PostgreSQL
try:
    from src.config.versioned_service import VersionedConfigService
    VERSIONED_SERVICE_AVAILABLE = True
except ImportError:
    VersionedConfigService = None
    VERSIONED_SERVICE_AVAILABLE = False

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/api-providers", tags=["api-providers"])


def _get_api_providers_config_path() -> Path:
    """Get the path to the API providers configuration file."""
    return Path("configs") / "api_providers.json"


def _load_api_providers_config() -> dict:
    """Load API providers configuration from file."""
    config_path = _get_api_providers_config_path()
    
    if not config_path.exists():
        return {"version": "1.0", "providers": []}
    
    with open(config_path, "r") as f:
        return json.load(f)


def _save_api_providers_config(config: dict) -> None:
    """Save API providers configuration to file."""
    config_path = _get_api_providers_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def _get_versioned_service() -> Optional["VersionedConfigService"]:
    """Get versioned config service if database is configured and available."""
    if not VERSIONED_SERVICE_AVAILABLE:
        return None
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        try:
            service = VersionedConfigService(database_url=database_url)
            if service.is_available():
                return service
        except Exception:
            # Database not available, return None to use file-only mode
            return None
    return None


def _provider_to_response(
    provider: dict,
    version_info: Optional[tuple] = None
) -> APIProviderResponse:
    """Convert provider dict to response model with masked API key."""
    response_data = {
        "id": provider["id"],
        "name": provider.get("name", provider["id"]),
        "type": provider.get("type", "api"),
        "description": provider.get("description", ""),
        "base_url": provider.get("base_url") or provider.get("default_base_url"),
        "api_key_masked": mask_api_key(resolve_api_key(provider["id"])),
        "api_key_env": (provider.get("auth") or {}).get("env_var"),
        "key_source": key_source(provider["id"]),
        "litellm_prefix": provider.get("litellm_prefix"),
        "models": provider.get("models") or None,
        "enabled": provider.get("enabled", True),
        "config": provider.get("config", {}),
    }
    
    if version_info:
        response_data["version"] = version_info.version
        response_data["etag"] = version_info.etag
        response_data["last_updated"] = version_info.last_updated.isoformat()
    
    return APIProviderResponse(**response_data)


@router.get("", response_model=List[APIProviderResponse])
async def list_api_providers(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> List[APIProviderResponse]:
    """
    List all API providers.
    
    Args:
        request: FastAPI request object
        current_user: Current authenticated user
        
    Returns:
        List of API provider configurations
        
    Requirements: 3.1, 3.2, 3.3, 7.1
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Listing API providers",
        request_id=request_id,
    )
    
    try:
        config = _load_api_providers_config()
        
        responses = []
        for provider in config.get("providers", []):
            # Add models from config if present
            responses.append(_provider_to_response(provider))
        
        return responses
        
    except Exception as e:
        logger.error(
            "Failed to list API providers",
            request_id=request_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list API providers: {str(e)}",
        )


@router.post("", response_model=APIProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_api_provider(
    request: Request,
    body: APIProviderCreateRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> APIProviderResponse:
    """
    Create a new API provider.
    
    Args:
        request: FastAPI request object
        body: API provider creation request
        current_user: Current authenticated user (admin required)
        
    Returns:
        Created API provider
        
    Requirements: 3.1, 3.2, 7.1
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Creating API provider",
        request_id=request_id,
        provider_id=body.id,
    )
    
    try:
        # Load existing config
        config = _load_api_providers_config()
        
        # Check if provider already exists
        if any(p["id"] == body.id for p in config.get("providers", [])):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"API provider already exists: {body.id}",
            )
        
        # Create provider dict
        provider_dict = {
            "id": body.id,
            "name": body.name,
            "type": body.type,
            "description": body.description,
            "enabled": body.enabled,
            "config": body.config,
        }

        if body.base_url:
            provider_dict["base_url"] = body.base_url

        # Never write the key into configs/api_providers.json — that file is
        # tracked by git. It goes to the gitignored secret store instead.
        if body.api_key:
            set_secret(body.id, body.api_key)

        if body.litellm_prefix:
            provider_dict["litellm_prefix"] = body.litellm_prefix

        if body.models:
            provider_dict["models"] = body.models

        if body.api_key_env:
            provider_dict["auth"] = {
                "scheme": "bearer",
                "env_var": body.api_key_env,
                "required": not body.api_key,
            }
        
        # Add to config
        if "providers" not in config:
            config["providers"] = []
        config["providers"].append(provider_dict)
        
        # Save config
        _save_api_providers_config(config)
        
        # Create version snapshot if versioning is enabled
        versioned_service = _get_versioned_service()
        version_info = None
        if versioned_service:
            success, etag, _ = versioned_service.update_config(
                config_type="api_provider",
                config_id=body.id,
                updates=provider_dict,
                user_id=current_user.user_id,
                change_summary="Initial API provider creation",
            )
            if success:
                _, version_info = versioned_service.get_config(
                    "api_provider", body.id, current_user.user_id
                )
        
        logger.info(
            "Created API provider",
            request_id=request_id,
            provider_id=body.id,
        )
        
        return _provider_to_response(provider_dict, version_info)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to create API provider",
            request_id=request_id,
            provider_id=body.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create API provider: {str(e)}",
        )


@router.get("/{provider_id}", response_model=APIProviderResponse)
async def get_api_provider(
    request: Request,
    provider_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> APIProviderResponse:
    """
    Get API provider by ID.
    
    Args:
        request: FastAPI request object
        provider_id: Provider identifier
        current_user: Current authenticated user
        
    Returns:
        API provider configuration
        
    Requirements: 3.1, 3.2, 3.3, 7.1
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Getting API provider",
        request_id=request_id,
        provider_id=provider_id,
    )
    
    try:
        config = _load_api_providers_config()
        
        # Find provider
        provider = next(
            (p for p in config.get("providers", []) if p["id"] == provider_id),
            None
        )
        
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"API provider not found: {provider_id}",
            )
        
        # Get version info if available
        versioned_service = _get_versioned_service()
        version_info = None
        if versioned_service:
            _, version_info = versioned_service.get_config(
                "api_provider", provider_id, current_user.user_id
            )
        
        return _provider_to_response(provider, version_info)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get API provider",
            request_id=request_id,
            provider_id=provider_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get API provider: {str(e)}",
        )


@router.put("/{provider_id}", response_model=APIProviderResponse)
async def update_api_provider(
    request: Request,
    provider_id: str,
    body: APIProviderUpdateRequest,
    current_user: CurrentUser = Depends(require_admin),
    if_match: Optional[str] = Header(None),
) -> APIProviderResponse:
    """
    Update API provider with optimistic locking.
    
    Args:
        request: FastAPI request object
        provider_id: Provider identifier
        body: API provider update request
        current_user: Current authenticated user (admin required)
        if_match: Optional version token (ETag) for optimistic locking
        
    Returns:
        Updated API provider
        
    Requirements: 3.2, 3.3, 7.1, 7.2
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Updating API provider",
        request_id=request_id,
        provider_id=provider_id,
    )
    
    try:
        config = _load_api_providers_config()
        
        # Find provider
        provider_idx = next(
            (i for i, p in enumerate(config.get("providers", [])) if p["id"] == provider_id),
            None
        )
        
        if provider_idx is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"API provider not found: {provider_id}",
            )
        
        # Update provider
        provider = config["providers"][provider_idx]
        update_data = body.model_dump(exclude_unset=True)

        # Secrets never land in the tracked config file
        new_api_key = update_data.pop("api_key", None)
        if new_api_key:
            set_secret(provider_id, new_api_key)
        provider.pop("api_key", None)

        # api_key_env is persisted under auth.env_var, not as a raw key
        api_key_env = update_data.pop("api_key_env", None)
        if api_key_env:
            auth = provider.get("auth") or {"scheme": "bearer", "required": True}
            auth["env_var"] = api_key_env
            provider["auth"] = auth

        # Apply updates
        for key, value in update_data.items():
            if value is not None:
                provider[key] = value
        
        # Check for version conflict if versioning is enabled
        versioned_service = _get_versioned_service()
        version_info = None
        
        if versioned_service and if_match:
            success, result, conflict = versioned_service.update_config(
                config_type="api_provider",
                config_id=provider_id,
                updates=provider,
                version_token=if_match,
                user_id=current_user.user_id,
                change_summary="API provider update",
            )
            
            if not success and conflict:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=conflict,
                )
            
            if success:
                _, version_info = versioned_service.get_config(
                    "api_provider", provider_id, current_user.user_id
                )
        elif versioned_service:
            # No version token provided, just update
            versioned_service.update_config(
                config_type="api_provider",
                config_id=provider_id,
                updates=provider,
                user_id=current_user.user_id,
                change_summary="API provider update",
            )
            _, version_info = versioned_service.get_config(
                "api_provider", provider_id, current_user.user_id
            )
        
        # Save config
        _save_api_providers_config(config)
        
        logger.info(
            "Updated API provider",
            request_id=request_id,
            provider_id=provider_id,
        )
        
        return _provider_to_response(provider, version_info)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to update API provider",
            request_id=request_id,
            provider_id=provider_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update API provider: {str(e)}",
        )


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_provider(
    request: Request,
    provider_id: str,
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    """
    Delete API provider.
    
    Args:
        request: FastAPI request object
        provider_id: Provider identifier
        current_user: Current authenticated user (admin required)
        
    Requirements: 3.2, 3.5, 7.1
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Deleting API provider",
        request_id=request_id,
        provider_id=provider_id,
    )
    
    try:
        config = _load_api_providers_config()
        
        # Find and remove provider
        original_count = len(config.get("providers", []))
        config["providers"] = [p for p in config.get("providers", []) if p["id"] != provider_id]
        
        if len(config["providers"]) == original_count:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"API provider not found: {provider_id}",
            )
        
        # Save config
        _save_api_providers_config(config)
        
        logger.info(
            "Deleted API provider",
            request_id=request_id,
            provider_id=provider_id,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to delete API provider",
            request_id=request_id,
            provider_id=provider_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete API provider: {str(e)}",
        )


@router.get("/{provider_id}/models")
async def list_provider_models(
    request: Request,
    provider_id: str,
    live: bool = True,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """List a provider's models, querying its live catalogue when possible.

    Hardcoded model lists go stale as providers ship new releases, so the
    authoritative source is the provider's own OpenAI-compatible ``/models``
    endpoint. The configured list in api_providers.json is the offline
    fallback (and is merged in so curated entries never disappear).
    """
    from src.config.provider_registry import ProviderResolutionError, resolve_openai_endpoint

    config = _load_api_providers_config()
    provider = next((p for p in config.get("providers", []) if p["id"] == provider_id), None)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API provider not found: {provider_id}",
        )

    configured = [str(m.get("name")) for m in provider.get("models", []) if m.get("name")]
    result = {
        "provider_id": provider_id,
        "models": [{"name": name, "source": "configured"} for name in configured],
        "source": "configured",
        "live": False,
        "warning": None,
    }

    if not live:
        return result

    try:
        base_url, api_key, auth_required = resolve_openai_endpoint(provider_id)
    except ProviderResolutionError as exc:
        result["warning"] = str(exc)
        return result

    if not base_url:
        result["warning"] = "Provider has no base_url to query."
        return result
    if auth_required and not api_key:
        result["warning"] = "No API key configured, showing the saved model list."
        return result

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    endpoint = f"{base_url.rstrip('/')}/models"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.info("provider_models_live_fetch_failed", provider_id=provider_id, error=str(exc))
        result["warning"] = f"Could not reach {endpoint}: {exc}"
        return result

    entries = payload.get("data") if isinstance(payload, dict) else payload
    discovered: list[str] = []
    if isinstance(entries, list):
        for entry in entries:
            name = entry.get("id") or entry.get("name") if isinstance(entry, dict) else entry
            if isinstance(name, str) and name:
                discovered.append(name)

    if not discovered:
        result["warning"] = f"{endpoint} returned no models."
        return result

    # Configured entries first so curated defaults stay at the top of pickers
    merged = [{"name": name, "source": "configured"} for name in configured]
    seen = set(configured)
    for name in sorted(discovered):
        if name not in seen:
            merged.append({"name": name, "source": "live"})
            seen.add(name)

    result.update({"models": merged, "source": "live", "live": True, "count": len(discovered)})
    return result


@router.get("/{provider_id}/capabilities", response_model=ProviderCapabilitiesResponse)
async def get_provider_capabilities(
    request: Request,
    provider_id: str,
    model: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
) -> ProviderCapabilitiesResponse:
    """Report which settings this provider's route honours.

    CrewAI's provider classes silently ignore unknown parameters, so the studio
    hides fields a route would discard rather than showing controls that do
    nothing. The effective route matters, not the declared one: a native SDK
    that is not installed falls back to the OpenAI-compatible route, which has
    a different parameter set and output-token spelling.
    """
    from src.config.provider_capabilities import AGENT_PARAMS, route_capabilities
    from src.config.provider_registry import (
        ProviderResolutionError,
        compat_fallback,
        resolve_llm,
    )

    try:
        resolved = resolve_llm(provider_id, model or "probe-model")
    except ProviderResolutionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    effective = resolved
    if resolved.native:
        # Mirror the runtime: if the native SDK is missing we will fall back.
        try:
            from crewai import LLM  # noqa: F401

            import importlib

            importlib.import_module(
                f"crewai.llms.providers.{resolved.crewai_provider}.completion"
            )
        except Exception:
            effective = compat_fallback(resolved) or resolved

    caps = route_capabilities(effective.crewai_provider)
    return ProviderCapabilitiesResponse(
        provider_id=provider_id,
        crewai_provider=resolved.crewai_provider,
        effective_provider=effective.crewai_provider,
        native=effective.native,
        output_token_param=caps.output_token_param,
        supported_llm_params=list(caps.supported_llm_params),
        agent_params=list(AGENT_PARAMS),
        key_present=bool(resolve_api_key(provider_id)),
        key_source=key_source(provider_id),
        api_key_env=(_find_provider_dict(provider_id) or {}).get("auth", {}).get("env_var"),
    )


@router.delete("/{provider_id}/key", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_key(
    request: Request,
    provider_id: str,
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    """Remove a stored key so the provider falls back to its env var."""
    delete_secret(provider_id)


def _find_provider_dict(provider_id: str) -> dict | None:
    config = _load_api_providers_config()
    return next((p for p in config.get("providers", []) if p.get("id") == provider_id), None)


@router.post("/{provider_id}/test", response_model=ConnectionTestResponse)
async def test_api_provider_connection(
    request: Request,
    provider_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> ConnectionTestResponse:
    """
    Test API provider connection.
    
    Args:
        request: FastAPI request object
        provider_id: Provider identifier
        current_user: Current authenticated user
        
    Returns:
        Connection test result
        
    Requirements: 3.4
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Testing API provider connection",
        request_id=request_id,
        provider_id=provider_id,
    )
    
    try:
        config = _load_api_providers_config()
        
        # Find provider
        provider = next(
            (p for p in config.get("providers", []) if p["id"] == provider_id),
            None
        )
        
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"API provider not found: {provider_id}",
            )
        
        provider_type = provider.get("type", "api")
        
        if provider_type == "llm":
            base_url = provider.get("base_url") or provider.get("default_base_url")
            if provider.get("base_url_env"):
                base_url = os.getenv(provider["base_url_env"], base_url)
            if not base_url:
                return ConnectionTestResponse(
                    success=False,
                    live=False,
                    message="LLM provider missing base_url",
                    details={"provider_id": provider_id, "type": provider_type}
                )
            
            api_key = resolve_api_key(provider_id)
            
            if not api_key:
                return ConnectionTestResponse(
                    success=False,
                    live=False,
                    message="LLM provider missing API key",
                    checked_endpoint=f"{base_url.rstrip('/')}/models",
                    details={"provider_id": provider_id, "type": provider_type}
                )

            models = provider.get("models", [])
            model_id = next((model.get("name") for model in models if model.get("default")), None)
            model_id = model_id or (models[0].get("name") if models else "openai/gpt-oss-20b")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            started = time.perf_counter()
            models_endpoint = f"{base_url.rstrip('/')}/models"
            chat_endpoint = f"{base_url.rstrip('/')}/chat/completions"
            async with httpx.AsyncClient(timeout=20) as client:
                models_response = await client.get(models_endpoint, headers=headers)
                checked_endpoint = models_endpoint
                if models_response.status_code >= 400:
                    payload = {
                        "model": model_id,
                        "messages": [{"role": "user", "content": "Reply with ok."}],
                        "max_tokens": 8,
                        "stream": False,
                    }
                    chat_response = await client.post(chat_endpoint, headers=headers, json=payload)
                    checked_endpoint = chat_endpoint
                    chat_response.raise_for_status()
                else:
                    models_response.raise_for_status()
            latency_ms = round((time.perf_counter() - started) * 1000)
            capabilities = {cap for model in models for cap in model.get("capabilities", [])}
            
            return ConnectionTestResponse(
                success=True,
                live=True,
                message="LLM provider live test succeeded",
                latency_ms=latency_ms,
                checked_endpoint=checked_endpoint,
                model_id=model_id,
                supports_streaming=True,
                supports_tools=bool({"function_calling", "tools"} & capabilities),
                details={
                    "provider_id": provider_id,
                    "type": provider_type,
                    "base_url": base_url,
                    "has_api_key": True
                }
            )
        
        elif provider_type == "tool":
            if not provider.get("entrypoint") and not provider.get("library"):
                return ConnectionTestResponse(
                    success=False,
                    live=False,
                    message="Tool provider missing entrypoint or library",
                    details={"provider_id": provider_id, "type": provider_type}
                )
            
            return ConnectionTestResponse(
                success=True,
                live=False,
                message="Tool provider configuration is valid",
                details={
                    "provider_id": provider_id,
                    "type": provider_type,
                    "entrypoint": provider.get("entrypoint"),
                    "library": provider.get("library")
                }
            )
        
        else:  # api type
            if not provider.get("base_url"):
                return ConnectionTestResponse(
                    success=False,
                    live=False,
                    message="API provider missing base_url",
                    details={"provider_id": provider_id, "type": provider_type}
                )
            
            return ConnectionTestResponse(
                success=True,
                live=False,
                message="API provider configuration is valid",
                details={
                    "provider_id": provider_id,
                    "type": provider_type,
                    "base_url": provider.get("base_url")
                }
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to test API provider connection",
            request_id=request_id,
            provider_id=provider_id,
            error=str(e),
            exc_info=True,
        )
        return ConnectionTestResponse(
            success=False,
            live=False,
            message=f"Connection test failed: {str(e)}",
            details={"provider_id": provider_id, "error": str(e)[:500]}
        )


@router.get("/{provider_id}/history", response_model=ConfigHistoryResponse)
async def get_api_provider_history(
    request: Request,
    provider_id: str,
    limit: int = 10,
    current_user: CurrentUser = Depends(get_current_user),
) -> ConfigHistoryResponse:
    """
    Get API provider version history.
    
    Args:
        request: FastAPI request object
        provider_id: Provider identifier
        limit: Maximum number of history entries to return
        current_user: Current authenticated user
        
    Returns:
        Configuration history with versions
        
    Requirements: 9.2
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Getting API provider history",
        request_id=request_id,
        provider_id=provider_id,
    )
    
    try:
        versioned_service = _get_versioned_service()
        
        if not versioned_service:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Version history not available (database not configured)",
            )
        
        history = versioned_service.get_config_history(
            config_type="api_provider",
            config_id=provider_id,
            limit=limit,
            user_id=current_user.user_id,
        )
        
        if not history:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No history found for API provider: {provider_id}",
            )
        
        history_entries = [
            ConfigHistoryEntry(**entry) for entry in history
        ]
        
        return ConfigHistoryResponse(
            config_type="api_provider",
            config_id=provider_id,
            history=history_entries,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get API provider history",
            request_id=request_id,
            provider_id=provider_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get API provider history: {str(e)}",
        )
