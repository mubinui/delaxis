"""Per-run factories for tool types backed by external resources (MCP, database, Gmail).

Unlike function/api tools — which are plain callables held by the registry — these
tool types produce native CrewAI ``BaseTool`` instances and may hold live resources
(an MCP server subprocess/connection). They are therefore instantiated *per workflow
run* inside an ``ExitStack`` scope owned by the runtime, which guarantees cleanup
even when the crew kickoff raises.

Registration in the ToolRegistry stays inert: only ``build()`` opens connections.
"""

from __future__ import annotations

import contextlib
import json
import os
from abc import ABC, abstractmethod
from typing import Any, Callable

from src.audit_logging import get_logger

logger = get_logger(__name__)


class RuntimeToolFactory(ABC):
    """Builds CrewAI BaseTool instances for one workflow run."""

    def __init__(self, tool_id: str, name: str, description: str, settings: dict[str, Any]) -> None:
        self.tool_id = tool_id
        self.name = name
        self.description = description
        self.settings = settings or {}

    @abstractmethod
    def build(self, stack: contextlib.ExitStack) -> list[Any]:
        """Instantiate tools for one run; register any cleanup on ``stack``."""

    @abstractmethod
    def sandbox_function(self) -> Callable[..., Any]:
        """Plain callable for POST /api/v1/tools/{id}/execute (opens/closes per call)."""


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------

class McpToolFactory(RuntimeToolFactory):
    """One Delaxis tool config == one MCP server; expands into that server's tools."""

    def _server_params(self) -> Any:
        settings = self.settings
        transport = settings.get("transport", "stdio")

        if transport == "stdio":
            from mcp import StdioServerParameters

            env: dict[str, str] = {}
            for var_name in settings.get("env_passthrough", []) or []:
                value = os.environ.get(var_name)
                if value is not None:
                    env[var_name] = value
            env.update(settings.get("env", {}) or {})
            return StdioServerParameters(
                command=settings["command"],
                args=list(settings.get("args", []) or []),
                env=env or None,
            )

        headers = dict(settings.get("headers", {}) or {})
        if settings.get("auth_type") == "bearer":
            env_var = settings.get("auth_env_var", "")
            token = os.environ.get(env_var)
            if not token:
                raise ValueError(
                    f"MCP tool '{self.tool_id}': env var '{env_var}' is not set "
                    "(it should hold the bearer token for the MCP server)"
                )
            headers["Authorization"] = f"Bearer {token}"

        params: dict[str, Any] = {"url": settings["url"]}
        if headers:
            params["headers"] = headers
        if transport == "streamable-http":
            params["transport"] = "streamable-http"
        return params

    def _open_adapter(self) -> Any:
        from crewai_tools import MCPServerAdapter

        tool_filter = self.settings.get("tool_filter") or []
        # MCPServerAdapter.__init__ connects immediately; caller owns .stop().
        return MCPServerAdapter(
            self._server_params(),
            *tool_filter,
            connect_timeout=int(self.settings.get("connect_timeout") or 30),
        )

    def build(self, stack: contextlib.ExitStack) -> list[Any]:
        adapter = self._open_adapter()
        stack.callback(adapter.stop)
        tools = list(adapter.tools)
        logger.info(
            "mcp_adapter_opened",
            tool_id=self.tool_id,
            transport=self.settings.get("transport"),
            tool_count=len(tools),
        )
        return tools

    def inspect(self) -> list[dict[str, Any]]:
        """Connect, list the server's tools (with schemas), and disconnect."""
        adapter = self._open_adapter()
        try:
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "args_schema": t.args_schema.model_json_schema() if getattr(t, "args_schema", None) else {},
                }
                for t in adapter.tools
            ]
        finally:
            adapter.stop()

    def sandbox_function(self) -> Callable[..., Any]:
        factory = self

        def call_mcp_tool(tool_name: str = "", arguments: dict | None = None) -> Any:
            """Call a tool on the configured MCP server. Empty tool_name lists available tools."""
            adapter = factory._open_adapter()
            try:
                if not tool_name:
                    return [{"name": t.name, "description": t.description} for t in adapter.tools]
                for t in adapter.tools:
                    if t.name == tool_name:
                        return t._run(**(arguments or {}))
                available = [t.name for t in adapter.tools]
                return f"Tool '{tool_name}' not found on this MCP server. Available: {available}"
            finally:
                adapter.stop()

        call_mcp_tool.__name__ = self.name
        return call_mcp_tool


# ---------------------------------------------------------------------------
# Database (NL2SQL)
# ---------------------------------------------------------------------------

def _make_delaxis_nl2sql_class() -> type:
    """Build the DelaxisNL2SQLTool class lazily so importing this module never
    requires crewai_tools/sqlalchemy."""
    from crewai_tools import NL2SQLTool
    from sqlalchemy import create_engine, inspect as sa_inspect

    class DelaxisNL2SQLTool(NL2SQLTool):
        """Dialect-neutral NL2SQL: introspects schema via sqlalchemy.inspect().

        The stock NL2SQLTool queries information_schema with Postgres-specific
        SQL at construction time, which breaks SQLite (no information_schema)
        and MySQL (different schema scoping). SQLAlchemy's inspector works
        across all three, and lets us honor a table allowlist.
        """

        allowed_tables: list[str] | None = None

        def model_post_init(self, __context: Any) -> None:  # noqa: D102
            engine = create_engine(self.db_uri)
            try:
                inspector = sa_inspect(engine)
                names = [
                    n for n in inspector.get_table_names()
                    if not self.allowed_tables or n in self.allowed_tables
                ]
                self.tables = [{"table_name": n} for n in names]
                self.columns = {
                    f"{n}_columns": [
                        {"column_name": c["name"], "data_type": str(c["type"])}
                        for c in inspector.get_columns(n)
                    ]
                    for n in names
                }
            finally:
                engine.dispose()
            # Surface the schema in the description so the LLM writes correct SQL
            # up front instead of only learning the schema from error retries.
            schema_summary = ", ".join(
                f"{n}({', '.join(col['column_name'] for col in self.columns.get(f'{n}_columns', []))})"
                for n in (t["table_name"] for t in self.tables)
            )
            if schema_summary:
                self.description = f"{self.description} Available tables: {schema_summary}."

    return DelaxisNL2SQLTool


