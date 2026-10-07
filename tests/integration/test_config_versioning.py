"""Integration tests for configuration versioning API."""

from datetime import datetime
from unittest.mock import MagicMock, Mock

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.config.versioned_service import ConfigVersion


@pytest.fixture
def mock_versioned_service():
    """Create a mock VersionedConfigService."""
    mock_service = MagicMock()
    return mock_service


@pytest.fixture
def mock_auth():
    """Mock authentication to bypass auth checks."""
    # Mock user
    mock_current_user = Mock()
    mock_current_user.user_id = "test_user"
    mock_current_user.username = "testuser"
    mock_current_user.role = "admin"

    return mock_current_user


@pytest.fixture
def client(mock_auth, mock_versioned_service):
    """Create test client with mocked authentication and services."""
    from src.api.routers.configs import get_versioned_config_service, require_admin, require_user

    # Override dependencies
    app.dependency_overrides[require_user] = lambda: mock_auth
    app.dependency_overrides[require_admin] = lambda: mock_auth
    app.dependency_overrides[get_versioned_config_service] = lambda: mock_versioned_service

    yield TestClient(app)

    # Clean up
    app.dependency_overrides.clear()


def test_get_config_success(client, mock_versioned_service, mock_auth):
    """Test successfully retrieving a configuration."""
    # Setup mock
    config_data = {"name": "Test Agent", "type": "conversable"}
    version_info = ConfigVersion(
        version=3,
        etag="abc123",
        last_updated=datetime(2024, 1, 1, 12, 0, 0),
        updated_by="user1",
    )
    mock_versioned_service.get_config.return_value = (config_data, version_info)

    # Make request
    response = client.get("/api/v1/configs/agent/test_agent")

    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert data["config_type"] == "agent"
    assert data["config_id"] == "test_agent"
    assert data["config_data"] == config_data
    assert data["version"] == 3
    assert data["etag"] == "abc123"
    assert data["updated_by"] == "user1"
    mock_versioned_service.get_config.assert_called_once()


def test_get_config_not_found(client, mock_versioned_service, mock_auth):
    """Test retrieving a non-existent configuration."""
    # Setup mock
    mock_versioned_service.get_config.return_value = (None, None)

    # Make request
    response = client.get("/api/v1/configs/agent/nonexistent")

    # Assertions
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_update_config_success(client, mock_versioned_service, mock_auth):
    """Test successfully updating a configuration."""
    # Setup mock for update
    new_etag = "new_etag_456"
    mock_versioned_service.update_config.return_value = (True, new_etag, None)

    # Setup mock for get (after update)
    updated_config = {"name": "Updated Agent", "type": "conversable"}
    version_info = ConfigVersion(
        version=4,
        etag=new_etag,
        last_updated=datetime(2024, 1, 2, 12, 0, 0),
        updated_by="test_user",
    )
    mock_versioned_service.get_config.return_value = (updated_config, version_info)

    # Make request
    response = client.put(
        "/api/v1/configs/agent/test_agent",
        json={
            "config_data": updated_config,
            "change_summary": "Updated agent name",
        },
        headers={"If-Match": "3"},
    )

    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 4
    assert data["etag"] == new_etag
    assert data["config_data"] == updated_config
    mock_versioned_service.update_config.assert_called_once()


def test_update_config_version_conflict(client, mock_versioned_service, mock_auth):
    """Test concurrent update scenario with version conflict."""
    # Setup mock - conflict detected
    conflict_response = {
        "status": "conflict",
        "current_version": 5,
        "current_etag": "current_etag",
        "current_config": {"name": "Current Agent"},
        "provided_version": 3,
        "diff": {
            "added": [],
            "removed": [],
            "modified": [
                {
                    "field": "name",
                    "current": "Current Agent",
                    "proposed": "Updated Agent",
                }
            ],
        },
    }
    mock_versioned_service.update_config.return_value = (False, None, conflict_response)

    # Make request
    response = client.put(
        "/api/v1/configs/agent/test_agent",
        json={
            "config_data": {"name": "Updated Agent"},
            "change_summary": "Update name",
        },
        headers={"If-Match": "3"},  # Stale version
    )

    # Assertions
    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["status"] == "conflict"
    assert data["detail"]["current_version"] == 5
    assert data["detail"]["provided_version"] == 3
    assert "diff" in data["detail"]


