"""SQLAlchemy database schema for Delaxis.

All tables share one declarative Base so Alembic autogenerate sees the full
metadata. Column types are dialect-neutral: they work on SQLite (the
zero-config default) and PostgreSQL (the production option) alike.

Columns are declared in the SQLAlchemy 2.0 ``Mapped`` style so that a row's
attributes carry real Python types: a store can assign ``row.active = False``
and build a pydantic model from ``row.created_at`` without casts.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.memory.models import AgentType, MessageRole
from src.utils.time import utc_now_naive


class Base(DeclarativeBase):
    """Shared declarative base for every table."""


class Session(Base):
    """Database model for conversation sessions."""

    __tablename__ = "sessions"

    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive
    )
    session_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="session", cascade="all, delete-orphan"
    )
    agent_notes: Mapped[list["AgentNote"]] = relationship(
        "AgentNote", back_populates="session", cascade="all, delete-orphan"
    )

    # Indexes for performance
    __table_args__ = (
        Index("idx_sessions_active", "active"),
        Index("idx_sessions_created_at", "created_at"),
        Index("idx_sessions_updated_at", "updated_at"),
    )


class Message(Base):
    """Database model for conversation messages."""

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    message_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    session: Mapped["Session"] = relationship("Session", back_populates="messages")

    # Indexes for performance
    __table_args__ = (
        Index("idx_messages_session_id", "session_id"),
        Index("idx_messages_timestamp", "timestamp"),
        Index("idx_messages_role", "role"),
    )


class AgentNote(Base):
    """Database model for agent notes and decisions."""

    __tablename__ = "agent_notes"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_type: Mapped[AgentType] = mapped_column(Enum(AgentType), nullable=False)
    note_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    note_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    session: Mapped["Session"] = relationship("Session", back_populates="agent_notes")

    # Indexes for performance
    __table_args__ = (
        Index("idx_agent_notes_session_id", "session_id"),
        Index("idx_agent_notes_agent_type", "agent_type"),
        Index("idx_agent_notes_note_type", "note_type"),
        Index("idx_agent_notes_timestamp", "timestamp"),
    )


class User(Base):
    """Database model for local (non-Keycloak) user accounts."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # admin | user | readonly
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_users_username", "username"),
        Index("idx_users_active", "active"),
    )


class ApiKey(Base):
    """Database model for API keys used for programmatic access."""

    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_api_keys_key_hash", "key_hash"),
        Index("idx_api_keys_active", "active"),
        Index("idx_api_keys_user_id", "user_id"),
    )


class ConfigSnapshot(Base):
    """Database model for configuration snapshots."""

    __tablename__ = "config_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # 'agent', 'workflow', 'tool', 'vector_db'
    config_type: Mapped[str] = mapped_column(String(50), nullable=False)
    config_id: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    etag: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA256 hash
    config_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)  # User identity
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Indexes for performance
    __table_args__ = (
        Index("idx_config_snapshots_type_id", "config_type", "config_id"),
        Index("idx_config_snapshots_version", "config_type", "config_id", "version"),
        Index("idx_config_snapshots_created_at", "created_at"),
    )


class WorkflowDefinition(Base):
    """Database model for reusable workflow definitions."""

    __tablename__ = "workflow_definitions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stores the visual layout and node configuration
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive
    )

    __table_args__ = (
        Index("idx_workflow_defs_name", "name"),
        Index("idx_workflow_defs_updated_at", "updated_at"),
    )


class AgentDefinition(Base):
    """Database model for reusable agent templates."""

    __tablename__ = "agent_definitions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. 'assistant'
    # Stores the agent configuration (system message, llm config, etc)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive
    )

    __table_args__ = (
        Index("idx_agent_defs_name", "name"),
        Index("idx_agent_defs_type", "type"),
    )


class ToolDefinition(Base):
    """Database model for reusable tool configurations."""

    __tablename__ = "tool_definitions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'function' or 'api'
    # Stores execution details (api_url, headers, OR python entrypoint)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive
    )

    __table_args__ = (
        Index("idx_tool_defs_name", "name"),
        Index("idx_tool_defs_type", "type"),
    )


class IntegrationCredential(Base):
    """Encrypted OAuth credentials for external integrations (e.g. Gmail).

    The token blob is Fernet-encrypted JSON ({token, refresh_token, token_uri,
    scopes, expiry}); OAuth client id/secret stay in environment variables and
    are never stored here.
    """

    __tablename__ = "integration_credentials"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="gmail")
    account_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # A connection's display name: the GitLab username, the Jira display name,
    # the Gmail address. account_email stays for Gmail rows.
    account_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    auth_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="oauth")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive
    )

    __table_args__ = (
        Index("idx_integration_provider_email", "provider", "account_email", unique=True),
    )


class WorkflowTestCase(Base):
    """Database model for workflow test cases."""

    __tablename__ = "workflow_test_cases"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_message: Mapped[str] = mapped_column(Text, nullable=False)
    expected_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_tools: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    expected_output_contains: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    expected_output_pattern: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive
    )
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    results: Mapped[list["WorkflowTestResult"]] = relationship(
        "WorkflowTestResult", back_populates="test_case", cascade="all, delete-orphan"
    )


class WorkflowTestResult(Base):
    """Database model for workflow test results."""

    __tablename__ = "workflow_test_results"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    test_case_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workflow_test_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    actual_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actual_tools: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_trace: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    run_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workflow_test_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    meta_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    test_case: Mapped["WorkflowTestCase"] = relationship(
        "WorkflowTestCase", back_populates="results"
    )
    test_run: Mapped["WorkflowTestRun | None"] = relationship(
        "WorkflowTestRun", back_populates="results"
    )


class WorkflowTestRun(Base):
    """Database model for grouped test executions."""

    __tablename__ = "workflow_test_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # null = all workflows
    workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    run_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    results: Mapped[list["WorkflowTestResult"]] = relationship(
        "WorkflowTestResult", back_populates="test_run"
    )


class WorkflowRun(Base):
    """One execution of a workflow: what was asked, what ran, and every event it streamed.

    ``events`` holds the run's frames in the same shape the streaming endpoint
    sends them, so the Studio can play a recorded run back on the canvas through
    the code path it uses for a live one.
    """

    __tablename__ = "workflow_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # chat, stream, test, deployment, replay, ...: who started the run.
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="chat")
    # running, succeeded or failed.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_called: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    tools_called: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    replay_of: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("idx_workflow_runs_workflow_started", "workflow_id", "started_at"),
        Index("idx_workflow_runs_started_at", "started_at"),
        Index("idx_workflow_runs_status", "status"),
        Index("idx_workflow_runs_session_id", "session_id"),
    )