class DatabaseToolFactory(RuntimeToolFactory):
    def _resolve_uri(self) -> str:
        env_var = self.settings.get("db_uri_env_var")
        if env_var:
            uri = os.environ.get(env_var)
            if not uri:
                raise ValueError(
                    f"Database tool '{self.tool_id}': env var '{env_var}' is not set "
                    "(it should hold the SQLAlchemy database URI)"
                )
            return uri
        return str(self.settings["db_uri"])

    def _build_tool(self) -> Any:
        delaxis_cls = _make_delaxis_nl2sql_class()
        return delaxis_cls(
            name=self.name,
            description=self.description
            or "Convert natural language to SQL and run it against the configured database.",
            db_uri=self._resolve_uri(),
            allow_dml=bool(self.settings.get("allow_dml", False)),
            allowed_tables=self.settings.get("tables"),
        )

    def build(self, stack: contextlib.ExitStack) -> list[Any]:
        return [self._build_tool()]

    def sandbox_function(self) -> Callable[..., Any]:
        factory = self

        def run_sql(sql_query: str) -> Any:
            """Run a SQL query against the configured database (read-only unless allow_dml)."""
            return factory._build_tool()._run(sql_query=sql_query)

        run_sql.__name__ = self.name
        return run_sql


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

class GmailToolFactory(RuntimeToolFactory):
    def _capabilities(self) -> list[str]:
        return list(self.settings.get("capabilities") or ["send", "search", "read"])

    def build(self, stack: contextlib.ExitStack) -> list[Any]:
        from crewai.tools import tool as crewai_tool

        from src.tools import gmail_tool

        account_email = self.settings["account_email"]
        max_results_cap = int(self.settings.get("max_results") or 10)
        tools: list[Any] = []

        if "send" in self._capabilities():
            def send_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> str:
                """Send an email from the connected Gmail account. 'to', 'cc' and 'bcc' accept comma-separated addresses. Returns the sent message id."""
                return gmail_tool.send_email(account_email, to=to, subject=subject, body=body, cc=cc, bcc=bcc)

            tools.append(crewai_tool(f"{self.name}_send_email")(send_email))

        if "search" in self._capabilities():
            def search_emails(query: str, max_results: int = 10) -> str:
                """Search the connected Gmail mailbox with Gmail query syntax (e.g. 'from:alice subject:invoice newer_than:7d is:unread'). Returns a JSON array of {id, threadId, date, from, to, subject, snippet}."""
                return gmail_tool.search_emails(account_email, query=query, max_results=min(max_results, max_results_cap))

            tools.append(crewai_tool(f"{self.name}_search_emails")(search_emails))

        if "read" in self._capabilities():
            def read_email(message_id: str) -> str:
                """Read one email in full by its Gmail message id (obtained from search results). Returns JSON with headers and the plain-text body."""
                return gmail_tool.read_email(account_email, message_id=message_id)

            tools.append(crewai_tool(f"{self.name}_read_email")(read_email))

        return tools

    def sandbox_function(self) -> Callable[..., Any]:
        factory = self

        def gmail_action(action: str, **kwargs: Any) -> Any:
            """Test the Gmail tool: action is 'send' (to, subject, body), 'search' (query, max_results), or 'read' (message_id)."""
            from src.tools import gmail_tool

            account_email = factory.settings["account_email"]
            if action == "send":
                return gmail_tool.send_email(
                    account_email,
                    to=kwargs.get("to", ""),
                    subject=kwargs.get("subject", ""),
                    body=kwargs.get("body", ""),
                    cc=kwargs.get("cc", ""),
                    bcc=kwargs.get("bcc", ""),
                )
            if action == "search":
                return gmail_tool.search_emails(
                    account_email,
                    query=kwargs.get("query", ""),
                    max_results=int(kwargs.get("max_results", 10)),
                )
            if action == "read":
                return gmail_tool.read_email(account_email, message_id=kwargs.get("message_id", ""))
            return json.dumps({"error": f"Unknown action '{action}'. Use send, search, or read."})

        gmail_action.__name__ = self.name
        return gmail_action


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_FACTORY_TYPES: dict[str, type[RuntimeToolFactory]] = {
    "mcp": McpToolFactory,
    "database": DatabaseToolFactory,
    "gmail": GmailToolFactory,
}


def create_runtime_factory(
    tool_type: str,
    tool_id: str,
    name: str,
    description: str,
    settings: dict[str, Any],
) -> RuntimeToolFactory:
    factory_cls = _FACTORY_TYPES.get(tool_type)
    if factory_cls is None:
        raise ValueError(f"No runtime factory for tool type '{tool_type}'")
    return factory_cls(tool_id, name, description, settings)


def is_factory_tool_type(tool_type: str) -> bool:
    return tool_type in _FACTORY_TYPES
