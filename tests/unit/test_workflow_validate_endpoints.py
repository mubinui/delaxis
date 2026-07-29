"""HTTP-level tests for the workflow/topology validation endpoints.

Both endpoints were broken and nobody noticed because neither had a test:
- POST /workflows/{id}/validate fed a bare str into List[WorkflowValidationError],
  so every invalid workflow raised inside Pydantic and surfaced as a 500.
- POST /topologies/validate always 500'd because its WorkflowGraph stub returned
  a bool while the caller read .is_valid.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import topologies as topologies_router
from src.api.routers import workflows as workflows_router
from src.api.workflow_diagnostics import diagnose_graph, structural_checks_applicable


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(workflows_router.router)
    app.include_router(topologies_router.router)
    return TestClient(app)


class TestWorkflowValidate:
    def test_invalid_workflow_returns_structured_errors_not_500(self, client):
        response = client.post("/api/v1/workflows/definitely_not_a_workflow/validate")
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert body["errors"], "expected at least one structured error"
        assert set(body["errors"][0]) >= {"field", "message", "error_type"}

    def test_valid_workflow_passes(self, client):
        response = client.post("/api/v1/workflows/demo_multi_agent/validate")
        assert response.status_code == 200
        assert response.json()["valid"] is True


class TestTopologyValidate:
    def _payload(self, edges):
        return {
            "workflow_id": "demo",
            "type": "graph",
            "entry_node": "a",
            "nodes": [
                {"id": "a", "agent_id": "general_assistant"},
                {"id": "b", "agent_id": "calculator_agent"},
            ],
            "edges": edges,
        }

    def test_edgeless_topology_is_valid_with_a_warning(self, client):
        """Selector-style workflows have no edges; treating that as unreachable
        nodes would flag most of the shipped workflows as broken."""
        response = client.post("/api/v1/topologies/validate", json=self._payload([]))
        assert response.status_code == 200
        body = response.json()
        assert body["is_valid"] is True
        assert body["errors"] == []
        assert any("no explicit edges" in w.lower() for w in body["warnings"])

    def test_endpoint_does_not_500(self, client):
        response = client.post(
            "/api/v1/topologies/validate",
            json=self._payload([{"from_node": "a", "to_node": "b", "context_strategy": "full"}]),
        )
        assert response.status_code == 200


class TestStructuralApplicability:
    def test_edgeless_skips_structural_rules(self):
        assert structural_checks_applicable({"edges": []}) is False

    def test_llm_routing_skips_structural_rules(self):
        assert structural_checks_applicable(
            {"edges": [{"from_node": "a", "to_node": "b"}], "routing_method": "llm"}
        ) is False

    def test_domain_agents_skip_structural_rules(self):
        assert structural_checks_applicable(
            {"edges": [{"from_node": "a", "to_node": "b"}], "domain_agents": [{"id": "x"}]}
        ) is False

    def test_plain_edge_graph_is_checked(self):
        assert structural_checks_applicable({"edges": [{"from_node": "a", "to_node": "b"}]}) is True


class TestValidateGraphEndpoint:
    """The canvas needs to check work that has not been saved yet."""

    def test_empty_graph(self, client):
        body = client.post("/api/v1/workflows/validate-graph", json={"nodes": [], "connections": []}).json()
        assert body["valid"] is False
        assert body["diagnostics"][0]["code"] == "workflow_empty"

    def test_node_without_an_agent(self, client):
        body = client.post(
            "/api/v1/workflows/validate-graph",
            json={"nodes": [{"id": "n1"}], "connections": []},
        ).json()
        codes = {d["code"] for d in body["diagnostics"]}
        assert "agent_not_assigned" in codes
        assert body["valid"] is False

    def test_unknown_agent_is_reported_with_suggestions(self, client):
        body = client.post(
            "/api/v1/workflows/validate-graph",
            json={"nodes": [{"id": "n1", "agent_id": "no_such_agent"}], "connections": []},
        ).json()
        finding = next(d for d in body["diagnostics"] if d["code"] == "agent_missing")
        assert finding["node_id"] == "n1"
        assert finding["suggestions"], "expected 'did you mean' candidates"

    def test_dangling_connection(self, client):
        body = client.post(
            "/api/v1/workflows/validate-graph",
            json={
                "nodes": [{"id": "n1", "agent_id": "general_assistant"}],
                "connections": [{"from_node": "n1", "to_node": "ghost", "type": "sequential"}],
            },
        ).json()
        assert "missing_node" in {d["code"] for d in body["diagnostics"]}

    def test_entry_node_must_exist(self, client):
        body = client.post(
            "/api/v1/workflows/validate-graph",
            json={
                "nodes": [{"id": "n1", "agent_id": "general_assistant"}],
                "connections": [],
                "entry_node": "nope",
            },
        ).json()
        assert "entry_node_missing" in {d["code"] for d in body["diagnostics"]}


class TestConfigurationChecks:
    """The checks configs/README.md already tells users to run by hand."""

    PROVIDERS = [
        {
            "id": "configured",
            "type": "llm",
            "enabled": True,
            "base_url": "https://x.example/v1",
            "models": [{"name": "known-model"}],
            "auth": {"scheme": "bearer", "env_var": "TEST_KEY", "required": True},
        }
    ]

    def _agent(self, **llm):
        return [{"id": "a1", "tools": [], "llm_config": {"provider_id": "configured", **llm}}]

    def test_unknown_provider(self):
        findings = diagnose_graph(
            [{"id": "n1", "agent_id": "a1"}], [],
            agents=[{"id": "a1", "llm_config": {"provider_id": "ghost", "model": "m"}}],
            providers=self.PROVIDERS,
        )
        assert "provider_missing" in {f.code for f in findings}

    def test_missing_api_key(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OAK_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("TEST_KEY", raising=False)
        findings = diagnose_graph(
            [{"id": "n1", "agent_id": "a1"}], [],
            agents=self._agent(model="known-model"),
            providers=self.PROVIDERS,
        )
        key_finding = next(f for f in findings if f.code == "provider_key_missing")
        assert "TEST_KEY" in key_finding.message

    def test_unknown_model_is_a_warning_not_an_error(self, monkeypatch, tmp_path):
        """Free-text model ids are legal — the list is only a hint."""
        monkeypatch.setenv("OAK_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("TEST_KEY", "sk-test")
        findings = diagnose_graph(
            [{"id": "n1", "agent_id": "a1"}], [],
            agents=self._agent(model="some-new-model"),
            providers=self.PROVIDERS,
        )
        finding = next(f for f in findings if f.code == "model_unknown_for_provider")
        assert finding.severity == "warning"
        assert "known-model" in finding.suggestions

    def test_disabled_tool_still_referenced(self):
        findings = diagnose_graph(
            [{"id": "n1", "agent_id": "a1"}], [],
            agents=[{"id": "a1", "tools": ["t1"]}],
            tools=[{"id": "t1", "enabled": False}],
            providers=[],
        )
        assert "tool_disabled_but_referenced" in {f.code for f in findings}

    def test_missing_tool(self):
        findings = diagnose_graph(
            [{"id": "n1", "agent_id": "a1"}], [],
            agents=[{"id": "a1", "tools": ["ghost_tool"]}],
            tools=[{"id": "t1"}],
            providers=[],
        )
        assert "tool_missing" in {f.code for f in findings}

    def test_unimportable_entrypoint(self):
        findings = diagnose_graph(
            [{"id": "n1", "agent_id": "a1"}], [],
            agents=[{"id": "a1", "tools": ["t1"]}],
            tools=[{"id": "t1", "entrypoint": "no.such.module:fn"}],
            providers=[],
        )
        assert "tool_entrypoint_unimportable" in {f.code for f in findings}

    def test_importable_entrypoint_is_clean(self):
        findings = diagnose_graph(
            [{"id": "n1", "agent_id": "a1"}], [],
            agents=[{"id": "a1", "tools": ["t1"]}],
            tools=[{"id": "t1", "entrypoint": "json:dumps"}],
            providers=[],
        )
        assert "tool_entrypoint_unimportable" not in {f.code for f in findings}

    def test_user_modules_are_not_imported_by_default(self, tmp_path, monkeypatch):
        """Validation must not execute user code implicitly."""
        module = tmp_path / "boom_module.py"
        module.write_text("raise RuntimeError('imported!')\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        findings = diagnose_graph(
            [{"id": "n1", "agent_id": "a1"}], [],
            agents=[{"id": "a1", "tools": ["t1"]}],
            tools=[{"id": "t1", "entrypoint": "boom_module:fn"}],
            providers=[],
        )
        # find_spec locates it without executing, so no import error is raised
        assert "tool_entrypoint_unimportable" not in {f.code for f in findings}
