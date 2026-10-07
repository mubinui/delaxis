"""Swagger/OpenAPI parser for importing API tools.

Supports both OpenAPI 2.0 (Swagger) and OpenAPI 3.0+ specifications.
"""

import re
from typing import Any
from urllib.parse import urljoin

import httpx
import yaml
from pydantic import BaseModel, Field


class ParsedEndpoint(BaseModel):
    """Represents a parsed API endpoint from Swagger/OpenAPI spec."""

    operation_id: str = Field(description="Unique operation identifier")
    path: str = Field(description="API path e.g., /users/{id}")
    method: str = Field(description="HTTP method (GET, POST, etc.)")
    summary: str = Field(default="", description="Operation summary")
    description: str = Field(default="", description="Operation description")
    parameters: list[dict[str, Any]] = Field(default_factory=list, description="Request parameters")
    request_body: dict[str, Any] | None = Field(default=None, description="Request body schema")
    responses: dict[str, Any] = Field(default_factory=dict, description="Response schemas")
    tags: list[str] = Field(default_factory=list, description="Operation tags")
    security: list[dict[str, list[str]]] = Field(
        default_factory=list, description="Security requirements"
    )


class SwaggerParseResult(BaseModel):
    """Result of parsing a Swagger/OpenAPI specification."""

    title: str = Field(description="API title")
    version: str = Field(description="API version")
    description: str = Field(default="", description="API description")
    base_url: str = Field(description="Base URL for the API")
    endpoints: list[ParsedEndpoint] = Field(default_factory=list, description="Parsed endpoints")
    security_definitions: dict[str, Any] = Field(
        default_factory=dict, description="Security schemes"
    )
    openapi_version: str = Field(description="OpenAPI spec version (2.0 or 3.x)")
    errors: list[str] = Field(default_factory=list, description="Parsing errors/warnings")


class ToolFromEndpoint(BaseModel):
    """Tool configuration generated from a parsed endpoint."""

    id: str = Field(description="Tool ID (generated from operation_id)")
    name: str = Field(description="Tool name")
    description: str = Field(description="Tool description")
    entrypoint: str = Field(description="Entrypoint for API tool executor")
    enabled: bool = Field(default=True)
    settings: dict[str, Any] = Field(
        default_factory=dict, description="Tool settings including API config"
    )


def to_snake_case(text: str) -> str:
    """
    Convert any text to snake_case.

    Examples:
        - "Total active framework agreement" -> "total_active_framework_agreement"
        - "GetUserById" -> "get_user_by_id"
        - "Find order by order no" -> "find_order_by_order_no"
    """
    if not text:
        return ""

    # First, handle camelCase/PascalCase by inserting spaces before uppercase letters
    text = re.sub(r"(?<!^)(?=[A-Z])", " ", text)

    # Convert to lowercase and replace non-alphanumeric with underscores
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)

    # Remove consecutive underscores
    text = re.sub(r"_+", "_", text)

    # Remove leading/trailing underscores
    text = text.strip("_")

    return text


def sanitize_tool_id(operation_id: str, path: str, method: str) -> str:
    """
    Generate a valid tool ID from operation_id, path, and method.

    Tool IDs must match pattern: ^[a-z0-9_]+$

    Converts camelCase/PascalCase to snake_case for better readability.
    Examples:
        - getOrderInfo -> get_order_info
        - GetUserById -> get_user_by_id
        - POST /api/users -> post_api_users
    """
    if operation_id:
        # Use the snake_case converter
        tool_id = to_snake_case(operation_id)
    else:
        # Generate from path and method
        # Remove path parameters and special chars
        clean_path = re.sub(r"\{[^}]+\}", "", path)
        clean_path = re.sub(r"[^a-zA-Z0-9]", "_", clean_path)
        tool_id = f"{method.lower()}_{clean_path}"

    # Replace non-allowed characters with underscores
    tool_id = re.sub(r"[^a-z0-9_]", "_", tool_id)
    # Remove consecutive underscores
    tool_id = re.sub(r"_+", "_", tool_id)
    # Remove leading/trailing underscores
    tool_id = tool_id.strip("_")

    return tool_id or f"api_{method.lower()}"


