"""Generic API tool executor for imported Swagger/OpenAPI tools.

This module provides a generic executor for API tools that were imported
from Swagger/OpenAPI specifications. It handles HTTP requests with proper
authentication and user context forwarding.

Authentication Flow:
1. Frontend sends user JWT → Backend extracts username and roles
2. Backend gets admin token using client_credentials grant
3. Backend calls target API with:
   - Authorization: Bearer <admin_token>
   - x-client-username: <extracted_username>
   - x-client-ref: <extracted_roles>

This is AUTOMATIC - no configuration needed when importing APIs via Swagger.
"""

import base64
import json
import os
from typing import Any, Callable, Optional, Annotated

import httpx
import structlog

from src.config.settings import get_settings
from src.tools.context_utils import get_user_context_info

logger = structlog.get_logger(__name__)


async def _get_admin_token() -> Optional[str]:
    """
    Get admin token using client_credentials grant from Keycloak.
    
    Used for service-to-service
    authentication while passing user context via x-client headers.
    
    Returns:
        Admin access token string, or None if acquisition fails
    """
    settings = get_settings()
    
    if not settings.keycloak.enabled:
        logger.warning("keycloak_not_enabled_for_admin_token")
        return None
    
    if not settings.keycloak.admin_client_secret:
        logger.warning("admin_client_secret_not_configured")
        return None
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                settings.keycloak.token_endpoint,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.keycloak.admin_client_id,
                    "client_secret": settings.keycloak.admin_client_secret,
                },
            )
            response.raise_for_status()
            token_response = response.json()
            logger.info("admin_token_acquired_for_api_tool", 
                       client_id=settings.keycloak.admin_client_id)
            return token_response["access_token"]
    except Exception as e:
        logger.error("failed_to_acquire_admin_token", error=str(e))
        return None


def _get_python_type(schema_type: str) -> type:
    """Map OpenAPI schema types to Python types."""
    type_mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    return type_mapping.get(schema_type, str)


def create_api_tool_function(
    tool_id: str,
    settings: dict[str, Any],
    description: str = "",
) -> Callable[..., Any]:
    """
    Create a bound API tool function for a specific tool configuration.
    
    This factory creates a closure that binds the tool_id and settings,
    returning a function that CrewAI can call directly with just the
    user-provided arguments.
    
    CrewAI requires functions to have explicit parameter annotations,
    so we dynamically create a function signature based on the Swagger
    parameter metadata.
    
    Args:
        tool_id: The ID of the tool
        settings: Tool settings containing API configuration
        description: Tool description for docstring
        
    Returns:
        A callable async function that can be registered with CrewAI
    """
    # Parameter metadata comes from a Swagger import when there was one, and
    # otherwise from a `parameters` list written by hand in settings. Without
    # the second source, a hand-authored API tool documented its parameters in
    # its description but fell through to the zero-argument fallback below —
    # so an agent calling it exactly as described got a TypeError.
    swagger_metadata = settings.get("_swagger_metadata", {})
    parameters = swagger_metadata.get("parameters") or settings.get("parameters") or []
    
    # Build parameter info for function signature and docstring
    param_docs = []
    param_info = []  # List of (name, type, required, description, default)
    
    for param in parameters:
        param_name = param.get("name", "")
        param_in = param.get("in", "")
        required = param.get("required", False)
        param_desc = param.get("description", "")
        schema = param.get("schema", {})
        param_type = schema.get("type", "string")
        default = schema.get("default")
        
        # Skip header parameters as they're handled automatically
        if param_in == "header":
            continue
        
        if not param_name:
            continue
            
        req_str = "required" if required else "optional"
        param_docs.append(f"    {param_name} ({param_type}, {req_str}): {param_desc}")
        
        python_type = _get_python_type(param_type)
        param_info.append((param_name, python_type, required, param_desc, default))
    
    # Build the full docstring
    full_description = description
    if param_docs:
        full_description += "\n\nParameters:\n" + "\n".join(param_docs)
    
    # If we have parameter info, create a properly typed function
    if param_info:
        # Build parameters for the dynamic function
        # Required params first, then optional params with defaults
        required_params = [(n, t, d) for n, t, req, d, default in param_info if req]
        optional_params = [(n, t, d, default) for n, t, req, d, default in param_info if not req]
        
        # Create the function dynamically using exec
        # This allows us to create proper type annotations that CrewAI can inspect
        param_strs = []
        annotations = {"return": dict[str, Any]}
        
        for name, ptype, desc in required_params:
            # Use Annotated for description
            param_strs.append(f"{name}: {ptype.__name__}")
            annotations[name] = Annotated[ptype, desc] if desc else ptype
            
        for name, ptype, desc, default in optional_params:
            default_val = repr(default) if default is not None else repr("")
            if ptype == str:
                default_val = repr(default) if default is not None else "''"
            elif ptype == int:
                default_val = str(default) if default is not None else "0"
            elif ptype == float:
                default_val = str(default) if default is not None else "0.0"
            elif ptype == bool:
                default_val = str(default) if default is not None else "False"
            elif ptype == list:
                default_val = "None"
            elif ptype == dict:
                default_val = "None"
            else:
                default_val = "None"
            param_strs.append(f"{name}: {ptype.__name__} = {default_val}")
            annotations[name] = Annotated[ptype, desc] if desc else ptype
        
        params_str = ", ".join(param_strs)
        
        # Create a wrapper that calls execute_api_tool with captured tool_id and settings
        async def _execute_wrapper(**kw):
            return await execute_api_tool(tool_id, settings, **kw)
        
        # Build the function code
        func_code = f'''
async def {tool_id}({params_str}) -> dict:
    """{{docstring}}"""
    return await _execute_wrapper({", ".join(f"{name}={name}" for name, _, _, _ in [(n, t, d, None) for n, t, d in required_params] + [(n, t, d, df) for n, t, d, df in optional_params])})
'''
        
        # Execute to create the function
        local_vars = {"_execute_wrapper": _execute_wrapper}
        try:
            exec(func_code.replace("{docstring}", full_description.replace('"', "'")), local_vars, local_vars)
            api_tool_func = local_vars[tool_id]
            api_tool_func.__annotations__.update(annotations)
            return api_tool_func
        except Exception as e:
            logger.warning(
                "failed_to_create_typed_function",
                tool_id=tool_id,
                error=str(e),
                fallback="using_simple_wrapper",
            )
    
    # Fallback for tools with no declared parameters. It still accepts and
    # forwards keyword arguments: execute_api_tool maps them onto the request,
    # so an undeclared-but-documented parameter degrades to "untyped" rather
    # than "uncallable".
    async def api_tool_func(**kwargs: Any) -> dict[str, Any]:
        """Execute the API tool."""
        return await execute_api_tool(tool_id, settings, **kwargs)
    
    # Set function metadata
    api_tool_func.__name__ = tool_id
    api_tool_func.__doc__ = full_description
    
    return api_tool_func


