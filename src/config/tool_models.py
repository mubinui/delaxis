"""Pydantic models for tool configuration validation."""

import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

VALID_TOOL_TYPES = {"function", "api", "mcp", "database", "sql", "mongodb", "gmail"}
MCP_TRANSPORTS = {"stdio", "sse", "streamable-http"}
GMAIL_CAPABILITIES = {"send", "search", "read"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ToolConfig(BaseModel):
    """Configuration for a tool.

    Supported tool types (settings['type']):
    - function: Python function tools (requires entrypoint)
    - api: HTTP API tools (requires settings.api_url)
    - mcp: MCP server tools (requires settings.transport + command/url)
    - database: NL2SQL database tools (requires settings.db_uri or db_uri_env_var)
    - sql: schema introspection + guarded SQL over any SQLAlchemy URL (read-only by default)
    - mongodb: collection listing, schema sampling and find (read-only by default)
    - gmail: Gmail tools via connected Google OAuth account (requires settings.account_email)
    """

    id: str = Field(
        pattern=r"^[a-z0-9_]+$",
        description="Unique tool identifier (lowercase alphanumeric and underscores only)"
    )
    name: str = Field(
        description="Function name for the tool"
    )
    description: str = Field(
        description="Description of what the tool does"
    )
    entrypoint: Optional[str] = Field(
        default=None,
        description="Python entrypoint in format 'module.path:function_name'. Required for function tools."
    )
    enabled: bool = Field(
        default=True,
        description="Whether the tool is enabled"
    )
    settings: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool-specific settings. For API tools, must include 'type': 'api' and 'api_url'."
    )
    is_async: bool = Field(
        default=False,
        description="Whether the tool function is async (True) or sync (False). For v0.4 compatibility."
    )
    category: Optional[str] = Field(
        default=None,
        description=(
            "Presentation category for the Library, e.g. 'security', 'data', 'files'. "
            "Purely cosmetic — it groups tools in the UI and never affects execution."
        )
    )
    
    # Versioning and metadata fields
    version: int = Field(
        default=1,
        ge=1,
        description="Configuration version number"
    )
    last_updated: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp of last configuration update"
    )

    @model_validator(mode='after')
    def validate_tool_type(self) -> 'ToolConfig':
        """Validate tool configuration based on type."""
        tool_type = self.settings.get('type', 'function')

        if tool_type not in VALID_TOOL_TYPES:
            raise ValueError(
                f"Tool '{self.id}': unknown tool type '{tool_type}'. "
                f"Supported types: {sorted(VALID_TOOL_TYPES)}"
            )

        if tool_type == 'api':
            # API tool validation
            api_url = self.settings.get('api_url')
            if not api_url:
                raise ValueError(
                    f"Tool '{self.id}': API tools require 'api_url' in settings. "
                    "Example: settings={'type': 'api', 'api_url': 'https://api.example.com/endpoint'}"
                )
            # Set default entrypoint for API tools if not provided
            if not self.entrypoint:
                self.entrypoint = "src.tools.api_tool_executor:execute_api_tool"
        elif tool_type == 'mcp':
            self._validate_mcp_settings()
        elif tool_type == 'database':
            self._validate_database_settings()
        elif tool_type == 'sql':
            self._validate_database_settings()
        elif tool_type == 'mongodb':
            self._validate_mongo_settings()
        elif tool_type == 'gmail':
            self._validate_gmail_settings()
        else:
            # Function tool validation
            if not self.entrypoint:
                raise ValueError(
                    f"Tool '{self.id}': Function tools require 'entrypoint' field. "
                    "Example: entrypoint='src.tools.calculator:calculate'"
                )

        return self

    def _validate_mcp_settings(self) -> None:
        transport = self.settings.get('transport')
        if transport not in MCP_TRANSPORTS:
            raise ValueError(
                f"Tool '{self.id}': MCP tools require 'transport' in settings, "
                f"one of {sorted(MCP_TRANSPORTS)}"
            )
        if transport == 'stdio':
            if not self.settings.get('command'):
                raise ValueError(
                    f"Tool '{self.id}': stdio MCP tools require 'command' in settings "
                    "(e.g. 'npx' or 'uvx')"
                )
            if self.settings.get('url'):
                raise ValueError(f"Tool '{self.id}': stdio MCP tools must not set 'url'")
            args = self.settings.get('args')
            if args is not None and not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
                raise ValueError(f"Tool '{self.id}': MCP 'args' must be a list of strings")
        else:
            url = self.settings.get('url')
            if not url or not str(url).startswith(('http://', 'https://')):
                raise ValueError(
                    f"Tool '{self.id}': {transport} MCP tools require an http(s) 'url' in settings"
                )
            if self.settings.get('command'):
                raise ValueError(f"Tool '{self.id}': {transport} MCP tools must not set 'command'")
            auth_type = self.settings.get('auth_type', 'none')
            if auth_type not in {'none', 'bearer'}:
                raise ValueError(f"Tool '{self.id}': MCP 'auth_type' must be 'none' or 'bearer'")
            if auth_type == 'bearer' and not self.settings.get('auth_env_var'):
                raise ValueError(
                    f"Tool '{self.id}': bearer-authenticated MCP tools require 'auth_env_var' "
                    "(the NAME of the env var holding the token — never the token itself)"
                )
        tool_filter = self.settings.get('tool_filter')
        if tool_filter is not None and not (
            isinstance(tool_filter, list) and all(isinstance(t, str) for t in tool_filter)
        ):
            raise ValueError(f"Tool '{self.id}': MCP 'tool_filter' must be a list of tool names")
        timeout = self.settings.get('connect_timeout')
        if timeout is not None and not (isinstance(timeout, (int, float)) and 1 <= timeout <= 300):
            raise ValueError(f"Tool '{self.id}': MCP 'connect_timeout' must be between 1 and 300 seconds")

    def _validate_database_settings(self) -> None:
        db_uri = self.settings.get('db_uri')
        db_uri_env_var = self.settings.get('db_uri_env_var')
        if bool(db_uri) == bool(db_uri_env_var):
            raise ValueError(
                f"Tool '{self.id}': database tools require exactly one of 'db_uri' "
                "or 'db_uri_env_var' in settings"
            )
        if db_uri and '@' in str(db_uri):
            raise ValueError(
                f"Tool '{self.id}': inline 'db_uri' values must not embed credentials. "
                "Use 'db_uri_env_var' (the NAME of an env var holding the full URI) instead."
            )
        tables = self.settings.get('tables')
        if tables is not None and not (isinstance(tables, list) and all(isinstance(t, str) for t in tables)):
            raise ValueError(f"Tool '{self.id}': database 'tables' must be a list of table names")

    def _validate_mongo_settings(self) -> None:
        uri = self.settings.get('uri')
        uri_env_var = self.settings.get('uri_env_var')
        if bool(uri) == bool(uri_env_var):
            raise ValueError(
                f"Tool '{self.id}': mongodb tools require exactly one of 'uri' "
                "or 'uri_env_var' in settings"
            )
        if uri and '@' in str(uri):
            raise ValueError(
                f"Tool '{self.id}': inline 'uri' values must not embed credentials. "
                "Use 'uri_env_var' (the NAME of an env var holding the full URI) instead."
            )
        if not self.settings.get('database'):
            raise ValueError(f"Tool '{self.id}': mongodb tools require a 'database' name in settings")
        collections = self.settings.get('collections')
        if collections is not None and not (
            isinstance(collections, list) and all(isinstance(c, str) for c in collections)
        ):
            raise ValueError(f"Tool '{self.id}': mongodb 'collections' must be a list of names")

    def _validate_gmail_settings(self) -> None:
        account_email = self.settings.get('account_email')
        if not account_email or not _EMAIL_RE.match(str(account_email)):
            raise ValueError(
                f"Tool '{self.id}': gmail tools require a valid 'account_email' in settings"
            )
        capabilities = self.settings.get('capabilities', sorted(GMAIL_CAPABILITIES))
        if not (
            isinstance(capabilities, list)
            and capabilities
            and set(capabilities) <= GMAIL_CAPABILITIES
        ):
            raise ValueError(
                f"Tool '{self.id}': gmail 'capabilities' must be a non-empty subset "
                f"of {sorted(GMAIL_CAPABILITIES)}"
            )
        self.settings['capabilities'] = capabilities

    def validate_entrypoint(self) -> None:
        """Validate entrypoint format."""
        if self.entrypoint and ":" not in self.entrypoint:
            raise ValueError(
                f"Tool '{self.id}': Invalid entrypoint format '{self.entrypoint}'. "
                "Expected 'module.path:function_name' (e.g., 'src.tools.calculator:calculate')"
            )
    
    def is_api_tool(self) -> bool:
        """Check if this is an API tool."""
        return self.settings.get('type') == 'api'


class ToolsConfig(BaseModel):
    """Root configuration for tools."""

    version: str = Field(
        description="Configuration version"
    )
    tools: list[ToolConfig] = Field(
        description="List of tool configurations"
    )

    def get_tool(self, tool_id: str) -> Optional[ToolConfig]:
        """
        Get tool configuration by ID.

        Args:
            tool_id: Tool identifier

        Returns:
            ToolConfig or None if not found
        """
        return next((t for t in self.tools if t.id == tool_id), None)

    def get_enabled_tools(self) -> list[ToolConfig]:
        """
        Get all enabled tool configurations.

        Returns:
            List of enabled ToolConfig objects
        """
        return [t for t in self.tools if t.enabled]

    def validate_all(self) -> None:
        """Validate all tool configurations."""
        for tool in self.tools:
            tool.validate_entrypoint()
