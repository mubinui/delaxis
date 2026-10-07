"""Unit tests for VersionedConfigService."""

import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.config.versioned_service import (
    ConfigVersion,
    ConflictResponse,
    VersionedConfigService,
)
from src.infrastructure.database.schema import ConfigSnapshot


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager."""
    with patch("src.config.versioned_service.DatabaseConnectionManager") as mock_manager:
        mock_session = MagicMock()
        mock_manager.return_value.get_session.return_value.__enter__.return_value = mock_session
        mock_manager.return_value.get_session.return_value.__exit__.return_value = None
        yield {
            "manager": mock_manager,
            "session": mock_session,
        }


@pytest.fixture
def mock_audit_logger():
    """Create a mock audit logger."""
    with patch("src.config.versioned_service.AuditLogger") as mock_logger:
        yield mock_logger.return_value


def test_generate_etag():
    """Test SHA256 hash generation for configuration."""
    service = VersionedConfigService(
        database_url="postgresql://test",
    )

    config_data = {"id": "test", "name": "Test Config", "value": 123}
    etag = service.generate_etag(config_data)

    # Verify it's a valid SHA256 hash
    assert len(etag) == 64
    assert all(c in "0123456789abcdef" for c in etag)

    # Same config should produce same hash
    etag2 = service.generate_etag(config_data)
    assert etag == etag2

    # Different config should produce different hash
    config_data2 = {"id": "test", "name": "Different Config", "value": 456}
    etag3 = service.generate_etag(config_data2)
    assert etag != etag3


def test_generate_etag_key_order_independent():
    """Test that etag generation is independent of key order."""
    service = VersionedConfigService(
        database_url="postgresql://test",
    )

    config1 = {"a": 1, "b": 2, "c": 3}
    config2 = {"c": 3, "a": 1, "b": 2}

    etag1 = service.generate_etag(config1)
    etag2 = service.generate_etag(config2)

    # Should be the same despite different key order
    assert etag1 == etag2


def test_get_config_found(mock_db_manager, mock_audit_logger):
    """Test retrieving an existing configuration."""
    # Setup mock
    mock_session = mock_db_manager["session"]

    snapshot = ConfigSnapshot(
        id=1,
        config_type="agent",
        config_id="test_agent",
        version=5,
        etag="abc123",
        config_data={"name": "Test Agent", "type": "conversable"},
        created_at=datetime.now(UTC),
        updated_by="user1",
        change_summary="Updated configuration",
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = snapshot
    mock_session.execute.return_value = mock_result

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
        audit_logger=mock_audit_logger,
    )

    # Get config
    config_data, version_info = service.get_config("agent", "test_agent", "user1")

    # Assertions
    assert config_data == {"name": "Test Agent", "type": "conversable"}
    assert version_info.version == 5
    assert version_info.etag == "abc123"
    assert version_info.updated_by == "user1"
    mock_audit_logger.log_config_retrieval.assert_called_once()


def test_get_config_not_found(mock_db_manager, mock_audit_logger):
    """Test retrieving a non-existent configuration."""
    # Setup mock
    mock_session = mock_db_manager["session"]
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
        audit_logger=mock_audit_logger,
    )

    # Get config
    config_data, version_info = service.get_config("agent", "nonexistent", "user1")

    # Assertions
    assert config_data is None
    assert version_info is None
    mock_audit_logger.log_config_retrieval.assert_called_once()


def test_update_config_create_new(mock_db_manager, mock_audit_logger):
    """Test creating a new configuration."""
    # Setup mock - config doesn't exist
    mock_session = mock_db_manager["session"]
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
        audit_logger=mock_audit_logger,
    )

    # Update (create) config
    new_config = {"name": "New Agent", "type": "conversable"}
    success, etag, conflict = service.update_config(
        "agent",
        "new_agent",
        new_config,
        user_id="user1",
        change_summary="Initial creation",
    )

    # Assertions
    assert success is True
    assert etag is not None
    assert conflict is None
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_audit_logger.log_config_creation.assert_called_once()


def test_update_config_success_with_version_number(mock_db_manager, mock_audit_logger):
    """Test successful update with version number token."""
    # Setup mock - existing config
    mock_session = mock_db_manager["session"]

    existing_snapshot = ConfigSnapshot(
        id=1,
        config_type="agent",
        config_id="test_agent",
        version=3,
        etag="old_etag",
        config_data={"name": "Old Agent"},
        created_at=datetime.now(UTC),
        updated_by="user1",
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_snapshot
    mock_session.execute.return_value = mock_result

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
        audit_logger=mock_audit_logger,
    )

    # Update config with correct version
    new_config = {"name": "Updated Agent"}
    success, etag, conflict = service.update_config(
        "agent",
        "test_agent",
        new_config,
        version_token="3",  # Matches current version
        user_id="user2",
        change_summary="Updated name",
    )

    # Assertions
    assert success is True
    assert etag is not None
    assert conflict is None
    mock_session.add.assert_called()
    mock_session.commit.assert_called()
    mock_audit_logger.log_config_update.assert_called_once()


def test_update_config_success_with_etag(mock_db_manager, mock_audit_logger):
    """Test successful update with etag token."""
    # Setup mock - existing config
    mock_session = mock_db_manager["session"]

    old_config = {"name": "Old Agent"}
    old_etag = hashlib.sha256(json.dumps(old_config, sort_keys=True).encode()).hexdigest()

    existing_snapshot = ConfigSnapshot(
        id=1,
        config_type="agent",
        config_id="test_agent",
        version=2,
        etag=old_etag,
        config_data=old_config,
        created_at=datetime.now(UTC),
        updated_by="user1",
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_snapshot
    mock_session.execute.return_value = mock_result

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
        audit_logger=mock_audit_logger,
    )

    # Update config with correct etag
    new_config = {"name": "Updated Agent"}
    success, etag, conflict = service.update_config(
        "agent",
        "test_agent",
        new_config,
        version_token=old_etag,  # Matches current etag
        user_id="user2",
    )

    # Assertions
    assert success is True
    assert etag is not None
    assert conflict is None


def test_update_config_version_conflict(mock_db_manager, mock_audit_logger):
    """Test version conflict detection with version number."""
    # Setup mock - existing config
    mock_session = mock_db_manager["session"]

    existing_snapshot = ConfigSnapshot(
        id=1,
        config_type="agent",
        config_id="test_agent",
        version=5,
        etag="current_etag",
        config_data={"name": "Current Agent", "value": 100},
        created_at=datetime.now(UTC),
        updated_by="user1",
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_snapshot
    mock_session.execute.return_value = mock_result

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
        audit_logger=mock_audit_logger,
    )

    # Update config with wrong version
    new_config = {"name": "Updated Agent", "value": 200}
    success, etag, conflict = service.update_config(
        "agent",
        "test_agent",
        new_config,
        version_token="3",  # Doesn't match current version (5)
        user_id="user2",
    )

    # Assertions
    assert success is False
    assert etag is None
    assert conflict is not None
    assert conflict["status"] == "conflict"
    assert conflict["current_version"] == 5
    assert conflict["provided_version"] == 3
    assert "diff" in conflict
    mock_audit_logger.log_config_conflict.assert_called_once()


def test_update_config_etag_conflict(mock_db_manager, mock_audit_logger):
    """Test etag conflict detection."""
    # Setup mock - existing config
    mock_session = mock_db_manager["session"]

    existing_snapshot = ConfigSnapshot(
        id=1,
        config_type="agent",
        config_id="test_agent",
        version=2,
        etag="current_etag_abc",
        config_data={"name": "Current Agent"},
        created_at=datetime.now(UTC),
        updated_by="user1",
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_snapshot
    mock_session.execute.return_value = mock_result

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
        audit_logger=mock_audit_logger,
    )

    # Update config with wrong etag
    new_config = {"name": "Updated Agent"}
    success, etag, conflict = service.update_config(
        "agent",
        "test_agent",
        new_config,
        version_token="wrong_etag_xyz",  # Doesn't match current etag
        user_id="user2",
    )

    # Assertions
    assert success is False
    assert etag is None
    assert conflict is not None
    assert conflict["status"] == "conflict"
    assert conflict["current_etag"] == "current_etag_abc"
    assert conflict["provided_etag"] == "wrong_etag_xyz"


def test_get_config_history(mock_db_manager, mock_audit_logger):
    """Test retrieving configuration history."""
    # Setup mock
    mock_session = mock_db_manager["session"]

    snapshots = [
        ConfigSnapshot(
            id=3,
            config_type="agent",
            config_id="test_agent",
            version=3,
            etag="etag3",
            config_data={"name": "Agent v3"},
            created_at=datetime(2024, 1, 3),
            updated_by="user1",
            change_summary="Version 3",
        ),
        ConfigSnapshot(
            id=2,
            config_type="agent",
            config_id="test_agent",
            version=2,
            etag="etag2",
            config_data={"name": "Agent v2"},
            created_at=datetime(2024, 1, 2),
            updated_by="user2",
            change_summary="Version 2",
        ),
        ConfigSnapshot(
            id=1,
            config_type="agent",
            config_id="test_agent",
            version=1,
            etag="etag1",
            config_data={"name": "Agent v1"},
            created_at=datetime(2024, 1, 1),
            updated_by="user1",
            change_summary="Initial",
        ),
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = snapshots
    mock_session.execute.return_value = mock_result

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
        audit_logger=mock_audit_logger,
    )

    # Get history
    history = service.get_config_history("agent", "test_agent", limit=10, user_id="user1")

    # Assertions
    assert len(history) == 3
    assert history[0]["version"] == 3
    assert history[1]["version"] == 2
    assert history[2]["version"] == 1
    assert history[0]["updated_by"] == "user1"
    assert history[1]["updated_by"] == "user2"
    mock_audit_logger.log_config_history_retrieval.assert_called_once()


def test_rollback_config_success(mock_db_manager, mock_audit_logger):
    """Test successful configuration rollback."""
    # Setup mock
    mock_session = mock_db_manager["session"]

    # Target snapshot (version 2)
    target_snapshot = ConfigSnapshot(
        id=2,
        config_type="agent",
        config_id="test_agent",
        version=2,
        etag="etag2",
        config_data={"name": "Agent v2", "value": 200},
        created_at=datetime(2024, 1, 2),
        updated_by="user1",
    )

    # Current snapshot (version 5)
    current_snapshot = ConfigSnapshot(
        id=5,
        config_type="agent",
        config_id="test_agent",
        version=5,
        etag="etag5",
        config_data={"name": "Agent v5", "value": 500},
        created_at=datetime(2024, 1, 5),
        updated_by="user2",
    )

    # Mock execute to return different results based on query
    def execute_side_effect(stmt):
        mock_result = MagicMock()
        # Check if this is the target version query or current version query
        if hasattr(stmt, "whereclause") and "version" in str(stmt.whereclause):
            mock_result.scalar_one_or_none.return_value = target_snapshot
        else:
            mock_result.scalar_one_or_none.return_value = current_snapshot
        return mock_result

    mock_session.execute.side_effect = execute_side_effect

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
        audit_logger=mock_audit_logger,
    )

    # Rollback to version 2
    success, etag = service.rollback_config(
        "agent",
        "test_agent",
        target_version=2,
        user_id="user3",
    )

    # Assertions
    assert success is True
    assert etag is not None
    mock_session.add.assert_called()
    mock_session.commit.assert_called()
    mock_audit_logger.log_config_rollback.assert_called_once()


def test_rollback_config_target_not_found(mock_db_manager, mock_audit_logger):
    """Test rollback when target version doesn't exist."""
    # Setup mock
    mock_session = mock_db_manager["session"]
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
        audit_logger=mock_audit_logger,
    )

    # Rollback to non-existent version
    success, error = service.rollback_config(
        "agent",
        "test_agent",
        target_version=99,
        user_id="user1",
    )

    # Assertions
    assert success is False
    assert "not found" in error


