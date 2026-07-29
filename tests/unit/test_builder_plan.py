"""The builder's plan has to survive apply, or the Studio ends up with nothing."""

import pytest

from src.api.routers.builder import _normalize_plan


def normalize(plan: dict, prompt: str = "a support chatbot"):
    return _normalize_plan(plan, prompt)


class TestPlanRepair:
    def test_topology_node_pointing_at_a_nonexistent_agent_is_dropped(self):
        plan = normalize({
            "agents": [{"id": "helper", "name": "Helper"}],
            "workflow": {"topology": {"nodes": [{"id": "ghost", "agent_id": "not_defined"}], "entry_node": "ghost"}},
        })
        node_agents = {n["agent_id"] for n in plan["workflow"]["topology"]["nodes"]}
        assert node_agents == {"helper"}

    def test_every_agent_gets_a_topology_node(self):
        plan = normalize({
            "agents": [{"id": "one"}, {"id": "two"}],
            "workflow": {"topology": {"nodes": [{"id": "one", "agent_id": "one"}], "entry_node": "one"}},
        })
        assert {n["id"] for n in plan["workflow"]["topology"]["nodes"]} == {"one", "two"}

    def test_an_unregistered_tool_is_removed_rather_than_left_dangling(self):
        plan = normalize({"agents": [{"id": "helper", "tools": ["web_search", "invented_tool"]}]})
        assert plan["agents"][0]["tools"] == ["web_search"]

    def test_a_tool_the_plan_defines_itself_is_kept(self):
        plan = normalize({
            "agents": [{"id": "helper", "tools": ["my_api"]}],
            "tools": [{"id": "my_api", "name": "my_api"}],
        })
        assert plan["agents"][0]["tools"] == ["my_api"]

    def test_agent_tools_are_mirrored_onto_the_topology_node(self):
        plan = normalize({"agents": [{"id": "helper", "tools": ["web_search"]}]})
        node = plan["workflow"]["topology"]["nodes"][0]
        assert node["tools"] == ["web_search"]

    def test_ids_are_slugified_and_deduplicated(self):
        plan = normalize({"agents": [{"name": "My Agent!"}, {"name": "My Agent!"}]})
        ids = [a["id"] for a in plan["agents"]]
        assert ids[0] == "my_agent"
        assert len(set(ids)) == 2

    def test_a_missing_entry_node_falls_back_to_the_first_node(self):
        plan = normalize({"agents": [{"id": "one"}, {"id": "two"}], "workflow": {"topology": {"nodes": []}}})
        topology = plan["workflow"]["topology"]
        assert topology["entry_node"] in {n["id"] for n in topology["nodes"]}

    def test_an_entirely_empty_plan_still_produces_something_applyable(self):
        plan = normalize({})
        assert plan["agents"]
        assert plan["workflow"]["topology"]["nodes"]
        assert plan["workflow"]["topology"]["entry_node"]
        assert plan["workflow"]["id"]

    def test_a_chatbot_gets_memory_so_turns_are_not_cold(self):
        assert normalize({"agents": [{"id": "helper"}]})["workflow"]["memory"]["enabled"] is True

    def test_a_single_agent_plan_is_marked_single(self):
        plan = normalize({"agents": [{"id": "helper"}]})
        assert plan["workflow"]["pattern"] == "single"
        assert plan["workflow"]["topology"]["type"] == "single"


