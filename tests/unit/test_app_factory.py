"""Tests for FastAPI app assembly and SPA serving."""

import pytest
from fastapi.testclient import TestClient

from src.api.app_factory import create_app


def test_create_app_registers_core_routes() -> None:
    app = create_app()
    route_paths = {getattr(route, "path", None) for route in app.routes}

    assert "/" in route_paths or "/{path:path}" in route_paths
    assert "/api" in route_paths
    assert "/health" in route_paths
    assert "/api/v1/chat/stream" in route_paths
    assert "/api/v1/sessions/query" in route_paths


@pytest.fixture
def spa_app(tmp_path, monkeypatch):
    """App with a fake built SPA in a temp static dir."""
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html><body>Delaxis SPA</body></html>")
    (static_dir / "assets" / "app.js").write_text("console.log('delaxis')")
    monkeypatch.setenv("DELAXIS_STATIC_DIR", str(static_dir))
    return create_app()


def test_spa_served_at_root(spa_app):
    client = TestClient(spa_app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Delaxis SPA" in response.text


def test_spa_fallback_serves_index_for_client_routes(spa_app):
    client = TestClient(spa_app)
    response = client.get("/some/client/route")
    assert response.status_code == 200
    assert "Delaxis SPA" in response.text


def test_spa_fallback_does_not_shadow_api_404(spa_app):
    client = TestClient(spa_app)
    assert client.get("/api/v1/does-not-exist").status_code == 404


def test_spa_serves_real_static_assets(spa_app):
    client = TestClient(spa_app)
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert "delaxis" in response.text


def test_health_alias_still_works_with_spa(spa_app):
    client = TestClient(spa_app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_api_info_endpoint(spa_app):
    client = TestClient(spa_app)
    response = client.get("/api")
    assert response.status_code == 200
    assert response.json()["service"] == "Delaxis"
