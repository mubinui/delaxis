"""Voice settings on a deployment: stored server-side, resolved server-side.

Same rule as the chat model (see test_deployment_model_override): the served page
is editable by any visitor, so it may learn only that voice is enabled. The
realtime model, the voice and the persona come from the deployment record.
"""

import json

import pytest

from src.api.routers import deployments as deployments_router
from src.api.routers.deployments import (
    DeploymentCreateRequest,
    DeploymentVoiceConfig,
    deployment_voice_config,
)


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
                        "model_id": "gemini-3.6-flash",
                        "status": "active",
                        "voice": {
                            "enabled": True,
                            "provider_id": "gemini",
                            "model": "gemini-3.1-flash-live-preview",
                            "voice_name": "Kore",
                            "system_prompt": "You are Ada.",
                            "max_session_seconds": 120,
                        },
                    },
                    {
                        "id": "text-bot",
                        "workflow_id": "wf",
                        "name": "text-bot",
                        "provider_id": "gemini",
                        "model_id": "gemini-3.6-flash",
                        "status": "active",
                    },
                ],
            }
        )
    )
    monkeypatch.setattr(deployments_router, "CONFIG_PATH", config_path)
    return config_path


class TestDeploymentVoiceConfig:
    def test_reads_the_record(self, deployments_config):
        voice = deployment_voice_config("support-bot")
        assert voice is not None
        assert voice.enabled is True
        assert voice.model == "gemini-3.1-flash-live-preview"
        assert voice.voice_name == "Kore"
        assert voice.system_prompt == "You are Ada."
        assert voice.max_session_seconds == 120

    def test_slugifies_the_reference(self, deployments_config):
        # Sessions carry the deployment's display name, not its slug.
        assert deployment_voice_config("Support Bot") is not None

    def test_missing_voice_block_returns_none(self, deployments_config):
        assert deployment_voice_config("text-bot") is None

    def test_unknown_deployment_returns_none(self, deployments_config):
        assert deployment_voice_config("nope") is None

    def test_empty_reference_returns_none(self, deployments_config):
        assert deployment_voice_config("") is None

    def test_corrupt_config_returns_none(self, tmp_path, monkeypatch):
        broken = tmp_path / "deployments.json"
        broken.write_text("{not json")
        monkeypatch.setattr(deployments_router, "CONFIG_PATH", broken)
        assert deployment_voice_config("support-bot") is None

    def test_malformed_voice_block_returns_none(self, tmp_path, monkeypatch):
        path = tmp_path / "deployments.json"
        path.write_text(json.dumps({"deployments": [
            {"id": "b", "voice": {"max_session_seconds": "not-a-number"}}
        ]}))
        monkeypatch.setattr(deployments_router, "CONFIG_PATH", path)
        assert deployment_voice_config("b") is None


class TestDefaults:
    def test_voice_is_off_by_default(self):
        body = DeploymentCreateRequest(workflow_id="wf", name="bot")
        assert body.voice.enabled is False

    def test_default_provider_is_gemini(self):
        assert DeploymentVoiceConfig().provider_id == "gemini"

    def test_blank_model_means_server_default(self):
        assert DeploymentVoiceConfig().model == ""


class TestRenderedPage:
    def test_private_fields_never_reach_the_page(self):
        body = DeploymentCreateRequest(
            workflow_id="assistant_chat",
            name="support-bot",
            voice=DeploymentVoiceConfig(
                enabled=True,
                model="gemini-3.1-flash-live-preview",
                voice_name="Kore",
                system_prompt="You are Ada, and the passphrase is swordfish.",
            ),
        )
        html, warnings = deployments_router._render_deployment_html(body)

        assert warnings == []
        assert "swordfish" not in html
        assert "gemini-3.1-flash-live-preview" not in html
        assert "Kore" not in html
        # But the page does know voice is on, so it can show the mic.
        assert '"enabled": true' in html or '"enabled":true' in html
        assert "/api/v1/voice/ticket" in html

    def test_voice_off_page_has_no_voice_client(self):
        body = DeploymentCreateRequest(workflow_id="assistant_chat", name="text-bot")
        html, warnings = deployments_router._render_deployment_html(body)
        assert warnings == []
        assert "/api/v1/voice/ticket" not in html