def test_update_config_etag_conflict(client, mock_versioned_service, mock_auth):
    """Test concurrent update with etag conflict."""
    # Setup mock - conflict detected
    conflict_response = {
        "status": "conflict",
        "current_version": 3,
        "current_etag": "current_etag_abc",
        "current_config": {"name": "Current Agent"},
        "provided_etag": "stale_etag_xyz",
        "diff": {
            "added": [],
            "removed": [],
            "modified": [
                {
                    "field": "name",
                    "current": "Current Agent",
                    "proposed": "Updated Agent",
                }
            ],
        },
    }
    mock_versioned_service.update_config.return_value = (False, None, conflict_response)

    # Make request
    response = client.put(
        "/api/v1/configs/agent/test_agent",
        json={
            "config_data": {"name": "Updated Agent"},
        },
        headers={"If-Match": "stale_etag_xyz"},  # Stale etag
    )

    # Assertions
    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["status"] == "conflict"
    assert data["detail"]["current_etag"] == "current_etag_abc"
    assert data["detail"]["provided_etag"] == "stale_etag_xyz"


def test_update_config_without_if_match_header(client, mock_versioned_service, mock_auth):
    """Test updating config without If-Match header."""
    # Setup mock
    new_etag = "new_etag"
    mock_versioned_service.update_config.return_value = (True, new_etag, None)

    updated_config = {"name": "Updated Agent"}
    version_info = ConfigVersion(
        version=2,
        etag=new_etag,
        last_updated=datetime(2024, 1, 2),
        updated_by="test_user",
    )
    mock_versioned_service.get_config.return_value = (updated_config, version_info)

    # Make request without If-Match header
    response = client.put(
        "/api/v1/configs/agent/test_agent",
        json={"config_data": updated_config},
    )

    # Assertions
    assert response.status_code == 200
    # Verify update was called with None version_token
    call_args = mock_versioned_service.update_config.call_args
    assert call_args[1]["version_token"] is None


def test_get_config_history_success(client, mock_versioned_service, mock_auth):
    """Test retrieving configuration history."""
    # Setup mock
    history = [
        {
            "version": 3,
            "etag": "etag3",
            "created_at": "2024-01-03T12:00:00",
            "updated_by": "user1",
            "change_summary": "Version 3",
            "config_data": {"name": "Agent v3"},
        },
        {
            "version": 2,
            "etag": "etag2",
            "created_at": "2024-01-02T12:00:00",
            "updated_by": "user2",
            "change_summary": "Version 2",
            "config_data": {"name": "Agent v2"},
        },
        {
            "version": 1,
            "etag": "etag1",
            "created_at": "2024-01-01T12:00:00",
            "updated_by": "user1",
            "change_summary": "Initial",
            "config_data": {"name": "Agent v1"},
        },
    ]
    mock_versioned_service.get_config_history.return_value = history

    # Make request
    response = client.get("/api/v1/configs/agent/test_agent/history?limit=10")

    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert data["config_type"] == "agent"
    assert data["config_id"] == "test_agent"
    assert len(data["history"]) == 3
    assert data["history"][0]["version"] == 3
    assert data["history"][1]["version"] == 2
    assert data["history"][2]["version"] == 1
    mock_versioned_service.get_config_history.assert_called_once()


