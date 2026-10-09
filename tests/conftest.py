"""Shared fixtures for the API-level tests.

`async_client` talks to the real application in-process. `fake_runtime`
replaces only the LLM-backed CrewAI kickoff with a deterministic stand-in, so a
test exercises routing, sessions, persistence, validation and test-case judging
exactly as production runs them, without a provider key or network access.
`fixture_workflows` adds three small workflows the endpoint tests are written
against, and removes them again afterwards.
"""

from __future__ import annotations

import asyncio
import copy
import os
import tempfile
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

# The suite must never depend on a Redis being up, whatever the developer's .env says.
os.environ["REDIS_URL"] = ""
# Nor on an OpenTelemetry collector: FastAPI builds exporters from OTEL_*
# variables (a developer's .env may set them) and every app shutdown then waits
# out a flush to a collector that is not there.
for _signal in ("TRACES", "METRICS", "LOGS"):
    os.environ[f"OTEL_{_signal}_EXPORTER"] = "none"
# Nor write to the developer's database: runs are recorded on every message.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="delaxis-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DATA_DIR}/delaxis.db"


@pytest.fixture(scope="session", autouse=True)
def _test_database() -> Iterator[None]:
    """Create every table in the suite's own SQLite database."""
    from src.infrastructure.database.connection import get_db_manager
    from src.infrastructure.database.schema import Base

    Base.metadata.create_all(get_db_manager().engine)
    yield


@pytest.fixture
async def async_client() -> AsyncIterator[Any]:
    """An httpx client bound to the app, with an admin user for authenticated routes.

    Every client starts with a fresh rate-limit budget: all tests share one
    client address, so otherwise a test's 429s depend on what ran before it.
    """
    from httpx import ASGITransport, AsyncClient

    from src.api.auth import CurrentUser, UserRole, get_current_user
    from src.api.main import app
    from src.api.rate_limiting import rate_limiting_middleware

    rate_limiting_middleware._rate_limit_store.clear()

    admin = CurrentUser(
        user_id=UUID("00000000-0000-0000-0000-0000000000ad"),
        username="test-admin",
        role=UserRole.ADMIN,
        auth_method="jwt",
    )
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def mock_auth_token() -> str:
    """A correctly signed, unexpired access token for the test admin."""
    from src.api.auth import create_access_token

    return create_access_token(
        {
            "sub": "00000000-0000-0000-0000-0000000000ad",
            "username": "test-admin",
            "role": "admin",
        }
    )


def _single(workflow_id: str, agent_id: str, *, enabled: bool = True) -> dict[str, Any]:
    return {
        "id": workflow_id,
        "name": workflow_id.replace("_", " ").title(),
        "description": f"Test fixture workflow {workflow_id}",
        "pattern": "single",
        "enabled": enabled,
        "entry_agent_id": agent_id,
        "topology": {
            "type": "single",
            "entry_node": agent_id,
            "nodes": [{"id": agent_id, "agent_id": agent_id}],
            "edges": [],
        },
    }


FIXTURE_WORKFLOWS: list[dict[str, Any]] = [
    _single("echo_test", "general_assistant"),
    _single("tool_test", "search_assistant"),
    {
        **_single("pipeline_example", "content_outliner", enabled=False),
        "pattern": "sequential",
    },
]


@pytest.fixture
def fixture_workflows(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Register the fixture workflows with every reader of the workflow config."""
    from src.api.routers import workflows as workflows_router
    from src.config.workflow_models import WorkflowConfig
    from src.config.workflow_registry import get_workflow_registry

    registry = get_workflow_registry()
    added = [WorkflowConfig.model_validate(data) for data in FIXTURE_WORKFLOWS]
    original = list(registry._workflows_config.workflows)
    registry._workflows_config.workflows = original + added

    real_load = workflows_router._load_workflows_config

    def load_with_fixtures() -> dict:
        config = copy.deepcopy(real_load())
        known = {w["id"] for w in config.get("workflows", [])}
        config["workflows"] = config.get("workflows", []) + [
            w for w in FIXTURE_WORKFLOWS if w["id"] not in known
        ]
        return config

    monkeypatch.setattr(workflows_router, "_load_workflows_config", load_with_fixtures)
    try:
        yield [w["id"] for w in FIXTURE_WORKFLOWS]
    finally:
        registry._workflows_config.workflows = original


@pytest.fixture
def fake_runtime(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace the CrewAI kickoff with a deterministic echo; returns the call log.

    Every agent in the topology "runs", and a tool is "called" only when the
    message asks for it and the agent actually has that tool, mirroring what the
    real runtime reports.
    """
    from src.config.loader import load_agents_config
    from src.crewai_runtime.runtime import CrewAIRuntimeResult, CrewAIWorkflowRuntime

    calls: list[dict[str, Any]] = []
    agents = {agent.id: agent for agent in load_agents_config().agents}

    async def run_message(
        self: Any,
        workflow: Any,
        message: str,
        session_id: str,
        user_id: str,
        metadata: dict[str, Any] | None = None,
        event_sink: Any = None,
    ) -> CrewAIRuntimeResult:
        await asyncio.sleep(0.005)  # a real run takes time; zero would hide bugs
        agent_ids = [node.agent_id for node in workflow.topology.nodes]
        tools = [
            tool
            for agent_id in agent_ids
            for tool in (agents[agent_id].tools if agent_id in agents else [])
            if tool.split("_")[-1] in message.lower()
        ]
        calls.append({"workflow_id": workflow.id, "message": message, "session_id": session_id})
        return CrewAIRuntimeResult(
            response=f"Echo: {message}",
            # Same shape as the real runtime's planning/completion trace steps.
            trace_steps=[
                {
                    "type": "crew_done",
                    "agent": "CrewAI",
                    "description": f"Completed workflow {workflow.id}",
                    "timestamp": time.time(),
                    "details": {"fake": True},
                }
            ],
            metadata={
                "runtime": "crewai",
                "workflow_id": workflow.id,
                "agents_called": [
                    agents[agent_id].name if agent_id in agents else agent_id
                    for agent_id in agent_ids
                ],
                "agent_ids_called": agent_ids,
                "tools_called": tools,
            },
        )

    monkeypatch.setattr(CrewAIWorkflowRuntime, "run_message", run_message)
    return calls


# --- The shipped configs are read-only for the whole suite -------------------------------

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


def _config_snapshot() -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(CONFIG_DIR.glob("*.json"))}


@pytest.fixture(autouse=True)
def shipped_configs_are_not_modified() -> Iterator[None]:
    """Fail the test that writes to configs/*.json, and put the files back.

    Tests that need a config file to write to must point the code at a copy
    (see the prompts tests). Otherwise a fixture or a saved test case can end up
    committed as if it were a shipped workflow.
    """
    before = _config_snapshot()
    yield
    after = _config_snapshot()
    changed = sorted(name for name in before if before[name] != after.get(name))
    added = sorted(set(after) - set(before))
    if changed or added:
        import difflib

        excerpt = ""
        for name in changed[:1]:
            diff = difflib.unified_diff(
                before[name].decode(errors="replace").splitlines(),
                after[name].decode(errors="replace").splitlines(),
                lineterm="",
                n=1,
            )
            excerpt = "\n".join(list(diff)[:40])
        for name, content in before.items():
            (CONFIG_DIR / name).write_bytes(content)
        for name in added:
            (CONFIG_DIR / name).unlink()
        pytest.fail(
            f"this test wrote to the shipped configs (changed: {changed}, added: {added}); "
            f"point the code at a temporary copy instead\n{excerpt}"
        )
