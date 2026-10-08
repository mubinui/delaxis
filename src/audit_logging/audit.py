"""Audit logging for conversation tracking and compliance."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.audit_logging.logger import get_logger
from src.memory.models import AgentType

logger = get_logger(__name__)


class AuditLogger:
    """Captures and logs auditable events for compliance and debugging."""

    def log_user_input(
        self, session_id: UUID, content: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Log user input to the conversation."""
        logger.info(
            "user_input",
            session_id=str(session_id),
            content=content,
            timestamp=datetime.now(UTC).isoformat(),
            metadata=metadata or {},
        )

    def log_agent_execution(
        self,
        session_id: UUID,
        agent_type: AgentType,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log agent execution details."""
        logger.info(
            "agent_execution",
            session_id=str(session_id),
            agent_type=agent_type.value,
            action=action,
            timestamp=datetime.now(UTC).isoformat(),
            details=details or {},
        )

    def log_llm_call(
        self,
        session_id: UUID,
        model: str,
        prompt: str,
        response: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log LLM API calls."""
        logger.info(
            "llm_call",
            session_id=str(session_id),
            model=model,
            prompt=prompt,
            response=response,
            timestamp=datetime.now(UTC).isoformat(),
            metadata=metadata or {},
        )

    def log_safety_check(
        self,
        session_id: UUID,
        content: str,
        passed: bool,
        safeguard_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log safety check results."""
        logger.info(
            "safety_check",
            session_id=str(session_id),
            content=content,
            passed=passed,
            timestamp=datetime.now(UTC).isoformat(),
            safeguard_metadata=safeguard_metadata or {},
        )

    def log_error(
        self,
        session_id: UUID,
        error_type: str,
        error_message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Log errors and exceptions."""
        logger.error(
            "error",
            session_id=str(session_id),
            error_type=error_type,
            error_message=error_message,
            timestamp=datetime.now(UTC).isoformat(),
            context=context or {},
        )

    def log_session_lifecycle(
        self, session_id: UUID, event: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Log session lifecycle events (creation, completion, timeout)."""
        logger.info(
            "session_lifecycle",
            session_id=str(session_id),
            lifecycle_event=event,
            timestamp=datetime.now(UTC).isoformat(),
            metadata=metadata or {},
        )

    def log_assistant_response(
        self, session_id: UUID, content: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Log assistant responses sent to users."""
        logger.info(
            "assistant_response",
            session_id=str(session_id),
            content=content,
            timestamp=datetime.now(UTC).isoformat(),
            metadata=metadata or {},
        )

    def log_config_retrieval(
        self,
        config_type: str,
        config_id: str,
        user_id: str | UUID | None = None,
        version: int | None = None,
        found: bool = True,
    ) -> None:
        """
        Log configuration retrieval.

        Args:
            config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
            config_id: Configuration identifier
            user_id: User who retrieved the config
            version: Version number retrieved
            found: Whether the config was found
        """
        logger.info(
            "config_retrieval",
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            version=version,
            found=found,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def log_config_update(
        self,
        config_type: str,
        config_id: str,
        user_id: str | UUID | None = None,
        old_version: int | None = None,
        new_version: int | None = None,
        old_etag: str | None = None,
        new_etag: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        change_summary: str | None = None,
    ) -> None:
        """
        Log configuration update with before/after values.

        Args:
            config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
            config_id: Configuration identifier
            user_id: User who updated the config
            old_version: Previous version number
            new_version: New version number
            old_etag: Previous etag
            new_etag: New etag
            before: Configuration before update
            after: Configuration after update
            change_summary: Summary of changes
        """
        logger.info(
            "config_update",
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
            timestamp=datetime.now(UTC).isoformat(),
        )

    def log_config_conflict(
        self,
        config_type: str,
        config_id: str,
        user_id: str | UUID | None = None,
        current_version: int | None = None,
        provided_version: int | None = None,
        current_etag: str | None = None,
        provided_etag: str | None = None,
        resolution: str = "rejected",
    ) -> None:
        """
        Log configuration conflict with resolution action.

        Args:
            config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
            config_id: Configuration identifier
            user_id: User who attempted the update
            current_version: Current version number
            provided_version: Version number provided by user
            current_etag: Current etag
            provided_etag: Etag provided by user
            resolution: Resolution action ('rejected', 'merged', 'overridden')
        """
        logger.warning(
            "config_conflict",
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            current_version=current_version,
            provided_version=provided_version,
            current_etag=current_etag,
            provided_etag=provided_etag,
            resolution=resolution,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def log_config_rollback(
        self,
        config_type: str,
        config_id: str,
        user_id: str | UUID | None = None,
        from_version: int | None = None,
        to_version: int | None = None,
        new_version: int | None = None,
        new_etag: str | None = None,
    ) -> None:
        """
        Log configuration rollback with target version.

        Args:
            config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
            config_id: Configuration identifier
            user_id: User who performed the rollback
            from_version: Version being rolled back from
            to_version: Target version to rollback to
            new_version: New version number after rollback
            new_etag: New etag after rollback
        """
        logger.info(
            "config_rollback",
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            from_version=from_version,
            to_version=to_version,
            new_version=new_version,
            new_etag=new_etag,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def log_config_creation(
        self,
        config_type: str,
        config_id: str,
        user_id: str | UUID | None = None,
        version: int = 1,
        etag: str | None = None,
        config_data: dict[str, Any] | None = None,
    ) -> None:
        """
        Log configuration creation.

        Args:
            config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
            config_id: Configuration identifier
            user_id: User who created the config
            version: Initial version number
            etag: Initial etag
            config_data: Initial configuration data
        """
        logger.info(
            "config_creation",
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            version=version,
            etag=etag,
            config_data=config_data,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def log_config_history_retrieval(
        self,
        config_type: str,
        config_id: str,
        user_id: str | UUID | None = None,
        entries_returned: int = 0,
    ) -> None:
        """
        Log configuration history retrieval.

        Args:
            config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
            config_id: Configuration identifier
            user_id: User who retrieved the history
            entries_returned: Number of history entries returned
        """
        logger.info(
            "config_history_retrieval",
            config_type=config_type,
            config_id=config_id,
            user_id=user_id,
            entries_returned=entries_returned,
            timestamp=datetime.now(UTC).isoformat(),
        )
