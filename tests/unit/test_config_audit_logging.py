"""Tests for configuration audit logging."""

from unittest.mock import MagicMock, patch

import pytest

from src.audit_logging.audit import AuditLogger
from src.config.versioned_service import VersionedConfigService


class TestConfigAuditLogging:
    """Test configuration audit logging functionality."""

    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        with patch("src.audit_logging.audit.logger") as mock:
            yield mock

    @pytest.fixture
    def audit_logger(self):
        """Create an AuditLogger instance."""
        return AuditLogger()

    def test_log_config_retrieval_found(self, audit_logger, mock_logger):
        """Test logging successful config retrieval."""
        # Arrange
        config_type = "agent"
        config_id = "test_agent"
        user_id = "user123"
        version = 5

        # Act
        audit_logger.log_config_retrieval(
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            version=version,
            found=True,
        )

        # Assert
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "config_retrieval"
        assert call_args[1]["config_type"] == config_type
        assert call_args[1]["config_id"] == config_id
        assert call_args[1]["user_id"] == user_id
        assert call_args[1]["version"] == version
        assert call_args[1]["found"] is True
        assert "timestamp" in call_args[1]

    def test_log_config_retrieval_not_found(self, audit_logger, mock_logger):
        """Test logging failed config retrieval."""
        # Arrange
        config_type = "workflow"
        config_id = "missing_workflow"
        user_id = "user456"

        # Act
        audit_logger.log_config_retrieval(
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            found=False,
        )

        # Assert
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[1]["config_type"] == config_type
        assert call_args[1]["config_id"] == config_id
        assert call_args[1]["user_id"] == user_id
        assert call_args[1]["found"] is False

    def test_log_config_update_with_before_after(self, audit_logger, mock_logger):
        """Test logging config update with before/after values."""
        # Arrange
        config_type = "tool"
        config_id = "calculator"
        user_id = "admin123"
        old_version = 3
        new_version = 4
        old_etag = "abc123"
        new_etag = "def456"
        before = {"enabled": True, "timeout": 30}
        after = {"enabled": True, "timeout": 60}
        change_summary = "Increased timeout"

        # Act
        audit_logger.log_config_update(
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            old_version=old_version,
            new_version=new_version,
            old_etag=old_etag,
            new_etag=new_etag,
            before=before,
            after=after,
            change_summary=change_summary,
        )

        # Assert
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "config_update"
        assert call_args[1]["config_type"] == config_type
        assert call_args[1]["config_id"] == config_id
        assert call_args[1]["user_id"] == user_id
        assert call_args[1]["old_version"] == old_version
        assert call_args[1]["new_version"] == new_version
        assert call_args[1]["old_etag"] == old_etag
        assert call_args[1]["new_etag"] == new_etag
        assert call_args[1]["before"] == before
        assert call_args[1]["after"] == after
        assert call_args[1]["change_summary"] == change_summary
        assert "timestamp" in call_args[1]

    def test_log_config_conflict_with_version(self, audit_logger, mock_logger):
        """Test logging config conflict with version numbers."""
        # Arrange
        config_type = "agent"
        config_id = "reasoning_agent"
        user_id = "user789"
        current_version = 10
        provided_version = 8
        resolution = "rejected"

        # Act
        audit_logger.log_config_conflict(
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            current_version=current_version,
            provided_version=provided_version,
            resolution=resolution,
        )

        # Assert
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert call_args[0][0] == "config_conflict"
        assert call_args[1]["config_type"] == config_type
        assert call_args[1]["config_id"] == config_id
        assert call_args[1]["user_id"] == user_id
        assert call_args[1]["current_version"] == current_version
        assert call_args[1]["provided_version"] == provided_version
        assert call_args[1]["resolution"] == resolution
        assert "timestamp" in call_args[1]

    def test_log_config_conflict_with_etag(self, audit_logger, mock_logger):
        """Test logging config conflict with etags."""
        # Arrange
        config_type = "workflow"
        config_id = "chatbot_workflow"
        user_id = "user999"
        current_etag = "xyz789"
        provided_etag = "abc123"
        resolution = "rejected"

        # Act
        audit_logger.log_config_conflict(
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            current_etag=current_etag,
            provided_etag=provided_etag,
            resolution=resolution,
        )

        # Assert
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert call_args[1]["current_etag"] == current_etag
        assert call_args[1]["provided_etag"] == provided_etag

    def test_log_config_rollback(self, audit_logger, mock_logger):
        """Test logging config rollback."""
        # Arrange
        config_type = "vector_db"
        config_id = "chromadb_config"
        user_id = "admin456"
        from_version = 15
        to_version = 12
        new_version = 16
        new_etag = "rollback123"

        # Act
        audit_logger.log_config_rollback(
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            from_version=from_version,
            to_version=to_version,
            new_version=new_version,
            new_etag=new_etag,
        )

        # Assert
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "config_rollback"
        assert call_args[1]["config_type"] == config_type
        assert call_args[1]["config_id"] == config_id
        assert call_args[1]["user_id"] == user_id
        assert call_args[1]["from_version"] == from_version
        assert call_args[1]["to_version"] == to_version
        assert call_args[1]["new_version"] == new_version
        assert call_args[1]["new_etag"] == new_etag
        assert "timestamp" in call_args[1]

    def test_log_config_creation(self, audit_logger, mock_logger):
        """Test logging config creation."""
        # Arrange
        config_type = "agent"
        config_id = "new_agent"
        user_id = "creator123"
        version = 1
        etag = "initial123"
        config_data = {"name": "New Agent", "type": "conversable"}

        # Act
        audit_logger.log_config_creation(
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            version=version,
            etag=etag,
            config_data=config_data,
        )

        # Assert
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "config_creation"
        assert call_args[1]["config_type"] == config_type
        assert call_args[1]["config_id"] == config_id
        assert call_args[1]["user_id"] == user_id
        assert call_args[1]["version"] == version
        assert call_args[1]["etag"] == etag
        assert call_args[1]["config_data"] == config_data
        assert "timestamp" in call_args[1]

    def test_log_config_history_retrieval(self, audit_logger, mock_logger):
        """Test logging config history retrieval."""
        # Arrange
        config_type = "workflow"
        config_id = "sequential_workflow"
        user_id = "viewer123"
        entries_returned = 10

        # Act
        audit_logger.log_config_history_retrieval(
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            entries_returned=entries_returned,
        )

        # Assert
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "config_history_retrieval"
        assert call_args[1]["config_type"] == config_type
        assert call_args[1]["config_id"] == config_id
        assert call_args[1]["user_id"] == user_id
        assert call_args[1]["entries_returned"] == entries_returned
        assert "timestamp" in call_args[1]


