"""Regression tests for defects found while auditing every component end to end."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.test_models import TestStatus, WorkflowExecuteResponse, WorkflowTestCaseResponse
from src.core.workflow_test_runner import judge, responding_agent
from src.infrastructure import redis_guard
from src.memory.models import ConversationState
from src.utils.time import as_utc, parse_utc, utc_now_naive

ROOT = Path(__file__).resolve().parents[2]


# --- Redis is optional even when configured but down ------------------------------------


@pytest.fixture
def guard_env(monkeypatch: pytest.MonkeyPatch):
    redis_guard.reset_for_tests()
    yield monkeypatch
    redis_guard.reset_for_tests()


def test_unreachable_redis_is_blanked_not_fatal(guard_env) -> None:
    guard_env.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    guard_env.setattr(redis_guard, "redis_reachable", lambda url, timeout=1.0: False)
    assert redis_guard.ensure_redis_or_disable() is False
    # Blank rather than removed: a process variable beats the value in .env.
    assert os.environ["REDIS_URL"] == ""


def test_reachable_redis_is_kept(guard_env) -> None:
    guard_env.setenv("REDIS_URL", "redis://example:6379/0")
    guard_env.setattr(redis_guard, "redis_reachable", lambda url, timeout=1.0: True)
    assert redis_guard.ensure_redis_or_disable() is True
    assert os.environ["REDIS_URL"] == "redis://example:6379/0"


def test_redis_reachable_reports_a_refused_port() -> None:
    assert redis_guard.redis_reachable("redis://127.0.0.1:1/0", timeout=0.2) is False


# --- Times from storage compare with aware "now" -----------------------------------------


def test_naive_values_are_read_as_utc() -> None:
    naive = datetime(2026, 1, 1, 12, 0)
    assert as_utc(naive) == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert as_utc(naive) < datetime.now(UTC)
    assert parse_utc("2026-01-01T12:00:00") == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert parse_utc("2026-01-01T12:00:00Z").tzinfo is not None
    assert utc_now_naive().tzinfo is None


def test_sessions_saved_before_aware_times_still_sort() -> None:
    old = ConversationState.model_validate(
        {
            "session_id": str(uuid4()),
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
    )
    new = ConversationState(session_id=uuid4())
    assert old.updated_at.tzinfo is not None
    assert sorted([new, old], key=lambda s: s.updated_at) == [old, new]


# --- Tool execution -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> TestClient:
    from src.api.main import app

    return TestClient(app)


def test_tool_execute_runs_the_tool(client: TestClient) -> None:
    body = client.post("/api/v1/tools/calculate/execute", json={"args": {"expression": "2+2*5"}})
    assert body.status_code == 200
    assert body.json()["status"] == "success"
    assert body.json()["result"] == 12


@pytest.mark.parametrize("wrong_key", ["arguments", "parameters", "input"])
def test_tool_execute_rejects_misnamed_arguments(client: TestClient, wrong_key: str) -> None:
    response = client.post(
        "/api/v1/tools/calculate/execute", json={wrong_key: {"expression": "1+1"}}
    )
    assert response.status_code == 422, "a misnamed key used to run the tool with no arguments"


# --- Dashboard reports real numbers ----------------------------------------------------------


def test_dashboard_counts_come_from_the_configs(client: TestClient) -> None:
    data = client.get("/api/v1/metrics/dashboard").json()
    shipped = json.loads((ROOT / "configs" / "workflows.json").read_text())["workflows"]
    assert data["total_workflows"] == len(shipped)
    assert data["total_agents"] > 0
    assert data["total_tools"] > 0
    for key in ("error_rate", "avg_response_time", "cache_hit_rate"):
        assert 0.0 <= data[key]


def test_readiness_does_not_report_a_missing_function_as_redis_down(client: TestClient) -> None:
    data = client.get("/api/v1/health/ready").json()
    assert data["status"] == "ready"


# --- Every shipped config round-trips ---------------------------------------------------------


def test_shipped_configs_load_validate_and_round_trip() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_configs", ROOT / "scripts" / "check_configs.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.main(ROOT / "configs") == 0, module.problems
    assert module.warnings == []


# --- Test cases are judged on every expectation ----------------------------------------------


def case(**overrides) -> WorkflowTestCaseResponse:
    now = datetime.now(UTC)
    data = {
        "id": uuid4(),
        "workflow_id": "wf",
        "name": "t",
        "description": None,
        "input_message": "hi",
        "expected_agent": None,
        "expected_tools": None,
        "expected_output_contains": None,
        "expected_output_pattern": None,
        "timeout_seconds": 30,
        "enabled": True,
        "created_at": now,
        "updated_at": now,
        "created_by": None,
        "metadata": {},
    }
    data.update(overrides)
    return WorkflowTestCaseResponse(**data)


def result(**overrides) -> WorkflowExecuteResponse:
    data = {
        "workflow_id": "wf",
        "response": "The answer is 60.",
        "execution_time_ms": 5,
        "agents_called": ["TriageAgent", "CalculatorAgent"],
        "tools_called": ["calculate"],
        "success": True,
        "metadata": {
            "agent_ids_called": ["triage_agent", "calculator_agent"],
            "manager_agent_id": "triage_agent",
        },
    }
    data.update(overrides)
    return WorkflowExecuteResponse(**data)


def test_judge_passes_when_every_expectation_holds() -> None:
    assert (
        judge(
            case(
                expected_agent="calculator_agent",
                expected_tools=["calculate"],
                expected_output_contains=["60"],
                expected_output_pattern=r"answer is \d+",
            ),
            result(),
        )
        == []
    )


def test_judge_names_each_unmet_expectation() -> None:
    failures = judge(
        case(
            expected_agent="search_assistant",
            expected_tools=["web_search"],
            expected_output_contains=["Berlin"],
            expected_output_pattern=r"^\d+$",
        ),
        result(),
    )
    assert len(failures) == 4
    assert "search_assistant" in failures[0]
    assert "web_search" in failures[1]


def test_judge_reports_a_bad_regex_instead_of_crashing() -> None:
    assert "not a valid regex" in judge(case(expected_output_pattern="("), result())[0]


def test_responding_agent_is_the_specialist_not_the_manager() -> None:
    assert responding_agent(result()) == "calculator_agent"
    solo = result(metadata={"agent_ids_called": ["general_assistant"]})
    assert responding_agent(solo) == "general_assistant"


async def test_disabled_case_is_skipped(monkeypatch) -> None:
    from src.core.workflow_test_runner import WorkflowTestRunner

    runner = WorkflowTestRunner(session_manager=SimpleNamespace())
    _, verdict, message = await runner.run_test_case(case(enabled=False))
    assert verdict is TestStatus.SKIPPED
    assert message


# --- The user's words are data, not template text ---------------------------------------


@pytest.mark.parametrize(
    "message", ["Fill in: Hello {name}!", "{request}", "{message} {session_id}"]
)
def test_braces_in_a_message_cannot_break_or_steer_a_run(message: str) -> None:
    from crewai.utilities.string_utils import interpolate_only

    from src.crewai_runtime.runtime import CrewAIWorkflowRuntime as Runtime

    description = Runtime._task_description("Answer the question.", final=True)
    inputs = {
        "message": message,
        "session_id": "s-1",
        "request": Runtime._request_text(message, {}),
    }
    rendered = interpolate_only(description, inputs)
    assert rendered.endswith(message), "the message must arrive verbatim"
    assert "s-1" not in rendered


def test_earlier_turns_reach_the_model_once() -> None:
    from src.crewai_runtime.runtime import CrewAIWorkflowRuntime as Runtime

    history = [
        {"role": "user", "content": "My name is Rafi."},
        {"role": "assistant", "content": "Hello Rafi."},
        {"role": "user", "content": "What is my name?"},
    ]
    text = Runtime._request_text("What is my name?", {"history": history})
    assert "user: My name is Rafi." in text
    assert text.count("What is my name?") == 1


def test_step_text_carries_no_session_identifiers_or_boilerplate() -> None:
    from src.crewai_runtime.runtime import CrewAIWorkflowRuntime as Runtime

    text = Runtime._task_description("Outline the piece.", final=False)
    for leaked in ("Session Trace", "Identity Context", "Runtime Parameters", "exhaustive"):
        assert leaked not in text


# --- An agent is its instructions ---------------------------------------------------------


@pytest.mark.parametrize("system_message", [None, "", "   ", "You are a helpful AI assistant."])
def test_agents_without_real_instructions_are_refused(client: TestClient, system_message) -> None:
    body = {"id": "probe_no_instructions", "type": "conversable", "name": "Probe"}
    if system_message is not None:
        body["system_message"] = system_message
    response = client.post("/api/v1/agents", json=body)
    assert response.status_code == 422, response.text
    assert "instructions" in response.text
    assert client.get("/api/v1/agents/probe_no_instructions").status_code == 404


# --- Run admission per workflow, and the status that reports it --------------------------


async def test_runs_beyond_the_limit_wait_and_are_counted() -> None:
    import asyncio

    from src.api.session_manager import SessionManager

    manager = SessionManager.__new__(SessionManager)
    manager.max_concurrent_runs = 2
    manager._run_slots, manager._active_runs, manager._waiting_runs = {}, {}, {}

    release = asyncio.Event()

    async def run() -> None:
        async with manager._run_slot("wf"):
            await release.wait()

    tasks = [asyncio.create_task(run()) for _ in range(3)]
    await asyncio.sleep(0.01)
    assert manager.run_status("wf") == {"active": 2, "waiting": 1, "max_concurrent": 2}
    assert manager.run_status("other") == {"active": 0, "waiting": 0, "max_concurrent": 2}

    release.set()
    await asyncio.gather(*tasks)
    assert manager.run_status("wf") == {"active": 0, "waiting": 0, "max_concurrent": 2}


async def test_a_cancelled_waiter_does_not_leak_a_count() -> None:
    import asyncio

    from src.api.session_manager import SessionManager

    manager = SessionManager.__new__(SessionManager)
    manager.max_concurrent_runs = 1
    manager._run_slots, manager._active_runs, manager._waiting_runs = {}, {}, {}
    hold = asyncio.Event()

    async def run() -> None:
        async with manager._run_slot("wf"):
            await hold.wait()

    first = asyncio.create_task(run())
    await asyncio.sleep(0.01)
    second = asyncio.create_task(run())
    await asyncio.sleep(0.01)
    second.cancel()
    await asyncio.gather(second, return_exceptions=True)
    assert manager.run_status("wf")["waiting"] == 0
    hold.set()
    await first
    assert manager.run_status("wf")["active"] == 0


def test_topology_status_endpoint_reports_real_counts(client: TestClient) -> None:
    response = client.get("/api/v1/topologies/assistant_chat/status")
    assert response.status_code == 200, "it read an execution engine that no longer exists"
    body = response.json()
    assert body["active_executions"] == 0
    assert body["queued_requests"] == 0
    assert body["max_concurrent"] >= 1
    assert body["resource_limit_reached"] is False


# --- One config location, seeded without overwriting edits -------------------------------


def test_config_dir_follows_the_environment(monkeypatch, tmp_path) -> None:
    from src.config.paths import config_dir, config_path

    monkeypatch.setenv("DELAXIS_CONFIG_DIR", str(tmp_path / "cfg"))
    assert config_dir() == tmp_path / "cfg"
    assert config_path("workflows.json") == tmp_path / "cfg" / "workflows.json"


def test_seeding_fills_gaps_and_never_overwrites_edits(monkeypatch, tmp_path) -> None:
    from src.config.paths import seed_config_dir

    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "agents.json").write_text('{"shipped": true}')
    (bundled / "tools.json").write_text('{"shipped": true}')
    target = tmp_path / "volume"
    target.mkdir()
    (target / "agents.json").write_text('{"edited": true}')
    monkeypatch.setenv("DELAXIS_CONFIG_DIR", str(target))

    assert seed_config_dir(bundled) == ["tools.json"]
    assert (target / "agents.json").read_text() == '{"edited": true}'
    assert (target / "tools.json").read_text() == '{"shipped": true}'
    assert seed_config_dir(bundled) == [], "a second boot copies nothing"


def test_the_api_reads_and_writes_the_configured_directory(monkeypatch, tmp_path) -> None:
    """A Studio save must land in DELAXIS_CONFIG_DIR, not in the image's copy."""
    import shutil

    from src.api.routers import workflows as workflows_router

    target = tmp_path / "cfg"
    shutil.copytree(ROOT / "configs", target)
    monkeypatch.setenv("DELAXIS_CONFIG_DIR", str(target))
    assert workflows_router._get_workflows_config_path() == target / "workflows.json"