def test_compute_diff():
    """Test computing differences between configurations."""
    service = VersionedConfigService(
        database_url="postgresql://test",
    )

    current = {
        "name": "Agent",
        "type": "conversable",
        "value": 100,
        "removed_field": "old",
    }

    proposed = {
        "name": "Agent",
        "type": "retrieve",  # Modified
        "value": 100,
        "new_field": "added",  # Added
        # removed_field is removed
    }

    diff = service._compute_diff(current, proposed)

    # Assertions
    assert "new_field" in diff["added"]
    assert "removed_field" in diff["removed"]
    assert len(diff["modified"]) == 1
    assert diff["modified"][0]["field"] == "type"
    assert diff["modified"][0]["current"] == "conversable"
    assert diff["modified"][0]["proposed"] == "retrieve"


def test_apply_retention_policy(mock_db_manager, mock_audit_logger):
    """Test snapshot retention policy."""
    # Setup mock
    mock_session = mock_db_manager["session"]

    # Create 60 snapshot IDs (more than max_snapshots=50)
    snapshot_ids = list(range(1, 61))

    # Create snapshots for the count query
    snapshots = [
        ConfigSnapshot(
            id=i,
            config_type="agent",
            config_id="test_agent",
            version=i,
            etag=f"etag{i}",
            config_data={"version": i},
            created_at=datetime(2024, 1, i % 28 + 1),
            updated_by="user1",
        )
        for i in snapshot_ids
    ]

    # Mock the count query to return all snapshots
    mock_count_result = MagicMock()
    mock_count_result.scalars.return_value.all.return_value = snapshots

    # Mock the ID query to return just IDs
    mock_id_result = MagicMock()
    mock_id_result.scalars.return_value.all.return_value = snapshot_ids[
        :10
    ]  # First 10 IDs to delete

    # Setup execute to return different results based on call order
    mock_session.execute.side_effect = [mock_count_result, mock_id_result, MagicMock()]

    # Create service with max_snapshots=50
    service = VersionedConfigService(
        database_url="postgresql://test",
        audit_logger=mock_audit_logger,
        max_snapshots=50,
    )

    # Apply retention policy
    service._apply_retention_policy(mock_session, "agent", "test_agent")

    # Should have called execute 3 times: count query, ID query, delete query
    assert mock_session.execute.call_count == 3


