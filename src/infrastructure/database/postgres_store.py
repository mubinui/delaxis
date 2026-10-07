"""PostgreSQL implementation of ConversationStore."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from src.infrastructure.database import schema
from src.infrastructure.database.connection import DatabaseConnectionManager
from src.memory.models import (
    AgentNote,
    ConversationState,
    Message,
)
from src.memory.store import ConversationStore


class PostgreSQLConversationStore(ConversationStore):
    """PostgreSQL-backed conversation store implementation."""

    def __init__(
        self,
        database_url: str,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
    ):
        """Initialize PostgreSQL conversation store.

        Args:
            database_url: PostgreSQL connection string
            pool_size: Number of connections to maintain in the pool
            max_overflow: Maximum number of connections to create beyond pool_size
            pool_timeout: Seconds to wait before giving up on getting a connection
            pool_recycle: Seconds after which to recycle connections
        """
        self.db_manager = DatabaseConnectionManager(
            database_url=database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
        )

    async def create_session(self) -> ConversationState:
        """Create a new conversation session.

        Returns:
            ConversationState: Newly created session
        """
        with self.db_manager.get_session() as db_session:
            # Create new session in database
            db_session_obj = schema.Session(
                turn_count=0,
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                session_metadata={},
            )
            db_session.add(db_session_obj)
            db_session.commit()
            db_session.refresh(db_session_obj)

            # Convert to ConversationState
            return self._db_session_to_conversation_state(db_session_obj)

    async def get_session(self, session_id: UUID) -> ConversationState | None:
        """Retrieve a conversation session by ID.

        Args:
            session_id: UUID of the session to retrieve

        Returns:
            ConversationState if found, None otherwise
        """
        with self.db_manager.get_session() as db_session:
            # Query session with messages and agent notes
            stmt = select(schema.Session).where(schema.Session.session_id == session_id)
            db_session_obj = db_session.execute(stmt).scalar_one_or_none()

            if db_session_obj is None:
                return None

            return self._db_session_to_conversation_state(db_session_obj)

    async def update_session(self, state: ConversationState) -> None:
        """Update an existing conversation session.

        Args:
            state: ConversationState to update
        """
        with self.db_manager.get_session() as db_session:
            # Get existing session
            stmt = select(schema.Session).where(schema.Session.session_id == state.session_id)
            db_session_obj = db_session.execute(stmt).scalar_one_or_none()

            if db_session_obj is None:
                raise ValueError(f"Session {state.session_id} not found")

            # Update session fields
            db_session_obj.turn_count = state.turn_count
            db_session_obj.active = state.active
            db_session_obj.updated_at = datetime.now(UTC)
            db_session_obj.session_metadata = state.metadata

            # Get existing message and note IDs
            existing_message_ids = {msg.id for msg in db_session_obj.messages}
            existing_note_ids = {note.id for note in db_session_obj.agent_notes}

            # Add new messages
            for message in state.messages:
                if message.id not in existing_message_ids:
                    db_message = schema.Message(
                        id=message.id,
                        session_id=state.session_id,
                        role=message.role,
                        content=message.content,
                        timestamp=message.timestamp,
                        message_metadata=message.metadata,
                    )
                    db_session.add(db_message)

            # Add new agent notes
            for note in state.agent_notes:
                if note.id not in existing_note_ids:
                    db_note = schema.AgentNote(
                        id=note.id,
                        session_id=state.session_id,
                        agent_type=note.agent_type,
                        note_type=note.note_type,
                        content=note.content,
                        timestamp=note.timestamp,
                        note_metadata=note.metadata,
                    )
                    db_session.add(db_note)

    async def delete_session(self, session_id: UUID) -> bool:
        """Delete a conversation session.

        Args:
            session_id: UUID of the session to delete

        Returns:
            True if session was deleted, False if not found
        """
        with self.db_manager.get_session() as db_session:
            stmt = select(schema.Session).where(schema.Session.session_id == session_id)
            db_session_obj = db_session.execute(stmt).scalar_one_or_none()

            if db_session_obj is None:
                return False

            db_session.delete(db_session_obj)
            return True

    async def list_sessions(self, active_only: bool = True) -> list[ConversationState]:
        """List all conversation sessions.

        Args:
            active_only: If True, only return active sessions

        Returns:
            List of ConversationState objects
        """
        with self.db_manager.get_session() as db_session:
            stmt = select(schema.Session)
            if active_only:
                stmt = stmt.where(schema.Session.active == True)  # noqa: E712

            stmt = stmt.order_by(schema.Session.updated_at.desc())
            db_sessions = db_session.execute(stmt).scalars().all()

            return [
                self._db_session_to_conversation_state(db_session_obj)
                for db_session_obj in db_sessions
            ]

    def _db_session_to_conversation_state(
        self, db_session_obj: schema.Session
    ) -> ConversationState:
        """Convert database Session to ConversationState.

        Args:
            db_session_obj: Database session object

        Returns:
            ConversationState object
        """
        # Convert messages
        messages = [
            Message(
                id=msg.id,
                role=msg.role,
                content=msg.content,
                timestamp=msg.timestamp,
                metadata=msg.message_metadata,
            )
            for msg in db_session_obj.messages
        ]

        # Convert agent notes
        agent_notes = [
            AgentNote(
                id=note.id,
                agent_type=note.agent_type,
                note_type=note.note_type,
                content=note.content,
                timestamp=note.timestamp,
                metadata=note.note_metadata,
            )
            for note in db_session_obj.agent_notes
        ]

        return ConversationState(
            session_id=db_session_obj.session_id,
            messages=messages,
            agent_notes=agent_notes,
            turn_count=db_session_obj.turn_count,
            active=db_session_obj.active,
            created_at=db_session_obj.created_at,
            updated_at=db_session_obj.updated_at,
            metadata=db_session_obj.session_metadata,
        )

    def health_check(self) -> bool:
        """Check if database connection is healthy.

        Returns:
            True if connection is healthy, False otherwise
        """
        return self.db_manager.health_check()

    def get_pool_status(self) -> dict:
        """Get current connection pool status.

        Returns:
            Dictionary with pool statistics
        """
        return self.db_manager.get_pool_status()

    def close(self) -> None:
        """Close database connections and cleanup resources."""
        self.db_manager.close()
