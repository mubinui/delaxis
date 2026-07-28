"""Unit tests for flash deployment lifecycle APIs (same-origin, no subprocesses)."""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import deployments as deployments_router


@pytest.fixture
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "deployments.json"
    deployments_dir = tmp_path / "deployments"

    monkeypatch.setattr(deployments_router, "CONFIG_PATH", config_path)
    monkeypatch.setattr(deployments_router, "DEPLOYMENTS_DIR", deployments_dir)

    app = FastAPI()
    app.include_router(deployments_router.router)
    app.include_router(deployments_router.pages_router)

    with TestClient(app) as test_client:
        yield test_client


def test_flash_deploy_writes_page_and_serves_it(client, tmp_path):
    payload = {
        "workflow_id": "demo_multi_agent",
        "name": "demo-chatbot",
        "title": "Demo Chatbot",
    }

    create_response = client.post("/api/v1/deployments/flash", json=payload)
    assert create_response.status_code == 201
    deployment = create_response.json()
    assert deployment["status"] == "active"
    assert deployment["url"] == "/d/demo-chatbot/"

    # The generated page exists on disk and is served same-origin
    index_path = Path(deployment["path"]) / "index.html"
    assert index_path.exists()
    page = client.get(f"/d/{deployment['id']}/")
    assert page.status_code == 200
    assert "Demo Chatbot" in page.text
    # Generated page must not hardcode a host — same-origin API calls only
    assert "127.0.0.1" not in page.text
    assert "localhost" not in page.text


def test_list_and_delete_deployment(client, tmp_path):
    payload = {"workflow_id": "demo_multi_agent", "name": "demo-chatbot"}
    created = client.post("/api/v1/deployments/flash", json=payload).json()

    listing = client.get("/api/v1/deployments")
    assert listing.status_code == 200
    assert [d["id"] for d in listing.json()] == [created["id"]]

    delete_response = client.delete(f"/api/v1/deployments/{created['id']}")
    assert delete_response.status_code == 204

    config = json.loads((tmp_path / "deployments.json").read_text(encoding="utf-8"))
    assert config["deployments"] == []
    assert not Path(created["path"]).exists()
    assert client.get(f"/d/{created['id']}/").status_code == 404


def test_delete_missing_deployment_returns_404(client):
    assert client.delete("/api/v1/deployments/nope").status_code == 404


def test_preview_reports_url_and_path(client):
    payload = {"workflow_id": "demo_multi_agent", "name": "My Bot!"}
    response = client.post("/api/v1/deployments/preview", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "/d/my-bot/"
    assert body["warnings"] == []
    assert "<!doctype html>" in body["html"]


def test_flash_deploy_replaces_existing_record(client):
    payload = {"workflow_id": "demo_multi_agent", "name": "demo-chatbot"}
    client.post("/api/v1/deployments/flash", json=payload)
    client.post("/api/v1/deployments/flash", json=payload)

    listing = client.get("/api/v1/deployments").json()
    assert len(listing) == 1


def test_theme_selection_reaches_served_page(client):
    from src.api.chatbot_page import THEMES

    payload = {"workflow_id": "demo_multi_agent", "name": "themed-bot", "theme": "ocean"}
    created = client.post("/api/v1/deployments/flash", json=payload).json()
    assert created["theme"] == "ocean"

    page = client.get(f"/d/{created['id']}/").text
    assert f"--bg: {THEMES['ocean']['bg']};" in page
    assert f"--accent: {THEMES['ocean']['accent']};" in page


def test_unknown_theme_normalizes_to_default(client):
    payload = {"workflow_id": "demo_multi_agent", "name": "weird-theme", "theme": "neon-zebra"}
    created = client.post("/api/v1/deployments/flash", json=payload).json()
    assert created["theme"] == "midnight"


def test_themes_endpoint_lists_presets(client):
    from src.api.chatbot_page import THEMES

    response = client.get("/api/v1/deployments/themes")
    assert response.status_code == 200
    presets = response.json()
    assert {p["id"] for p in presets} == set(THEMES)
    assert all("label" in p and "vars" in p for p in presets)


def test_custom_frontend_gets_config_before_app_scripts(client):
    frontend = (
        "<!doctype html><html><head><title>Custom</title></head>"
        "<body><script>const cfg = window.CHATBOT_CONFIG; boot(cfg);</script></body></html>"
    )
    payload = {
        "workflow_id": "demo_multi_agent",
        "name": "custom-bot",
        "frontend_html": frontend,
        "frontend_source": "ai_frontend_builder",
    }
    created = client.post("/api/v1/deployments/flash", json=payload)
    assert created.status_code == 201

    page = client.get("/d/custom-bot/").text
    assert "__CHATBOT_CONFIG__" not in page
    assert page.index("window.CHATBOT_CONFIG = {") < page.index("const cfg")
    assert "function renderMarkdown" in page


def test_hostile_title_is_escaped(client):
    payload = {
        "workflow_id": "demo_multi_agent",
        "name": "xss-bot",
        "title": '</title><script>alert(1)</script>',
    }
    client.post("/api/v1/deployments/flash", json=payload)
    page = client.get("/d/xss-bot/").text
    assert "<script>alert(1)</script>" not in page


def test_failed_generation_returns_500_and_error_record(client, monkeypatch):
    import src.api.routers.deployments as deployments_module

    def _boom(deployment_id, body):
        raise RuntimeError("disk full")

    monkeypatch.setattr(deployments_module, "_write_deployment", _boom)
    response = client.post(
        "/api/v1/deployments/flash",
        json={"workflow_id": "demo_multi_agent", "name": "broken-bot"},
    )
    assert response.status_code == 500
    assert "disk full" in response.json()["detail"]

    listing = client.get("/api/v1/deployments").json()
    assert listing[0]["status"] == "error"
    assert "disk full" in listing[0]["error"]


def test_no_trailing_slash_redirects(client):
    payload = {"workflow_id": "demo_multi_agent", "name": "slash-bot"}
    client.post("/api/v1/deployments/flash", json=payload)
    response = client.get("/d/slash-bot", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/d/slash-bot/"


def test_preview_warns_on_junk_frontend(client):
    payload = {
        "workflow_id": "demo_multi_agent",
        "name": "junk-bot",
        "frontend_html": "<div>not a page</div>",
    }
    response = client.post("/api/v1/deployments/preview", json=payload)
    assert response.status_code == 200
    assert response.json()["warnings"]