def test_health_check_success(mock_db_manager):
    """Test successful health check."""
    # Setup mock
    mock_manager = mock_db_manager["manager"].return_value
    mock_manager.health_check.return_value = True

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
    )

    # Health check
    result = service.health_check()

    # Assertions
    assert result is True


def test_health_check_failure(mock_db_manager):
    """Test failed health check."""
    # Setup mock
    mock_manager = mock_db_manager["manager"].return_value
    mock_manager.health_check.return_value = False

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
    )

    # Health check
    result = service.health_check()

    # Assertions
    assert result is False


def test_close(mock_db_manager):
    """Test closing database connections."""
    # Setup mock
    mock_manager = mock_db_manager["manager"].return_value

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
    )

    # Close
    service.close()

    # Assertions
    mock_manager.close.assert_called_once()


def test_update_config_without_version_token(mock_db_manager, mock_audit_logger):
    """Test updating config without providing version token."""
    # Setup mock - existing config
    mock_session = mock_db_manager["session"]

    existing_snapshot = ConfigSnapshot(
        id=1,
        config_type="agent",
        config_id="test_agent",
        version=1,
        etag="old_etag",
        config_data={"name": "Old Agent"},
        created_at=datetime.now(UTC),
        updated_by="user1",
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_snapshot
    mock_session.execute.return_value = mock_result

    # Create service
    service = VersionedConfigService(
        database_url="postgresql://test",
        audit_logger=mock_audit_logger,
    )

    # Update config without version token (should succeed)
    new_config = {"name": "Updated Agent"}
    success, etag, conflict = service.update_config(
        "agent",
        "test_agent",
        new_config,
        version_token=None,  # No version check
        user_id="user2",
    )

    # Assertions
    assert success is True
    assert etag is not None
    assert conflict is None


def test_config_version_dataclass():
    """Test ConfigVersion dataclass."""
    version = ConfigVersion(
        version=5,
        etag="abc123",
        last_updated=datetime(2024, 1, 1),
        updated_by="user1",
    )

    assert version.version == 5
    assert version.etag == "abc123"
    assert version.updated_by == "user1"


def test_conflict_response_dataclass():
    """Test ConflictResponse dataclass."""
    conflict = ConflictResponse(
        status="conflict",
        current_version=5,
        current_etag="abc",
        current_config={"name": "Current"},
        provided_version=3,
        diff={"added": [], "removed": [], "modified": []},
    )

    assert conflict.status == "conflict"
    assert conflict.current_version == 5
    assert conflict.provided_version == 3
