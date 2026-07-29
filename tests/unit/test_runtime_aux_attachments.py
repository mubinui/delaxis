"""Tests for canvas aux attachments (tools/memory/knowledge) in the CrewAI runtime."""

from types import SimpleNamespace

from src.config.agent_models import AgentConfig
from src.config.topology_models import AgentNode
from src.config.workflow_models import WorkflowConfig
from src.crewai_runtime.execution_events import TaskMeta
from src.crewai_runtime.runtime import CrewAIWorkflowRuntime


def make_runtime() -> CrewAIWorkflowRuntime:
    return CrewAIWorkflowRuntime(memory_enabled=False, storage_dir="./.crewai-test")


def test_node_attachments_fold_per_agent_with_union() -> None:
    nodes = [
        AgentNode(id="n1", agent_id="agent_one", tools=["t1", "t2"], memory=True),
        AgentNode(id="n2", agent_id="agent_one", tools=["t2", "t3"], knowledge=True),
        AgentNode(id="n3", agent_id="agent_two"),
    ]
    extra_tools, wants_memory, wants_knowledge, routers = CrewAIWorkflowRuntime._node_attachments(nodes)
    assert extra_tools == {"agent_one": ["t1", "t2", "t3"]}
    assert wants_memory == {"agent_one"}
    assert wants_knowledge == {"agent_one"}
    assert routers == set()


def test_node_attachments_collect_router_agents() -> None:
    nodes = [
        AgentNode(id="n1", agent_id="agent_one", is_router=True),
        AgentNode(id="n2", agent_id="agent_two"),
    ]
    _, _, _, routers = CrewAIWorkflowRuntime._node_attachments(nodes)
    assert routers == {"agent_one"}


