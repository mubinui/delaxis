"""The runtime builds a manager-led crew for selector workflows, and reports what ran.

Before this, a selector workflow handed CrewAI one task per node and every
specialist ran on every message; the run result then listed every configured
agent and tool as "called". These tests drive ``_run_message_inner`` against a
stand-in ``crewai`` module, so they check the crew the runtime actually builds.
"""

from __future__ import annotations

import contextlib
import sys
import types
from enum import Enum
from typing import Any

import pytest

from src.config.agent_models import AgentConfig
from src.config.workflow_models import WorkflowConfig
from src.crewai_runtime.runtime import CrewAIWorkflowRuntime


class FakeProcess(Enum):
    sequential = "sequential"
    hierarchical = "hierarchical"


class FakeAgent:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.role = kwargs["role"]
        self.tools = kwargs.get("tools", [])
        self.step_callback = kwargs.get("step_callback")


class FakeTask:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.name = kwargs.get("name")
        self.agent = kwargs.get("agent")


class Step:
    """Mimics crewai's AgentFinish: has `output`, no `tool`."""

    def __init__(self, output: str) -> None:
        self.output = output


class ToolStep:
    """Mimics crewai's AgentAction: has `tool`."""

    def __init__(self, tool: str) -> None:
        self.tool = tool
        self.output = None


class FakeCrew:
    built: list[FakeCrew] = []
    # Which specialist role the fake manager delegates to.
    delegate_to: str | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        FakeCrew.built.append(self)

    def kickoff(self, inputs: dict[str, Any]) -> Any:
        manager = self.kwargs.get("manager_agent")
        agents = self.kwargs["agents"]
        if manager is not None:
            manager.step_callback(ToolStep("Delegate work to coworker"))
            for agent in agents:
                if agent.role == FakeCrew.delegate_to:
                    agent.step_callback(Step("60"))
            manager.step_callback(Step("The answer is 60."))
        else:
            for agent in agents:
                if agent.step_callback:
                    agent.step_callback(Step(f"{agent.role} done"))
        for task in self.kwargs["tasks"]:
            self.kwargs["task_callback"](
                types.SimpleNamespace(name=task.name, raw="The answer is 60.", agent="x")
            )
        return types.SimpleNamespace(raw="The answer is 60.", token_usage={})


@pytest.fixture
def fake_crewai(monkeypatch: pytest.MonkeyPatch) -> type[FakeCrew]:
    module = types.ModuleType("crewai")
    module.Agent = FakeAgent
    module.Crew = FakeCrew
    module.Process = FakeProcess
    module.Task = FakeTask
    monkeypatch.setitem(sys.modules, "crewai", module)
    FakeCrew.built = []
    FakeCrew.delegate_to = None
    return FakeCrew


def agents() -> list[AgentConfig]:
    return [
        AgentConfig(id="triage", type="conversable", name="Triage", is_selector=True),
        AgentConfig(id="calc", type="conversable", name="Calc", tools=["calculate"]),
        AgentConfig(id="search", type="conversable", name="Search", tools=["web_search"]),
    ]


def selector_workflow(**overrides: Any) -> WorkflowConfig:
    data: dict[str, Any] = {
        "id": "triage_flow",
        "name": "Triage",
        "description": "Routes to a specialist",
        "pattern": "selector",
        "process": "hierarchical",
        "topology": {
            "type": "graph",
            "entry_node": "triage",
            "nodes": [
                {"id": "triage", "agent_id": "triage", "is_router": True},
                {"id": "calc", "agent_id": "calc"},
                {"id": "search", "agent_id": "search"},
            ],
            "edges": [
                {"from_node": "triage", "to_node": "calc"},
                {"from_node": "triage", "to_node": "search"},
            ],
        },
    }
    data.update(overrides)
    return WorkflowConfig.model_validate(data)


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> CrewAIWorkflowRuntime:
    rt = CrewAIWorkflowRuntime(memory_enabled=False, storage_dir="./.crewai-test")
    monkeypatch.setattr(rt, "_resolve_llm_model", lambda config: "fake-llm")
    monkeypatch.setattr(rt, "_get_crewai_tools", lambda tool_ids, *a, **k: list(tool_ids))
    monkeypatch.setattr(rt, "_knowledge_retrieval_tools", lambda workflow: [])
    monkeypatch.setattr(rt, "_resolve_knowledge_sources", lambda *a, **k: [])
    monkeypatch.setattr(
        "src.crewai_runtime.runtime.load_agents_config",
        lambda: types.SimpleNamespace(agents=agents()),
    )
    return rt