# --- Crew memory survives an embedder change -----------------------------------------------


def _memory_table(memory_dir: Path, dimensions: int) -> None:
    import lancedb
    import pyarrow as pa

    schema = pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimensions)),
        ]
    )
    lancedb.connect(str(memory_dir)).create_table("memories", schema=schema)


def test_a_store_written_by_another_embedder_is_moved_aside(tmp_path) -> None:
    from src.crewai_runtime import memory_store

    memory_store.reset_for_tests()
    memory_dir = tmp_path / "memory"
    _memory_table(memory_dir, 1536)
    assert memory_store.stored_vector_dim(memory_dir) == 1536

    retired = memory_store.retire_mismatched_store(tmp_path, 512)
    assert retired is not None and retired.exists(), "moved, never deleted"
    assert "1536d" in retired.name
    assert not (memory_dir / memory_store.TABLE_DIR).exists()


def test_a_matching_store_is_left_alone(tmp_path) -> None:
    from src.crewai_runtime import memory_store

    memory_store.reset_for_tests()
    _memory_table(tmp_path / "memory", 512)
    assert memory_store.retire_mismatched_store(tmp_path, 512) is None
    assert (tmp_path / "memory" / memory_store.TABLE_DIR).exists()


def test_no_store_means_nothing_to_do(tmp_path) -> None:
    from src.crewai_runtime import memory_store

    memory_store.reset_for_tests()
    assert memory_store.retire_mismatched_store(tmp_path, 512) is None