async def execute_api_tool(
    tool_id: str,
    settings: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Execute an API tool with the given settings.
    
    This is the generic executor for API tools imported from Swagger specs.
    It reads the tool configuration from settings and makes the appropriate
    HTTP request.
    
    Args:
        tool_id: The ID of the tool being executed
        settings: Tool settings containing API configuration:
            - api_url: Full URL for the API endpoint
            - http_method: HTTP method (GET, POST, etc.)
            - auth_type: Authentication type (none, bearer, api_key, basic)
            - auth_env_var: Environment variable containing auth credentials
            - auth_header: Header name for API key auth
            - timeout: Request timeout in seconds
            - forward_user_context: Whether to forward user context headers
            - headers: Additional headers to include
            - body_template: Request body template
            - response_path: JSON path to extract from response
        **kwargs: Additional arguments passed to the tool (request parameters)
        
    Returns:
        dict with:
            - status_code: HTTP response status
            - success: Boolean indicating success (2xx status)
            - data: Response body (parsed JSON or text)
            - error: Error message if request failed
    """
    # Extract settings
    api_url = settings.get("api_url")
    if not api_url:
        return {
            "status_code": 400,
            "success": False,
            "data": None,
            "error": f"Tool {tool_id}: Missing api_url in settings",
        }
    
    http_method = settings.get("http_method", "GET").upper()
    timeout = settings.get("timeout", 30)
    extra_headers = settings.get("headers", {})
    body_template = settings.get("body_template")
    response_path = settings.get("response_path")
    
    # Build URL with path parameters
    url = api_url
    for key, value in kwargs.items():
        # Replace path parameters like {id} with actual values
        url = url.replace(f"{{{key}}}", str(value))
    
    # Build headers
    request_headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
    }
    request_headers.update(extra_headers)
    
    # =========================================================================
    # AUTHENTICATION
    # =========================================================================
    # Modes (settings["auth_type"]):
    #   none    - no Authorization header (public APIs)
    #   bearer  - Bearer token from env var settings["auth_env_var"]
    #   api_key - key from env var settings["auth_env_var"] sent in
    #             header settings["auth_header"] (default "X-API-Key")
    #   basic   - "user:pass" from env var settings["auth_env_var"]
    #   keycloak- service-account admin token from the configured Keycloak
    # Additionally, "/self"-style endpoints (or settings["use_user_token"])
    # forward the calling user's own JWT instead.
    # =========================================================================

    # Get user context from the incoming request (username/roles/raw_token)
    user_info = get_user_context_info()

    admin_token = None
    auth_type = settings.get("auth_type", "none")
    is_self_endpoint = "/self" in url.lower() or "/myself" in url.lower()

    if is_self_endpoint or settings.get("use_user_token", False):
        # Use the calling user's own token to identify them to the upstream API
        raw_token = user_info.get("raw_token") if user_info else None
        if raw_token:
            if not raw_token.startswith("Bearer "):
                request_headers["Authorization"] = f"Bearer {raw_token}"
            else:
                request_headers["Authorization"] = raw_token
            logger.info("using_user_token_for_self_endpoint", tool_id=tool_id, has_token=True)
        else:
            logger.warning("no_user_token_for_self_endpoint", tool_id=tool_id)
    elif auth_type in ("bearer", "api_key", "basic"):
        env_var = settings.get("auth_env_var")
        credential = os.environ.get(env_var, "") if env_var else ""
        if not credential:
            logger.warning("api_tool_missing_credential", tool_id=tool_id, auth_type=auth_type, env_var=env_var)
        elif auth_type == "bearer":
            request_headers["Authorization"] = f"Bearer {credential}"
        elif auth_type == "api_key":
            request_headers[settings.get("auth_header", "X-API-Key")] = credential
        else:  # basic
            encoded = base64.b64encode(credential.encode()).decode()
            request_headers["Authorization"] = f"Basic {encoded}"
    elif auth_type == "keycloak":
        # Use the Keycloak service-account admin token with x-client headers
        admin_token = await _get_admin_token()
        if admin_token:
            request_headers["Authorization"] = f"Bearer {admin_token}"
        else:
            logger.warning("proceeding_without_admin_token", tool_id=tool_id)
    # auth_type "none": no Authorization header
    
    username = user_info.get("username") if user_info else None
    roles = user_info.get("roles") if user_info else None
    
    logger.info(
        "api_tool_user_context",
        tool_id=tool_id,
        username=username,
        has_roles=bool(roles),
        roles_count=len(roles) if roles else 0,
    )
    
    # Add user context headers when forwarding user identity
    if username:
        request_headers["x-client-username"] = username
    if roles:
        # x-client-ref is a comma-separated string of role names
        if isinstance(roles, list):
            request_headers["x-client-ref"] = ",".join(roles)
        else:
            request_headers["x-client-ref"] = str(roles)
    
    # Build request body
    payload = None
    if http_method in ("POST", "PUT", "PATCH"):
        if body_template:
            # Use body template with variable substitution
            try:
                body_str = body_template
                for key, value in kwargs.items():
                    body_str = body_str.replace(f"{{{key}}}", json.dumps(value) if not isinstance(value, str) else value)
                payload = json.loads(body_str)
            except json.JSONDecodeError:
                payload = kwargs
        else:
            # Use kwargs as body directly
            payload = kwargs if kwargs else None
    
    # Build query parameters for GET requests
    params = None
    if http_method == "GET" and kwargs:
        params = {k: v for k, v in kwargs.items() if f"{{{k}}}" not in api_url}
    
    # Log the API call
    logger.info(
        "calling_api_tool",
        tool_id=tool_id,
        url=url,
        method=http_method,
        username=username,
        has_roles=bool(roles),
        has_admin_token=bool(admin_token),
        params=params,
    )
    
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=settings.get("verify_ssl", True)) as client:
            response = await client.request(
                method=http_method,
                url=url,
                json=payload,
                params=params,
                headers=request_headers,
            )
            
            # Try to parse response as JSON
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                response_data = response.text
            
            # Extract data from response path if specified
            if response_path and isinstance(response_data, dict):
                try:
                    for key in response_path.split("."):
                        response_data = response_data.get(key, response_data)
                except (AttributeError, TypeError):
                    pass  # Keep original response if path extraction fails
            
            success = 200 <= response.status_code < 300
            
            logger.info(
                "api_tool_response",
                tool_id=tool_id,
                status_code=response.status_code,
                success=success,
            )
            
            return {
                "status_code": response.status_code,
                "success": success,
                "data": response_data,
                "error": None if success else response_data,
            }
            
    except httpx.TimeoutException:
        logger.error("api_tool_timeout", tool_id=tool_id, url=url)
        return {
            "status_code": 504,
            "success": False,
            "data": None,
            "error": f"Request timed out after {timeout} seconds",
        }
    except httpx.HTTPError as e:
        logger.error("api_tool_http_error", tool_id=tool_id, url=url, error=str(e))
        return {
            "status_code": 502,
            "success": False,
            "data": None,
            "error": f"HTTP request failed: {str(e)}",
        }
    except Exception as e:
        logger.error("api_tool_error", tool_id=tool_id, url=url, error=str(e), exc_info=True)
        return {
            "status_code": 500,
            "success": False,
            "data": None,
            "error": f"Unexpected error: {str(e)}",
        }
