"""Unit tests for FastAPI application."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


def test_api_info_endpoint(client):
    """Test the /api endpoint returns service information."""
    response = client.get("/api")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Delaxis"
    assert data["version"] == "0.1.0"
    assert "docs" in data


def test_health_check(client):
    """Test the health check endpoint."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "delaxis"
    assert data["version"] == "0.1.0"


def test_request_id_header(client):
    """Test that request ID is added to response headers."""
    response = client.get("/api/v1/health")
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


def test_cors_headers(client):
    """Test that CORS preflight requests are handled."""
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers


def test_unknown_api_route_returns_404(client):
    """Unknown API paths must 404 (never swallowed by the SPA fallback)."""
    response = client.get("/api/v1/nonexistent")
    assert response.status_code == 404


def test_openapi_docs_available(client):
    """Test that OpenAPI documentation is available."""
    response = client.get("/docs")
    assert response.status_code == 200
    
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "Delaxis"
    assert data["info"]["version"] == "0.1.0"
