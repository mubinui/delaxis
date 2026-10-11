"""Connector nodes become agent tools with real schemas, events, and honest failures."""

from __future__ import annotations

import contextlib
import json
from dataclasses import replace
from typing import Any

import pytest

from src.config.tool_models import ToolConfig
from src.connectors import tool_factory as tf
from src.connectors.base import ConnectionSecrets, ConnectorError
from src.tools.runtime_tool_factories import create_runtime_factory, is_factory_tool_type


class Emitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, Any]] = []

    def tool_started(self, tool_id: str, name: str, kwargs: dict[str, Any]) -> None:
        self.events.append(("start", name, kwargs))

    def tool_finished(
        self,
        tool_id: str,
        name: str,
        result: Any = None,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self.events.append(("finish", name, error or result))


SETTINGS = {
    "type": "connector",
    "connector": "jira",
    "connection_id": "c1",
    "actions": ["search_issues", "add_comment"],
    "options": {"project": "OPS"},
}


@pytest.fixture
def secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    class Store:
        def secrets(self, connection_id: str) -> ConnectionSecrets | None:
            if connection_id != "c1":
                return None
            return ConnectionSecrets(
                base_url="https://acme.atlassian.net",
                username="a@b.c",
                token="t",
                options={"api_version": "3"},
            )

    monkeypatch.setattr(tf, "ConnectionStore", Store)


def factory(settings: dict[str, Any] | None = None) -> Any:
    return create_runtime_factory(
        "connector", "ops_jira", "ops_jira", "Jira for ops", settings or SETTINGS
    )


def _with_action(connector: Any, action_id: str, run: Any) -> Any:
    actions = tuple(replace(a, run=run) if a.id == action_id else a for a in connector.actions)
    return replace(connector, actions=actions)


def test_connector_is_a_factory_type() -> None:
    assert is_factory_tool_type("connector")


def test_one_tool_per_ticked_action_with_the_action_schema(secrets: None) -> None:
    tools = factory().build(contextlib.ExitStack(), emitter=None)
    assert [t.name for t in tools] == ["ops_jira_search_issues", "ops_jira_add_comment"]
    schema = tools[0].args_schema.model_json_schema()
    assert schema["required"] == ["jql"]


def test_a_call_runs_the_action_and_emits_events(
    secrets: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []

    def fake_run(ctx: Any, args: dict[str, Any]) -> Any:
        seen.append((ctx.option("project"), args))
        return [{"key": "OPS-1"}]

    from src.connectors.jira import CONNECTOR

    monkeypatch.setattr(
        tf, "get_connector", lambda cid: _with_action(CONNECTOR, "search_issues", fake_run)
    )
    emitter = Emitter()
    tool = factory().build(contextlib.ExitStack(), emitter=emitter)[0]
    out = tool.run(jql="project = OPS")
    assert json.loads(out) == [{"key": "OPS-1"}]
    assert seen == [("OPS", {"jql": "project = OPS", "max_results": 20})]
    assert [e[0] for e in emitter.events] == ["start", "finish"]


def test_bad_arguments_come_back_to_the_agent_as_an_error(secrets: None) -> None:
    emitter = Emitter()
    tool = factory().build(contextlib.ExitStack(), emitter=emitter)[0]
    out = json.loads(tool._run(max_results=5))
    assert "jql" in out["error"]
    assert emitter.events[-1][0] == "finish" and "jql" in emitter.events[-1][2]


def test_missing_connection_fails_the_run_with_a_named_message(secrets: None) -> None:
    with pytest.raises(ConnectorError, match="ops_jira.*no longer exists"):
        factory({**SETTINGS, "connection_id": "gone"}).build(contextlib.ExitStack(), emitter=None)


def test_tool_config_validates_connector_settings() -> None:
    ToolConfig(id="ops_jira", name="ops_jira", description="d", settings=SETTINGS)
    with pytest.raises(ValueError, match="unknown connector"):
        ToolConfig(id="x", name="x", description="d", settings={**SETTINGS, "connector": "nope"})
    with pytest.raises(ValueError, match="connection"):
        ToolConfig(id="x", name="x", description="d", settings={**SETTINGS, "connection_id": ""})
    with pytest.raises(ValueError, match="at least one Jira action"):
        ToolConfig(id="x", name="x", description="d", settings={**SETTINGS, "actions": []})
    with pytest.raises(ValueError, match="merge_all"):
        ToolConfig(
            id="x", name="x", description="d", settings={**SETTINGS, "actions": ["merge_all"]}
        )


def test_runtime_lets_a_connector_error_fail_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from src.crewai_runtime.runtime import CrewAIWorkflowRuntime

    class Broken:
        accepts_emitter = True

        def build(self, stack: Any, emitter: Any = None) -> list[Any]:
            raise ConnectorError("node 'ops_jira' uses a connection that no longer exists")

    registry = SimpleNamespace(
        get_tool=lambda tool_id: SimpleNamespace(factory=Broken(), tool_id=tool_id, name=tool_id)
    )
    monkeypatch.setattr("src.crewai_runtime.runtime.get_tool_registry", lambda: registry)
    runtime = CrewAIWorkflowRuntime(memory_enabled=False, storage_dir="./.crewai-test")
    with pytest.raises(ConnectorError, match="no longer exists"):
        runtime._get_crewai_tools(["ops_jira"], contextlib.ExitStack())
