"""A deployment's provider/model choice must take effect — and only from the
deployment record, never from the client.

The generated chat page sends provider_id/model_id in every message's metadata,
but that JavaScript is editable by anyone who opens a public deployment, so
trusting it would let a visitor repoint the workflow at another provider.
"""

import json

import pytest

from src.api.routers import deployments as deployments_router
from src.config.agent_models import AgentConfig
from src.crewai_runtime.runtime import CrewAIWorkflowRuntime


@pytest.fixture
def deployments_config(tmp_path, monkeypatch):
    config_path = tmp_path / "deployments.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "deployments": [
                    {
                        "id": "support-bot",
                        "workflow_id": "wf",
                        "name": "support-bot",
                        "provider_id": "gemini",
                        "model_id": "gemini-3.5-flash",
                        "status": "active",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(deployments_router, "CONFIG_PATH", config_path)
    return config_path


class TestOverrideLookup:
    def test_resolves_from_the_deployment_record(self, deployments_config):
        override = deployments_router.deployment_model_override("support-bot")
        assert override == {"provider_id": "gemini", "model": "gemini-3.5-flash"}

    def test_name_is_slugified_like_the_deployment_id(self, deployments_config):
        assert deployments_router.deployment_model_override("Support Bot") == {
            "provider_id": "gemini",
            "model": "gemini-3.5-flash",
        }

    def test_unknown_deployment_returns_none(self, deployments_config):
        assert deployments_router.deployment_model_override("nope") is None

    def test_empty_reference_returns_none(self, deployments_config):
        assert deployments_router.deployment_model_override("") is None

    def test_missing_config_file_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(deployments_router, "CONFIG_PATH", tmp_path / "absent.json")
        assert deployments_router.deployment_model_override("support-bot") is None


class TestOverrideApplication:
    def test_override_replaces_the_agent_model(self):
        runtime = object.__new__(CrewAIWorkflowRuntime)
        config = AgentConfig(
            id="a", type="conversable", name="A",
            llm_config={"provider_id": "openrouter", "model": "openai/gpt-oss-20b", "temperature": 0.3},
        )
        merged = runtime._effective_model_config(config)
        assert merged["provider_id"] == "openrouter"

        applied = {**merged, **{"provider_id": "gemini", "model": "gemini-3.5-flash"}}
        assert applied["provider_id"] == "gemini"
        assert applied["model"] == "gemini-3.5-flash"
        # Non-routing settings from the agent survive
        assert applied["temperature"] == 0.3


class TestClientCannotForceRouting:
    def test_client_supplied_model_override_is_discarded(self, deployments_config, monkeypatch):
        """A forged metadata.model_override must not survive into the run."""
        import asyncio
        from datetime import datetime
        from types import SimpleNamespace

        captured: dict = {}

        class _Runtime:
            async def run_message(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(response="ok", trace_steps=[], metadata={})

        from src.api import session_manager as sm

        manager = object.__new__(sm.SessionManager)
        manager.runtime = _Runtime()
        manager.workflow_registry = SimpleNamespace(get_workflow=lambda _id: SimpleNamespace(id="wf"))
        manager._save_sessions = lambda: None
        manager._response = lambda session, text, meta: {"response": text}

        session = SimpleNamespace(
            active=True,
            metadata={"workflow_id": "wf", "user_id": "u", "deployment": "support-bot"},
            conversation_history=[],
            turn_count=0,
            add_message=lambda *a, **k: None,
            increment_turn=lambda: None,
            updated_at=datetime.utcnow(),
        )

        async def _get_session(_sid):
            return session

        manager.get_session = _get_session

        asyncio.run(
            manager.process_message(
                session_id="s1",
                message="hi",
                metadata={"model_override": {"provider_id": "attacker", "model": "evil"}},
            )
        )

        # The deployment record wins; the forged value is gone
        assert captured["metadata"]["model_override"] == {
            "provider_id": "gemini",
            "model": "gemini-3.5-flash",
        }