def generate_tool_description(endpoint: ParsedEndpoint) -> str:
    """Generate a comprehensive tool description from endpoint metadata."""
    parts = []

    # Use description or summary
    if endpoint.description:
        parts.append(endpoint.description)
    elif endpoint.summary:
        parts.append(endpoint.summary)
    else:
        parts.append(f"{endpoint.method.upper()} {endpoint.path}")

    # Add parameter info
    if endpoint.parameters:
        param_descriptions = []
        for param in endpoint.parameters:
            param_name = param.get("name", "unknown")
            param_in = param.get("in", "query")
            required = param.get("required", False)
            param_desc = param.get("description", "")

            req_str = " (required)" if required else " (optional)"
            desc_str = f": {param_desc}" if param_desc else ""
            param_descriptions.append(f"  - {param_name} [{param_in}]{req_str}{desc_str}")

        if param_descriptions:
            parts.append("\n\nParameters:\n" + "\n".join(param_descriptions))

    return "".join(parts)


class SwaggerParser:
    """Parser for Swagger/OpenAPI specifications."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def fetch_spec(self, url: str) -> dict[str, Any]:
        """
        Fetch and parse Swagger/OpenAPI spec from URL.

        Args:
            url: URL to the Swagger/OpenAPI specification

        Returns:
            Parsed specification as dictionary

        Raises:
            ValueError: If spec cannot be fetched or parsed
        """
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ValueError(
                    f"Failed to fetch spec from {url}: HTTP {e.response.status_code}"
                ) from e
            except httpx.RequestError as e:
                raise ValueError(f"Failed to fetch spec from {url}: {str(e)}") from e

        content = response.text.strip()

        # Check for HTML content (common mistake: providing UI URL instead of spec URL)
        if content.lower().startswith("<!doctype html") or content.lower().startswith("<html"):
            raise ValueError(
                f"The URL returned HTML content instead of a JSON/YAML specification. "
                f"You may have provided the Swagger UI URL ({url}) instead of the actual specification URL. "
                f"Look for a link like '/v3/api-docs', 'swagger.json', or 'openapi.yaml' on the page."
            )

        parsed_spec = None

        # Try parsing as JSON first
        try:
            import json

            parsed_spec = json.loads(content)
        except json.JSONDecodeError:
            # If JSON fails, try YAML
            try:
                parsed_spec = yaml.safe_load(content)
            except yaml.YAMLError as e:
                raise ValueError(f"Failed to parse spec: not valid JSON or YAML. Error: {e}") from e

        if not isinstance(parsed_spec, dict):
            raise ValueError(
                f"Parsed specification is not a dictionary (got {type(parsed_spec).__name__}). Please ensure the URL points to a valid Swagger/OpenAPI object."
            )

        return parsed_spec

    def detect_openapi_version(self, spec: dict[str, Any]) -> str:
        """Detect OpenAPI version from spec."""
        if "openapi" in spec:
            return spec["openapi"]
        elif "swagger" in spec:
            return spec["swagger"]
        else:
            raise ValueError("Unable to detect OpenAPI/Swagger version")

    def get_base_url(self, spec: dict[str, Any], spec_url: str) -> str:
        """
        Extract base URL from spec.

        Args:
            spec: Parsed specification
            spec_url: URL where spec was fetched from (for relative resolution)

        Returns:
            Base URL for the API
        """
        version = self.detect_openapi_version(spec)

        if version.startswith("3"):
            # OpenAPI 3.x
            servers = spec.get("servers", [])
            if servers and "url" in servers[0]:
                server_url = servers[0]["url"]
                # Handle relative URLs
                if server_url.startswith("/"):
                    from urllib.parse import urlparse

                    parsed = urlparse(spec_url)
                    return f"{parsed.scheme}://{parsed.netloc}{server_url}"
                return server_url
        else:
            # Swagger 2.0
            host = spec.get("host", "")
            base_path = spec.get("basePath", "")
            schemes = spec.get("schemes", ["https"])

            if host:
                scheme = schemes[0] if schemes else "https"
                return f"{scheme}://{host}{base_path}"

        # Fallback: derive from spec URL
        from urllib.parse import urlparse

        parsed = urlparse(spec_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def parse_security_definitions(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Extract security definitions from spec."""
        version = self.detect_openapi_version(spec)

        if version.startswith("3"):
            # OpenAPI 3.x
            components = spec.get("components", {})
            return components.get("securitySchemes", {})
        else:
            # Swagger 2.0
            return spec.get("securityDefinitions", {})

    def parse_parameters(
        self, spec: dict[str, Any], operation: dict[str, Any], path_params: list[dict]
    ) -> list[dict[str, Any]]:
        """Parse operation parameters including path-level parameters."""
        params = []

        # Add path-level parameters
        for param in path_params:
            if "$ref" in param:
                # Resolve reference
                param = self.resolve_ref(spec, param["$ref"])
            params.append(param)

        # Add operation-level parameters
        for param in operation.get("parameters", []):
            if "$ref" in param:
                param = self.resolve_ref(spec, param["$ref"])
            # Override path-level params with same name
            existing_idx = next(
                (i for i, p in enumerate(params) if p.get("name") == param.get("name")), None
            )
            if existing_idx is not None:
                params[existing_idx] = param
            else:
                params.append(param)

        return params

    def parse_request_body(
        self, spec: dict[str, Any], operation: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Parse request body from operation (OpenAPI 3.x)."""
        request_body = operation.get("requestBody")

        if not request_body:
            return None

        if "$ref" in request_body:
            request_body = self.resolve_ref(spec, request_body["$ref"])

        return request_body

    def resolve_ref(self, spec: dict[str, Any], ref: str) -> dict[str, Any]:
        """Resolve a $ref pointer to the actual schema."""
        if not ref.startswith("#/"):
            return {}  # External refs not supported

        parts = ref[2:].split("/")
        current = spec

        for part in parts:
            # Handle URL-encoded characters
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return {}

        return current if isinstance(current, dict) else {}

    def parse_endpoints(self, spec: dict[str, Any]) -> list[ParsedEndpoint]:
        """Parse all endpoints from the spec."""
        endpoints = []
        errors = []

        paths = spec.get("paths", {})

        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue

            # Get path-level parameters
            path_params = path_item.get("parameters", [])

            # HTTP methods
            methods = ["get", "post", "put", "delete", "patch", "options", "head"]

            for method in methods:
                if method not in path_item:
                    continue

                operation = path_item[method]
                if not isinstance(operation, dict):
                    continue

                try:
                    operation_id = operation.get("operationId", "")

                    endpoint = ParsedEndpoint(
                        operation_id=operation_id or f"{method}_{path}",
                        path=path,
                        method=method.upper(),
                        summary=operation.get("summary", ""),
                        description=operation.get("description", ""),
                        parameters=self.parse_parameters(spec, operation, path_params),
                        request_body=self.parse_request_body(spec, operation),
                        responses=operation.get("responses", {}),
                        tags=operation.get("tags", []),
                        security=operation.get("security", []),
                    )
                    endpoints.append(endpoint)
                except Exception as e:
                    errors.append(f"Error parsing {method.upper()} {path}: {str(e)}")

        return endpoints

    async def parse(self, url: str) -> SwaggerParseResult:
        """
        Parse a Swagger/OpenAPI specification from URL.

        Args:
            url: URL to the Swagger/OpenAPI specification

        Returns:
            SwaggerParseResult with parsed endpoints and metadata
        """
        spec = await self.fetch_spec(url)

        version = self.detect_openapi_version(spec)
        info = spec.get("info", {})

        endpoints = self.parse_endpoints(spec)
        base_url = self.get_base_url(spec, url)
        security_defs = self.parse_security_definitions(spec)

        return SwaggerParseResult(
            title=info.get("title", "Unknown API"),
            version=info.get("version", "1.0"),
            description=info.get("description", ""),
            base_url=base_url,
            endpoints=endpoints,
            security_definitions=security_defs,
            openapi_version=version,
            errors=[],
        )

    def generate_tool_configs(
        self,
        parse_result: SwaggerParseResult,
        existing_tool_ids: set[str],
        endpoint_filter: list[str] | None = None,
        default_auth_type: str = "none",
        default_auth_env_var: str | None = None,
        forward_user_context: bool = False,
        timeout: int = 30,
    ) -> tuple[list[ToolFromEndpoint], list[str]]:
        """
        Generate tool configurations from parsed endpoints.

        Args:
            parse_result: Parsed Swagger/OpenAPI result
            existing_tool_ids: Set of existing tool IDs to check for duplicates
            endpoint_filter: Optional list of operation_ids to include (None = all)
            default_auth_type: Default authentication type
            default_auth_env_var: Default environment variable for auth
            forward_user_context: Whether to forward user context headers
            timeout: Request timeout in seconds

        Returns:
            Tuple of (list of tool configs, list of skipped operation_ids due to duplicates)
        """
        tools = []
        skipped = []

        for endpoint in parse_result.endpoints:
            # Apply filter if provided
            if endpoint_filter is not None:
                if endpoint.operation_id not in endpoint_filter:
                    continue

            tool_id = sanitize_tool_id(endpoint.operation_id, endpoint.path, endpoint.method)

            # Check for duplicates
            if tool_id in existing_tool_ids:
                skipped.append(f"{tool_id} (from {endpoint.method} {endpoint.path})")
                continue

            # Build full URL
            full_url = urljoin(parse_result.base_url.rstrip("/") + "/", endpoint.path.lstrip("/"))

            # Generate description
            description = generate_tool_description(endpoint)

            # Build settings for API tool
            settings = {
                "type": "api",
                "api_url": full_url,
                "http_method": endpoint.method,
                "auth_type": default_auth_type,
                "timeout": timeout,
                "forward_user_context": forward_user_context,
                # Store original metadata for reference
                "_swagger_metadata": {
                    "operation_id": endpoint.operation_id,
                    "path": endpoint.path,
                    "tags": endpoint.tags,
                    "parameters": endpoint.parameters,
                    "source_spec": parse_result.title,
                },
            }

            if default_auth_env_var:
                settings["auth_env_var"] = default_auth_env_var

            # Generate snake_case name from summary or operation_id
            raw_name = (
                endpoint.summary or endpoint.operation_id or f"{endpoint.method} {endpoint.path}"
            )
            tool_name = to_snake_case(raw_name)

            tool = ToolFromEndpoint(
                id=tool_id,
                name=tool_name,
                description=description,
                entrypoint="src.tools.api_tool_executor:execute_api_tool",
                enabled=True,
                settings=settings,
            )

            tools.append(tool)
            existing_tool_ids.add(tool_id)

        return tools, skipped


# Convenience function for direct use
async def parse_swagger_url(url: str) -> SwaggerParseResult:
    """Parse Swagger/OpenAPI spec from URL."""
    parser = SwaggerParser()
    return await parser.parse(url)


async def import_tools_from_swagger(
    url: str,
    existing_tool_ids: set[str],
    endpoint_filter: list[str] | None = None,
    default_auth_type: str = "none",
    default_auth_env_var: str | None = None,
    forward_user_context: bool = False,
    timeout: int = 30,
) -> tuple[SwaggerParseResult, list[ToolFromEndpoint], list[str]]:
    """
    Import tools from a Swagger/OpenAPI specification.

    Args:
        url: URL to the Swagger/OpenAPI specification
        existing_tool_ids: Set of existing tool IDs to check for duplicates
        endpoint_filter: Optional list of operation_ids to include (None = all)
        default_auth_type: Default authentication type
        default_auth_env_var: Default environment variable for auth
        forward_user_context: Whether to forward user context headers
        timeout: Request timeout in seconds

    Returns:
        Tuple of (parse_result, tools, skipped_duplicates)
    """
    parser = SwaggerParser()
    parse_result = await parser.parse(url)

    tools, skipped = parser.generate_tool_configs(
        parse_result=parse_result,
        existing_tool_ids=existing_tool_ids,
        endpoint_filter=endpoint_filter,
        default_auth_type=default_auth_type,
        default_auth_env_var=default_auth_env_var,
        forward_user_context=forward_user_context,
        timeout=timeout,
    )

    return parse_result, tools, skipped
