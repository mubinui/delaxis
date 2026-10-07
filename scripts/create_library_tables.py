#!/usr/bin/env python3
"""
Create database tables for the Library feature.

Usage:
    python scripts/create_library_tables.py
"""

import os
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Column, DateTime, Index, String, Text, create_engine
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class WorkflowDefinition(Base):
    """Database model for reusable workflow definitions."""

    __tablename__ = "workflow_definitions"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
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

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String(50), nullable=False)
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

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String(50), nullable=False)
    config = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_tool_defs_name", "name"),
        Index("idx_tool_defs_type", "type"),
    )


def main():
    # Load environment variables from .env file
    from pathlib import Path

    env_path = Path(__file__).parent.parent / ".env"

    if env_path.exists():
        from dotenv import load_dotenv

        load_dotenv(env_path)
        print(f"📝 Loaded environment from {env_path}")

    # Get database URL from environment
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        print("❌ DATABASE_URL environment variable is not set")
        print("   Please set it in your .env file or export it:")
        print("   export DATABASE_URL='postgresql://user:password@localhost:5432/dbname'")
        return 1

    # Convert asyncpg to psycopg2 if needed
    if "asyncpg" in database_url:
        database_url = database_url.replace("+asyncpg", "")
        print("   Note: Converted asyncpg URL to synchronous")

    print("🔌 Connecting to database...")
    print(f"   URL: {database_url.split('@')[1] if '@' in database_url else '(hidden)'}")

    try:
        # Create engine
        engine = create_engine(database_url)

        # Create all tables
        print("\n📋 Creating tables...")
        Base.metadata.create_all(engine)

        print("✅ Library tables created successfully!")
        print("\nCreated tables:")
        print("  - workflow_definitions")
        print("  - agent_definitions")
        print("  - tool_definitions")

        return 0

    except Exception as e:
        print(f"\n❌ Failed to create tables: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
