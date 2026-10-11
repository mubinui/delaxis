"""A connector node at run time: one agent tool per ticked action.

Factory-built tools bypass the runtime's tool wrapper, so each tool reports
its own tool_call_start / tool_call_result events; connector calls then show
on the canvas, in the timeline and in run history like any other tool. A
failed call returns {"error": ...} to the agent so it can correct itself; a
connection that no longer exists fails the run, because an agent that silently
lost its tools gives answers nobody should trust.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable
from typing import Any

from crewai.tools import BaseTool

from src.connectors.base import (
    Connector,
    ConnectorContext,
    ConnectorError,
    args_model,
    validate_args,
)
from src.connectors.registry import get_connector
from src.connectors.store import ConnectionStore
from src.tools.runtime_tool_factories import RuntimeToolFactory


class ConnectorActionTool(BaseTool):
    """One connector action as a CrewAI tool."""

    runner: Callable[..., str]

    def _run(self, **kwargs: Any) -> str:
        return self.runner(**kwargs)


def _as_text(result: Any) -> str:
    return result if isinstance(result, str) else json.dumps(result, default=str)


class ConnectorToolFactory(RuntimeToolFactory):
    accepts_emitter = True

    def _connector(self) -> Connector:
        connector = get_connector(str(self.settings.get("connector", "")))
        if connector is None:
            raise ConnectorError(
                f"Tool '{self.name}' names an unknown connector '{self.settings.get('connector')}'."
            )
        return connector

    def _context(self, connector: Connector) -> ConnectorContext:
        connection_id = str(self.settings.get("connection_id") or "")
        secrets = ConnectionStore().secrets(connection_id) if connection_id else None
        if secrets is None:
            raise ConnectorError(
                f"The {connector.name} node '{self.name}' uses a connection that no longer "
                f"exists ({connection_id or 'none chosen'}). Pick another in its inspector."
            )
        return ConnectorContext(secrets, dict(self.settings.get("options") or {}))

    def build(self, stack: contextlib.ExitStack, emitter: Any = None) -> list[Any]:
        connector = self._connector()
        ctx = self._context(connector)
        tools: list[Any] = []
        for action_id in self.settings.get("actions") or []:
            action = connector.action(str(action_id))
            tool_name = f"{self.name}_{action.id}"

            def runner(_action: Any = action, _tool_name: str = tool_name, **kwargs: Any) -> str:
                if emitter is not None:
                    emitter.tool_started(self.tool_id, _tool_name, kwargs)
                started = time.perf_counter()
                try:
                    args = validate_args(connector.id, _action, kwargs)
                    text = _as_text(_action.run(ctx, args))
                except ConnectorError as exc:
                    if emitter is not None:
                        emitter.tool_finished(
                            self.tool_id,
                            _tool_name,
                            error=str(exc),
                            duration_ms=int((time.perf_counter() - started) * 1000),
                        )
                    return json.dumps({"error": str(exc)})
                if emitter is not None:
                    emitter.tool_finished(
                        self.tool_id,
                        _tool_name,
                        result=text,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                    )
                return text

            tools.append(
                ConnectorActionTool(
                    name=tool_name,
                    description=f"{connector.name}: {action.description}",
                    args_schema=args_model(connector.id, action),
                    runner=runner,
                )
            )
        return tools

    def sandbox_function(self) -> Callable[..., Any]:
        factory = self

        def connector_action(action: str = "", **kwargs: Any) -> Any:
            """Run one of this node's actions: pass its id as 'action' and its arguments."""
            connector = factory._connector()
            if action not in (factory.settings.get("actions") or []):
                return {"error": f"'{action}' is not ticked on this node."}
            chosen = connector.action(action)
            try:
                return chosen.run(
                    factory._context(connector), validate_args(connector.id, chosen, kwargs)
                )
            except ConnectorError as exc:
                return {"error": str(exc)}

        connector_action.__name__ = self.name
        return connector_action