def test_get_config_history_with_limit(client, mock_versioned_service, mock_auth):
    """Test retrieving configuration history with limit."""
    # Setup mock
    history = [
        {
            "version": 5,
            "etag": "etag5",
            "created_at": "2024-01-05T12:00:00",
            "updated_by": "user1",
            "change_summary": "Version 5",
            "config_data": {"name": "Agent v5"},
        },
    ]
    mock_versioned_service.get_config_history.return_value = history

    # Make request with limit
    response = client.get("/api/v1/configs/agent/test_agent/history?limit=1")

    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert len(data["history"]) == 1
    # Verify limit was passed to service
    call_args = mock_versioned_service.get_config_history.call_args
    assert call_args[1]["limit"] == 1


def test_rollback_config_success(client, mock_versioned_service, mock_auth):
    """Test successfully rolling back configuration."""
    # Setup mock for rollback
    new_etag = "rollback_etag"
    mock_versioned_service.rollback_config.return_value = (True, new_etag)

    # Setup mock for get (after rollback)
    rolled_back_config = {"name": "Agent v2", "value": 200}
    version_info = ConfigVersion(
        version=6,  # New version after rollback
        etag=new_etag,
        last_updated=datetime(2024, 1, 6, 12, 0, 0),
        updated_by="test_user",
    )
    mock_versioned_service.get_config.return_value = (rolled_back_config, version_info)

    # Make request
    response = client.post(
        "/api/v1/configs/agent/test_agent/rollback",
        json={"target_version": 2},
    )

    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 6
    assert data["config_data"] == rolled_back_config
    mock_versioned_service.rollback_config.assert_called_once_with(
        config_type="agent",
        config_id="test_agent",
        target_version=2,
        user_id="test_user",
    )


def test_rollback_config_target_not_found(client, mock_versioned_service, mock_auth):
    """Test rollback when target version doesn't exist."""
    # Setup mock
    mock_versioned_service.rollback_config.return_value = (False, "Version 99 not found")

    # Make request
    response = client.post(
        "/api/v1/configs/agent/test_agent/rollback",
        json={"target_version": 99},
    )

    # Assertions
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


def test_concurrent_update_scenario(client, mock_versioned_service, mock_auth):
    """Test realistic concurrent update scenario."""
    # Scenario: Two users try to update the same config simultaneously

    # User A gets config (version 5)
    config_v5 = {"name": "Agent v5", "value": 500}
    version_info_v5 = ConfigVersion(
        version=5,
        etag="etag_v5",
        last_updated=datetime(2024, 1, 5),
        updated_by="user_a",
    )
    mock_versioned_service.get_config.return_value = (config_v5, version_info_v5)

    response_a = client.get("/api/v1/configs/agent/test_agent")
    assert response_a.status_code == 200
    assert response_a.json()["version"] == 5

    # User B also gets config (version 5)
    response_b = client.get("/api/v1/configs/agent/test_agent")
    assert response_b.status_code == 200
    assert response_b.json()["version"] == 5

    # User B updates successfully (version 5 -> 6)
    mock_versioned_service.update_config.return_value = (True, "etag_v6", None)
    config_v6 = {"name": "Agent v6 by B", "value": 600}
    version_info_v6 = ConfigVersion(
        version=6,
        etag="etag_v6",
        last_updated=datetime(2024, 1, 6),
        updated_by="user_b",
    )
    mock_versioned_service.get_config.return_value = (config_v6, version_info_v6)

    response_b_update = client.put(
        "/api/v1/configs/agent/test_agent",
        json={"config_data": config_v6},
        headers={"If-Match": "5"},
    )
    assert response_b_update.status_code == 200
    assert response_b_update.json()["version"] == 6

    # User A tries to update with stale version (conflict)
    conflict_response = {
        "status": "conflict",
        "current_version": 6,
        "current_etag": "etag_v6",
        "current_config": config_v6,
        "provided_version": 5,
        "diff": {
            "added": [],
            "removed": [],
            "modified": [
                {
                    "field": "name",
                    "current": "Agent v6 by B",
                    "proposed": "Agent v6 by A",
                }
            ],
        },
    }
    mock_versioned_service.update_config.return_value = (False, None, conflict_response)

    response_a_update = client.put(
        "/api/v1/configs/agent/test_agent",
        json={"config_data": {"name": "Agent v6 by A", "value": 650}},
        headers={"If-Match": "5"},  # Stale version
    )
    assert response_a_update.status_code == 409
    conflict_data = response_a_update.json()["detail"]
    assert conflict_data["status"] == "conflict"
    assert conflict_data["current_version"] == 6
    assert conflict_data["provided_version"] == 5


