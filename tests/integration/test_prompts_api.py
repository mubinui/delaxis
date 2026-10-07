"""Integration tests for the Prompts API.

The API runs with authentication disabled in development mode, so the CRUD
tests exercise the real code path. One test flips the environment to
production and checks that the same endpoints then refuse anonymous calls.
"""

import json
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.config.settings import get_settings


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def temp_config_dir() -> Iterator[Path]:
    """Point the prompts router at an empty, throwaway prompt_templates.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "prompt_templates.json"
        config_path.write_text(json.dumps({"version": "1.0", "contexts": [], "fallbacks": {}}))
        with (
            patch("src.api.routers.prompts._get_prompts_config_path", return_value=config_path),
            # Keep the test on the file store even when the developer's .env
            # names a database; the versioned store is covered by its own tests.
            patch("src.api.routers.prompts._get_versioned_service", return_value=None),
        ):
            yield config_path


PROMPT = {
    "id": "test_prompt",
    "name": "Test Prompt",
    "description": "A test prompt template",
    "template": "Hello {name}, your age is {age}",
    "category": "test",
}


def _create(client: TestClient) -> dict:
    response = client.post("/api/v1/prompts", json=PROMPT)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_prompt_extracts_variables(client, temp_config_dir):
    body = _create(client)
    assert body["id"] == "test_prompt"
    assert body["template"] == PROMPT["template"]
    assert body["variables"] == ["name", "age"]
    stored = json.loads(temp_config_dir.read_text())
    assert [p["id"] for p in stored["contexts"]] == ["test_prompt"]


def test_create_duplicate_is_a_conflict(client, temp_config_dir):
    _create(client)
    response = client.post("/api/v1/prompts", json=PROMPT)
    assert response.status_code == 409


def test_list_prompts(client, temp_config_dir):
    assert client.get("/api/v1/prompts").json() == []
    _create(client)
    listed = client.get("/api/v1/prompts").json()
    assert [p["id"] for p in listed] == ["test_prompt"]


def test_get_prompt(client, temp_config_dir):
    assert client.get("/api/v1/prompts/test_prompt").status_code == 404
    _create(client)
    response = client.get("/api/v1/prompts/test_prompt")
    assert response.status_code == 200
    assert response.json()["name"] == "Test Prompt"


def test_update_prompt(client, temp_config_dir):
    _create(client)
    response = client.put(
        "/api/v1/prompts/test_prompt",
        json={"name": "Updated Test Prompt", "description": "An updated test prompt"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Updated Test Prompt"
    assert body["template"] == PROMPT["template"], "fields left out of the update must survive"
    assert client.put("/api/v1/prompts/missing", json={"name": "x"}).status_code == 404


def test_delete_prompt(client, temp_config_dir):
    _create(client)
    assert client.delete("/api/v1/prompts/test_prompt").status_code == 204
    assert client.get("/api/v1/prompts/test_prompt").status_code == 404
    assert client.delete("/api/v1/prompts/test_prompt").status_code == 404


def test_get_prompt_history_needs_the_versioned_store(client, temp_config_dir):
    """Without a database there is no history, and the API must say so rather than 500."""
    _create(client)
    response = client.get("/api/v1/prompts/test_prompt/history")
    assert response.status_code == 501, response.text


def test_production_mode_requires_authentication(client, temp_config_dir):
    settings = get_settings()
    original = settings.app.environment
    settings.app.environment = "production"
    try:
        assert client.get("/api/v1/prompts").status_code == 401
        assert client.post("/api/v1/prompts", json=PROMPT).status_code == 401
        assert client.get("/api/v1/prompts/test_prompt").status_code == 401
        assert client.put("/api/v1/prompts/test_prompt", json={"name": "x"}).status_code == 401
        assert client.delete("/api/v1/prompts/test_prompt").status_code == 401
        assert client.get("/api/v1/prompts/test_prompt/history").status_code == 401
    finally:
        settings.app.environment = original