def test_create_agent_grants_delegation_for_router_nodes(monkeypatch) -> None:
    runtime = make_runtime()
    monkeypatch.setattr(runtime, "_get_crewai_tools", lambda *a, **k: [])

    captured: dict = {}

    def fake_agent_cls(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(**kwargs)

    config = AgentConfig(id="agent_one", type="conversable", name="Agent One")
    runtime._create_agent(fake_agent_cls, config, delegates=True)
    assert captured["allow_delegation"] is True

    captured.clear()
    runtime._create_agent(fake_agent_cls, config)
    assert captured["allow_delegation"] is False


def test_create_agent_merges_extra_tools_and_attachment_kwargs(monkeypatch) -> None:
    runtime = make_runtime()
    captured_tool_ids: list[list[str]] = []

    def fake_get_tools(tool_ids, stack=None, run_tool_cache=None, emitter=None):
        captured_tool_ids.append(list(tool_ids))
        return []

    monkeypatch.setattr(runtime, "_get_crewai_tools", fake_get_tools)

    captured_kwargs: dict = {}

    def fake_agent_cls(**kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(**kwargs)

    config = AgentConfig(id="agent_one", type="conversable", name="Agent One", tools=["t1"])
    knowledge_sources = [object()]
    runtime._create_agent(
        fake_agent_cls,
        config,
        emitter=None,
        extra_tool_ids=["t1", "t2"],
        memory_attached=True,
        knowledge_sources=knowledge_sources,
    )

    assert captured_tool_ids == [["t1", "t2"]]  # deduped: config t1 + extra t2
    assert captured_kwargs["memory"] is True
    assert captured_kwargs["knowledge_sources"] == knowledge_sources


def test_create_agent_defaults_omit_attachment_kwargs(monkeypatch) -> None:
    runtime = make_runtime()
    monkeypatch.setattr(runtime, "_get_crewai_tools", lambda *a, **k: [])

    captured_kwargs: dict = {}

    def fake_agent_cls(**kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(**kwargs)

    config = AgentConfig(id="agent_one", type="conversable", name="Agent One")
    runtime._create_agent(fake_agent_cls, config)

    assert "memory" not in captured_kwargs
    assert "knowledge_sources" not in captured_kwargs


def make_workflow() -> WorkflowConfig:
    return WorkflowConfig(
        id="wf1",
        name="WF",
        description="test workflow",
        topology={
            "type": "sequential",
            "entry_node": "n1",
            "nodes": [
                {"id": "n1", "agent_id": "agent_one"},
                {"id": "n2", "agent_id": "agent_two"},
            ],
            "edges": [{"from_node": "n1", "to_node": "n2"}],
        },
    )


def test_create_tasks_names_tasks_after_node_ids_and_tracks_upstream() -> None:
    runtime = make_runtime()
    workflow = make_workflow()
    ordered_nodes = runtime._ordered_nodes(workflow)
    fake_agents = {"agent_one": object(), "agent_two": object()}

    def fake_task_cls(**kwargs):
        return SimpleNamespace(**kwargs)

    tasks, metas = runtime._create_tasks(
        task_cls=fake_task_cls,
        workflow=workflow,
        ordered_nodes=ordered_nodes,
        crew_agent_by_id=fake_agents,
        message="hi",
        session_id="s1",
        user_id="u1",
        metadata={},
    )

    assert [task.name for task in tasks] == ["n1", "n2"]
    assert [meta.node_id for meta in metas] == ["n1", "n2"]
    assert metas[0].upstream_node_ids == []
    assert metas[1].upstream_node_ids == ["n1"]
    assert isinstance(metas[0], TaskMeta)
    # metas stay aligned with tasks even though they're separate lists
    assert metas[1].index == 1


def test_create_tasks_skips_nodes_with_missing_agents_without_misalignment() -> None:
    runtime = make_runtime()
    workflow = make_workflow()
    ordered_nodes = runtime._ordered_nodes(workflow)
    fake_agents = {"agent_two": object()}  # agent_one missing

    tasks, metas = runtime._create_tasks(
        task_cls=lambda **kwargs: SimpleNamespace(**kwargs),
        workflow=workflow,
        ordered_nodes=ordered_nodes,
        crew_agent_by_id=fake_agents,
        message="hi",
        session_id="s1",
        user_id="u1",
        metadata={},
    )

    assert [task.name for task in tasks] == ["n2"]
    assert [meta.node_id for meta in metas] == ["n2"]
    # n1 never created a task, so it must not appear as upstream context
    assert metas[0].upstream_node_ids == []


def test_knowledge_tools_need_a_collection() -> None:
    """No collection means no search tool, rather than one that can only fail."""
    runtime = make_runtime()
    workflow = make_workflow()
    workflow.knowledge.enabled = True
    workflow.knowledge.collections = []
    assert runtime._knowledge_retrieval_tools(workflow) == []


def test_knowledge_tools_skipped_when_rag_service_is_off(monkeypatch) -> None:
    runtime = make_runtime()
    workflow = make_workflow()
    workflow.knowledge.enabled = True
    workflow.knowledge.collections = ["handbook"]

    from src.config import settings as settings_module

    original = settings_module.get_settings()
    monkeypatch.setattr(original.external_services, "rag_pipeline_enabled", False)
    assert runtime._knowledge_retrieval_tools(workflow) == []


def test_knowledge_tool_queries_every_configured_collection(monkeypatch) -> None:
    runtime = make_runtime()
    workflow = make_workflow()
    workflow.knowledge.enabled = True
    workflow.knowledge.collections = ["handbook", "policies"]
    workflow.knowledge.top_k = 3

    from src.config import settings as settings_module

    monkeypatch.setattr(settings_module.get_settings().external_services, "rag_pipeline_enabled", True)

    queried: list[tuple[str, str, int]] = []

    async def fake_query_rag(query: str, collection: str, top_k: int):
        queried.append((query, collection, top_k))
        return {"success": True, "results": [{"text": f"passage from {collection}", "score": 0.9}]}

    import src.tools.rag_pipeline as rag_pipeline

    monkeypatch.setattr(rag_pipeline, "query_rag", fake_query_rag)

    tools = runtime._knowledge_retrieval_tools(workflow)
    assert len(tools) == 1

    result = tools[0].run(query="what is the leave policy")
    assert queried == [
        ("what is the leave policy", "handbook", 3),
        ("what is the leave policy", "policies", 3),
    ]
    assert "passage from handbook" in result
    assert "passage from policies" in result


def test_knowledge_tool_survives_one_failing_collection(monkeypatch) -> None:
    runtime = make_runtime()
    workflow = make_workflow()
    workflow.knowledge.enabled = True
    workflow.knowledge.collections = ["broken", "good"]

    from src.config import settings as settings_module

    monkeypatch.setattr(settings_module.get_settings().external_services, "rag_pipeline_enabled", True)

    async def fake_query_rag(query: str, collection: str, top_k: int):
        if collection == "broken":
            raise RuntimeError("connection refused")
        return {"success": True, "results": [{"text": "still here", "score": 0.5}]}

    import src.tools.rag_pipeline as rag_pipeline

    monkeypatch.setattr(rag_pipeline, "query_rag", fake_query_rag)

    result = runtime._knowledge_retrieval_tools(workflow)[0].run(query="anything")
    assert "still here" in result