def test_run_memory_uses_the_workflow_model_and_the_local_embedder(monkeypatch, tmp_path) -> None:
    from src.config.workflow_registry import get_workflow_registry
    from src.crewai_runtime import memory_store
    from src.crewai_runtime.runtime import CrewAIWorkflowRuntime
    from src.rag.service import get_rag_service

    memory_store.reset_for_tests()
    monkeypatch.setenv("CREWAI_STORAGE_DIR", str(tmp_path))
    runtime = CrewAIWorkflowRuntime(memory_enabled=True, storage_dir=str(tmp_path))
    monkeypatch.setattr(runtime, "_resolve_llm_model", lambda config: f"llm:{config.get('model')}")
    workflow = get_workflow_registry().get_workflow("assistant_chat")
    from src.config.loader import load_agents_config

    agents = {agent.id: agent for agent in load_agents_config().agents}
    memory = runtime._build_memory(workflow, agents, ["general_assistant"])
    assert memory.llm == f"llm:{agents['general_assistant'].llm_config.model}"
    assert memory.root_scope == "/crew/assistant_chat"
    # The local embedder, not CrewAI's OpenAI default.
    assert memory.embedder is not None
    assert get_rag_service().embedder.dimensions == 512


# --- POST /topologies stores what it validates ---------------------------------------------