class TestPatternCoercion:
    """A pattern outside ConversationPattern makes workflow creation 422, which
    is one of the ways a generated plan ended up creating nothing at all."""

    def test_known_patterns_pass_through(self):
        from src.api.routers.builder import _coerce_pattern

        for value in ("single", "sequential", "selector", "parallel"):
            assert _coerce_pattern(value, 2) == value

    def test_common_model_wording_is_mapped(self):
        from src.api.routers.builder import _coerce_pattern

        assert _coerce_pattern("conversational", 1) == "single"
        assert _coerce_pattern("Pipeline", 3) == "sequential"
        assert _coerce_pattern("routing", 3) == "selector"
        assert _coerce_pattern("graph", 3) == "selector"

    def test_nonsense_falls_back_to_the_shape_of_the_graph(self):
        from src.api.routers.builder import _coerce_pattern

        assert _coerce_pattern("wibble", 1) == "single"
        assert _coerce_pattern(None, 4) == "sequential"

    def test_a_coerced_plan_passes_workflow_validation(self):
        from src.api.models import WorkflowCreateRequest

        plan = normalize({"agents": [{"id": "a"}], "workflow": {"pattern": "conversational"}})
        WorkflowCreateRequest(**plan["workflow"])  # must not raise


class TestApplyIsIdempotent:
    """Re-applying a plan used to fail on "already exists" and leave the Studio
    with nothing to show."""

    @pytest.fixture
    def client(self):
        """Applying writes to the real configs, so anything created here is
        removed again — otherwise the next run sees it and never 'creates'."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.api.routers import agents as agents_router
        from src.api.routers import builder as builder_router
        from src.api.routers import functions as functions_router
        from src.api.routers import tools as tools_router
        from src.api.routers import workflows as workflows_router

        app = FastAPI()
        for module in (builder_router, agents_router, tools_router, workflows_router, functions_router):
            app.include_router(module.router)
        test_client = TestClient(app)
        yield test_client
        for workflow in test_client.get("/api/v1/workflows").json():
            if str(workflow["id"]).startswith("idem_wf_"):
                test_client.delete(f"/api/v1/workflows/{workflow['id']}")
        for agent in test_client.get("/api/v1/agents").json():
            if str(agent["id"]).startswith("idem_agent_"):
                test_client.delete(f"/api/v1/agents/{agent['id']}")

    def _plan(self, suffix: str) -> dict:
        return {
            "agents": [{
                "id": f"idem_agent_{suffix}",
                "type": "conversable",
                "name": f"IdemAgent{suffix}",
                "instruction": "Be helpful.",
                "tools": ["web_search"],
            }],
            "workflow": {
                "id": f"idem_wf_{suffix}",
                "name": "Idem",
                "description": "idempotency check",
                "pattern": "single",
                "topology": {
                    "type": "single",
                    "entry_node": "n1",
                    "nodes": [{"id": "n1", "agent_id": f"idem_agent_{suffix}", "tools": ["web_search"]}],
                    "edges": [],
                },
            },
        }

    def test_applying_twice_reports_updates_not_errors(self, client):
        plan = self._plan("twice")
        first = client.post("/api/v1/builder/apply", json={"plan": plan}).json()
        assert first["errors"] == []
        assert first["created"]["workflows"] == ["idem_wf_twice"]

        second = client.post("/api/v1/builder/apply", json={"plan": plan}).json()
        assert second["errors"] == []
        assert second["created"]["workflows"] == []
        assert second["updated"]["agents"] == ["idem_agent_twice"]
        assert second["updated"]["workflows"] == ["idem_wf_twice"]

    def test_the_workflow_comes_back_so_the_studio_can_draw_it(self, client):
        result = client.post("/api/v1/builder/apply", json={"plan": self._plan("canvas")}).json()
        workflow = result["workflow"]
        assert workflow is not None
        assert workflow["id"] == "idem_wf_canvas"
        # The tools the plan attached survive, so the canvas can draw them
        assert workflow["topology"]["nodes"][0]["tools"] == ["web_search"]

    def test_a_plan_missing_derived_fields_still_applies(self, client):
        """Plans arrive hand-edited or from older sessions; a missing
        entry_agent_id must not fail the whole apply."""
        plan = self._plan("derived")
        plan["workflow"].pop("pattern")
        result = client.post("/api/v1/builder/apply", json={"plan": plan}).json()
        assert result["errors"] == []
        assert result["workflow"] is not None
