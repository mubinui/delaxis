"""SQLAlchemy database schema for Delaxis.

All tables share one declarative Base so Alembic autogenerate sees the full
metadata. Column types are dialect-neutral: they work on SQLite (the
zero-config default) and PostgreSQL (the production option) alike.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import declarative_base, relationship

from src.memory.models import AgentType, MessageRole

Base = declarative_base()


class Session(Base):
    """Database model for conversation sessions."""

    __tablename__ = "sessions"

    session_id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    turn_count = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    session_metadata = Column(JSON, nullable=False, default=dict)

    # Relationships
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    agent_notes = relationship("AgentNote", back_populates="session", cascade="all, delete-orphan")

    # Indexes for performance
    __table_args__ = (
        Index("idx_sessions_active", "active"),
        Index("idx_sessions_created_at", "created_at"),
        Index("idx_sessions_updated_at", "updated_at"),
    )


class Message(Base):
    """Database model for conversation messages."""

    __tablename__ = "messages"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(Enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    message_metadata = Column(JSON, nullable=False, default=dict)

    # Relationships
    session = relationship("Session", back_populates="messages")

    # Indexes for performance
    __table_args__ = (
        Index("idx_messages_session_id", "session_id"),
        Index("idx_messages_timestamp", "timestamp"),
        Index("idx_messages_role", "role"),
    )


class AgentNote(Base):
    """Database model for agent notes and decisions."""

    __tablename__ = "agent_notes"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_type = Column(Enum(AgentType), nullable=False)
    note_type = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    note_metadata = Column(JSON, nullable=False, default=dict)

    # Relationships
    session = relationship("Session", back_populates="agent_notes")

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

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    username = Column(String(255), nullable=False, unique=True)
    email = Column(String(255), nullable=True, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="user")  # admin | user | readonly
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_users_username", "username"),
        Index("idx_users_active", "active"),
    )


class ApiKey(Base):
    """Database model for API keys used for programmatic access."""

    __tablename__ = "api_keys"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    key_hash = Column(String(255), nullable=False, unique=True)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    role = Column(String(50), nullable=False, default="user")
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_api_keys_key_hash", "key_hash"),
        Index("idx_api_keys_active", "active"),
        Index("idx_api_keys_user_id", "user_id"),
    )


class ConfigSnapshot(Base):
    """Database model for configuration snapshots."""

    __tablename__ = "config_snapshots"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    config_type = Column(String(50), nullable=False)  # 'agent', 'workflow', 'tool', 'vector_db'
    config_id = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False)
    etag = Column(String(64), nullable=False)  # SHA256 hash
    config_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_by = Column(String(255), nullable=True)  # User identity
    change_summary = Column(Text, nullable=True)

    # Indexes for performance
    __table_args__ = (
        Index("idx_config_snapshots_type_id", "config_type", "config_id"),
        Index("idx_config_snapshots_version", "config_type", "config_id", "version"),
        Index("idx_config_snapshots_created_at", "created_at"),
    )


class WorkflowDefinition(Base):
    """Database model for reusable workflow definitions."""

    __tablename__ = "workflow_definitions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    # Stores the visual layout and node configuration
    config = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_workflow_defs_name", "name"),
        Index("idx_workflow_defs_updated_at", "updated_at"),
    )


class AgentDefinition(Base):
    """Database model for reusable agent templates."""

    __tablename__ = "agent_definitions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String(50), nullable=False)  # e.g., 'assistant', 'user_proxy'
    # Stores the agent configuration (system message, llm config, etc)
    config = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_defs_name", "name"),
        Index("idx_agent_defs_type", "type"),
    )


class ToolDefinition(Base):
    """Database model for reusable tool configurations."""

    __tablename__ = "tool_definitions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String(50), nullable=False)  # 'function' or 'api'
    # Stores execution details (api_url, headers, OR python entrypoint)
    config = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

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

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    provider = Column(String(50), nullable=False, default="gmail")
    account_email = Column(String(255), nullable=False)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    encrypted_token = Column(Text, nullable=False)
    scopes = Column(JSON, nullable=False, default=list)
    token_expiry = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_integration_provider_email", "provider", "account_email", unique=True),
    )


class WorkflowTestCase(Base):
    """Database model for workflow test cases."""

    __tablename__ = "workflow_test_cases"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    input_message = Column(Text, nullable=False)
    expected_agent = Column(String(255), nullable=True)
    expected_tools = Column(JSON, nullable=True)  # list[str]
    expected_output_contains = Column(JSON, nullable=True)  # list[str]
    expected_output_pattern = Column(String(500), nullable=True)
    timeout_seconds = Column(Integer, nullable=False, default=60)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String(255), nullable=True)
    meta_data = Column(JSON, nullable=False, default=dict)

    # Relationships
    results = relationship("WorkflowTestResult", back_populates="test_case", cascade="all, delete-orphan")


class WorkflowTestResult(Base):
    """Database model for workflow test results."""

    __tablename__ = "workflow_test_results"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    test_case_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("workflow_test_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_id = Column(String(255), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending")
    actual_response = Column(Text, nullable=True)
    actual_agent = Column(String(255), nullable=True)
    actual_tools = Column(JSON, nullable=True)  # list[str]
    execution_time_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    execution_trace = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    run_by = Column(String(255), nullable=True)
    run_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("workflow_test_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    meta_data = Column(JSON, nullable=False, default=dict)

    # Relationships
    test_case = relationship("WorkflowTestCase", back_populates="results")
    test_run = relationship("WorkflowTestRun", back_populates="results")


class WorkflowTestRun(Base):
    """Database model for grouped test executions."""

    __tablename__ = "workflow_test_runs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id = Column(String(255), nullable=True, index=True)  # null = all workflows
    name = Column(String(255), nullable=True)
    total_tests = Column(Integer, nullable=False, default=0)
    passed_tests = Column(Integer, nullable=False, default=0)
    failed_tests = Column(Integer, nullable=False, default=0)
    error_tests = Column(Integer, nullable=False, default=0)
    skipped_tests = Column(Integer, nullable=False, default=0)
    status = Column(String(50), nullable=False, default="pending")
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    run_by = Column(String(255), nullable=True)
    meta_data = Column(JSON, nullable=False, default=dict)

    # Relationships
    results = relationship("WorkflowTestResult", back_populates="test_run")