def _topology_body(workflow_id: str, agent_id: str = "general_assistant") -> dict:
    return {
        "workflow_id": workflow_id,
        "type": "single",
        "nodes": [{"id": "only", "agent_id": agent_id}],
        "edges": [],
        "entry_node": "only",
    }


def test_creating_a_topology_saves_it_on_the_workflow(monkeypatch, tmp_path) -> None:
    import shutil

    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.config.config_loader import get_config_loader
    from src.config.workflow_registry import get_workflow_registry

    target = tmp_path / "cfg"
    shutil.copytree(ROOT / "configs", target)
    monkeypatch.setenv("DELAXIS_CONFIG_DIR", str(target))
    loader = get_config_loader()
    monkeypatch.setattr(loader, "config_dir", target)
    loader.reload_all()
    registry = get_workflow_registry()
    monkeypatch.setattr(registry, "config_path", target / "workflows.json")
    try:
        client = TestClient(app)
        response = client.post("/api/v1/topologies", json=_topology_body("assistant_chat"))
        assert response.status_code == 201, response.text
        saved = json.loads((target / "workflows.json").read_text())
        workflow = next(w for w in saved["workflows"] if w["id"] == "assistant_chat")
        assert workflow["topology"]["entry_node"] == "only"
        assert registry.get_workflow("assistant_chat").topology.entry_node == "only"

        assert (
            client.post("/api/v1/topologies", json=_topology_body("no_such_flow")).status_code
            == 404
        )
        missing_agent = client.post(
            "/api/v1/topologies", json=_topology_body("assistant_chat", "ghost")
        )
        assert missing_agent.status_code == 422
    finally:
        monkeypatch.undo()
        get_config_loader().reload_all()
        get_workflow_registry().reload()