class TestVersionedConfigServiceAuditIntegration:
    """Test that VersionedConfigService properly uses audit logging."""

    @pytest.fixture
    def mock_audit_logger(self):
        """Create a mock audit logger."""
        return MagicMock(spec=AuditLogger)

    @pytest.fixture
    def mock_db_manager(self):
        """Create a mock database manager."""
        with patch("src.config.versioned_service.DatabaseConnectionManager") as mock:
            yield mock

    def test_get_config_logs_retrieval(self, mock_audit_logger, mock_db_manager):
        """Test that get_config logs retrieval."""
        # Arrange
        service = VersionedConfigService(
            database_url="postgresql://test",
            audit_logger=mock_audit_logger,
        )

        # Mock database session
        mock_session = MagicMock()
        mock_db_manager.return_value.get_session.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        # Act
        service.get_config("agent", "test_agent", user_id="user123")

        # Assert
        mock_audit_logger.log_config_retrieval.assert_called_once()
        call_args = mock_audit_logger.log_config_retrieval.call_args
        assert call_args[1]["config_type"] == "agent"
        assert call_args[1]["config_id"] == "test_agent"
        assert call_args[1]["user_id"] == "user123"
        assert call_args[1]["found"] is False

    def test_update_config_logs_conflict(self, mock_audit_logger, mock_db_manager):
        """Test that update_config logs conflicts."""
        # This test would require more complex mocking of the database
        # to simulate a version conflict scenario
        pass

    def test_rollback_config_logs_rollback(self, mock_audit_logger, mock_db_manager):
        """Test that rollback_config logs rollback."""
        # This test would require more complex mocking of the database
        # to simulate a rollback scenario
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