def run(rt: CrewAIWorkflowRuntime, workflow: WorkflowConfig, events: list | None = None) -> Any:
    sink = (
        (lambda kind, payload, agent: events.append((kind, payload)))
        if events is not None
        else None
    )
    with contextlib.ExitStack() as stack:
        return rt._run_message_inner(workflow, "What is (12+8)*3?", "s1", "u1", {}, stack, sink)


def test_selector_agent_becomes_the_manager(runtime, fake_crewai) -> None:
    run(runtime, selector_workflow())
    crew = fake_crewai.built[-1]
    assert crew.kwargs["process"] is FakeProcess.hierarchical
    assert crew.kwargs["manager_agent"].role == "Triage"
    assert crew.kwargs["manager_agent"].kwargs["allow_delegation"] is True
    assert "manager_llm" not in crew.kwargs
    # The manager is not also a peer: CrewAI rejects that, and it would run twice.
    assert [agent.role for agent in crew.kwargs["agents"]] == ["Calc", "Search"]


def test_selector_crew_has_one_unassigned_task(runtime, fake_crewai) -> None:
    run(runtime, selector_workflow())
    tasks = fake_crewai.built[-1].kwargs["tasks"]
    assert len(tasks) == 1, "one task per node made the manager run every specialist"
    assert tasks[0].agent is None, "an assigned agent limits delegation to that agent"
    assert tasks[0].name == "triage"


def test_called_lists_report_what_ran_not_what_is_configured(runtime, fake_crewai) -> None:
    fake_crewai.delegate_to = "Calc"
    result = run(runtime, selector_workflow())
    meta = result.metadata
    assert meta["agent_ids_called"] == ["triage", "calc"]
    assert meta["agents_called"] == ["Triage", "Calc"]
    assert meta["tools_called"] == [], "no tool wrapper was invoked in this run"
    assert set(meta["configured_tools"]) == {"calculate", "web_search"}
    assert meta["manager_agent_id"] == "triage"


def test_delegation_is_streamed_onto_the_specialist_node(runtime, fake_crewai) -> None:
    fake_crewai.delegate_to = "Search"
    events: list = []
    run(runtime, selector_workflow(), events)
    transfers = [payload for kind, payload in events if kind == "agent_transfer"]
    assert transfers == [{"node_id": "search", "from_node_id": "triage", "target_agent": "search"}]
    outputs = [payload["node_id"] for kind, payload in events if kind == "node_output"]
    assert "search" in outputs and "triage" in outputs


def test_selector_with_tools_is_refused_with_a_fix(runtime, fake_crewai, monkeypatch) -> None:
    configs = agents()
    configs[0] = AgentConfig(
        id="triage", type="conversable", name="Triage", is_selector=True, tools=["calculate"]
    )
    monkeypatch.setattr(
        "src.crewai_runtime.runtime.load_agents_config",
        lambda: types.SimpleNamespace(agents=configs),
    )
    with pytest.raises(ValueError, match="give the tools to the specialist"):
        run(runtime, selector_workflow())


def test_hierarchical_without_a_selector_keeps_the_generic_manager(runtime, fake_crewai) -> None:
    workflow = selector_workflow(
        topology={
            "type": "graph",
            "entry_node": "calc",
            "nodes": [{"id": "calc", "agent_id": "calc"}, {"id": "search", "agent_id": "search"}],
            "edges": [{"from_node": "calc", "to_node": "search"}],
        }
    )
    run(runtime, workflow)
    crew = fake_crewai.built[-1]
    assert "manager_agent" not in crew.kwargs
    assert crew.kwargs["manager_llm"] == "fake-llm"


def test_sequential_runs_report_every_agent_that_ran(runtime, fake_crewai) -> None:
    workflow = selector_workflow(
        pattern="sequential",
        process="sequential",
        topology={
            "type": "sequential",
            "entry_node": "calc",
            "nodes": [{"id": "calc", "agent_id": "calc"}, {"id": "search", "agent_id": "search"}],
            "edges": [{"from_node": "calc", "to_node": "search"}],
        },
    )
    result = run(runtime, workflow)
    assert result.metadata["agent_ids_called"] == ["calc", "search"]
    assert len(fake_crewai.built[-1].kwargs["tasks"]) == 2