def test_runtime_overrides_are_applied_not_ignored() -> None:
    from src.config.config_manager import ConfigurationError, ConfigurationManager

    manager = ConfigurationManager(ROOT / "configs")
    base = manager.get_effective_config()
    overridden = manager.get_effective_config(
        runtime_overrides={"execution": {"max_workers": base.execution.max_workers + 3}}
    )
    assert overridden.execution.max_workers == base.execution.max_workers + 3
    assert overridden.cache == base.cache

    with pytest.raises(ConfigurationError, match="Unsupported runtime override"):
        manager.get_effective_config(runtime_overrides={"agents": {}})
    with pytest.raises(ConfigurationError, match="Invalid runtime override"):
        manager.get_effective_config(runtime_overrides={"execution": {"max_workers": 0}})


def test_the_api_reports_the_package_version(client: TestClient) -> None:
    from importlib.metadata import version

    expected = version("delaxis")
    assert client.get("/openapi.json").json()["info"]["version"] == expected
    assert client.get("/api/v1/health/ready").json()["version"] == expected


def test_app_shutdown_does_not_wait_on_an_absent_collector(monkeypatch) -> None:
    """FastAPI 0.142 built OTLP exporters from OTEL_* variables and, with no
    collector listening, waited out a 15-second flush on every shutdown."""
    import time

    from src.api.app_factory import create_app

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9")
    started = time.perf_counter()
    with TestClient(create_app()) as fresh:
        fresh.get("/health")
    assert time.perf_counter() - started < 5


# --- Provider prefixes reach vendors CrewAI cannot call natively -------------------------


@pytest.mark.parametrize(
    ("model", "provider"),
    [
        ("groq/llama-3.3-70b-versatile", "groq"),
        ("mistral/mistral-large-latest", "mistral"),
        ("xai/grok-4", "grok"),
        ("gemini/gemini-2.5-pro", "gemini"),
    ],
)
def test_direct_prefixes_route_through_the_registry(monkeypatch, model, provider) -> None:
    from src.crewai_runtime.runtime import CrewAIWorkflowRuntime

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    runtime = CrewAIWorkflowRuntime(memory_enabled=False, storage_dir="./.crewai-test")
    seen: dict = {}

    def registry(provider_id, name, config):
        seen.update(provider=provider_id, name=name)
        return "llm"

    monkeypatch.setattr(runtime, "_resolve_registered_provider", registry)
    assert runtime._resolve_llm_model({"model": model}) == "llm"
    assert seen == {"provider": provider, "name": model.split("/", 1)[1]}


def test_openrouter_mode_keeps_vendor_ids_as_openrouter_models(monkeypatch) -> None:
    from src.crewai_runtime.runtime import CrewAIWorkflowRuntime

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    runtime = CrewAIWorkflowRuntime(memory_enabled=False, storage_dir="./.crewai-test")
    assert runtime._resolve_llm_model({"model": "openai/gpt-4o"}) == "openrouter/openai/gpt-4o"
    assert runtime._resolve_llm_model({"model": "xai/grok-4"}) == "openrouter/xai/grok-4"