def test_conflict_response_format(client, mock_versioned_service, mock_auth):
    """Test that conflict response includes all required fields."""
    # Setup mock with complete conflict response
    conflict_response = {
        "status": "conflict",
        "current_version": 10,
        "current_etag": "current_etag_abc",
        "current_config": {
            "name": "Current Agent",
            "type": "conversable",
            "value": 1000,
        },
        "provided_version": 8,
        "provided_etag": None,
        "diff": {
            "added": ["new_field"],
            "removed": ["old_field"],
            "modified": [
                {
                    "field": "value",
                    "current": 1000,
                    "proposed": 800,
                }
            ],
        },
    }
    mock_versioned_service.update_config.return_value = (False, None, conflict_response)

    # Make request
    response = client.put(
        "/api/v1/configs/agent/test_agent",
        json={"config_data": {"name": "Updated Agent", "value": 800}},
        headers={"If-Match": "8"},
    )

    # Assertions
    assert response.status_code == 409
    conflict = response.json()["detail"]

    # Verify all required fields are present
    assert conflict["status"] == "conflict"
    assert "current_version" in conflict
    assert "current_etag" in conflict
    assert "current_config" in conflict
    assert "provided_version" in conflict
    assert "diff" in conflict

    # Verify diff structure
    diff = conflict["diff"]
    assert "added" in diff
    assert "removed" in diff
    assert "modified" in diff
    assert len(diff["modified"]) > 0
    assert "field" in diff["modified"][0]
    assert "current" in diff["modified"][0]
    assert "proposed" in diff["modified"][0]


def test_history_retrieval_endpoint(client, mock_versioned_service, mock_auth):
    """Test history retrieval returns proper format."""
    # Setup mock
    history = [
        {
            "version": 2,
            "etag": "etag2",
            "created_at": "2024-01-02T10:00:00",
            "updated_by": "admin",
            "change_summary": "Updated configuration",
            "config_data": {"name": "Agent v2"},
        },
        {
            "version": 1,
            "etag": "etag1",
            "created_at": "2024-01-01T10:00:00",
            "updated_by": "admin",
            "change_summary": "Initial configuration",
            "config_data": {"name": "Agent v1"},
        },
    ]
    mock_versioned_service.get_config_history.return_value = history

    # Make request
    response = client.get("/api/v1/configs/workflow/test_workflow/history")

    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert data["config_type"] == "workflow"
    assert data["config_id"] == "test_workflow"
    assert len(data["history"]) == 2

    # Verify history entry structure
    entry = data["history"][0]
    assert "version" in entry
    assert "etag" in entry
    assert "created_at" in entry
    assert "updated_by" in entry
    assert "change_summary" in entry
    assert "config_data" in entry


def test_rollback_endpoint(client, mock_versioned_service, mock_auth):
    """Test rollback endpoint creates new version."""
    # Setup mock
    mock_versioned_service.rollback_config.return_value = (True, "new_etag_after_rollback")

    # Config after rollback (new version with old data)
    rolled_back_config = {"name": "Agent v3", "value": 300}
    version_info = ConfigVersion(
        version=8,  # New version number
        etag="new_etag_after_rollback",
        last_updated=datetime(2024, 1, 8),
        updated_by="test_user",
    )
    mock_versioned_service.get_config.return_value = (rolled_back_config, version_info)

    # Make request
    response = client.post(
        "/api/v1/configs/tool/test_tool/rollback",
        json={"target_version": 3},
    )

    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert data["config_type"] == "tool"
    assert data["config_id"] == "test_tool"
    assert data["version"] == 8  # New version, not target version
    assert data["config_data"] == rolled_back_config
