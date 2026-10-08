"""PostgreSQL implementation of ConfigStore for Library (Workflows, Agents, Tools)."""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, select, update

from src.infrastructure.database import schema
from src.infrastructure.database.connection import DatabaseConnectionManager
from src.utils.time import utc_now_naive

LibraryItem = schema.WorkflowDefinition | schema.AgentDefinition | schema.ToolDefinition


class ConfigStore:
    """Store for managing reusable configuration definitions (Library)."""

    def __init__(
        self,
        database_url: str,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
    ):
        """Initialize ConfigStore.

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

    def _get_model_class(self, item_type: str) -> type[LibraryItem]:
        """Get SQLAlchemy model class based on item type."""
        if item_type == "workflow":
            return schema.WorkflowDefinition
        elif item_type == "agent":
            return schema.AgentDefinition
        elif item_type == "tool":
            return schema.ToolDefinition
        else:
            raise ValueError(f"Unknown item type: {item_type}")

    def create_item(
        self,
        item_type: str,
        name: str,
        config: dict[str, Any],
        description: str | None = None,
        **kwargs: Any,
    ) -> LibraryItem:
        """Create a new library item."""
        model_class = self._get_model_class(item_type)

        with self.db_manager.get_session() as session:
            item = model_class(
                name=name,
                description=description,
                config=config,
                created_at=utc_now_naive(),
                updated_at=utc_now_naive(),
                **kwargs,
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            return item

    def get_item(self, item_type: str, item_id: UUID) -> LibraryItem | None:
        """Get a library item by ID."""
        model_class = self._get_model_class(item_type)

        with self.db_manager.get_session() as session:
            stmt = select(model_class).where(model_class.id == item_id)
            return cast(LibraryItem | None, session.execute(stmt).scalar_one_or_none())

    def list_items(self, item_type: str) -> list[LibraryItem]:
        """List all library items of a specific type."""
        model_class = self._get_model_class(item_type)

        with self.db_manager.get_session() as session:
            stmt = select(model_class).order_by(model_class.updated_at.desc())
            return cast(list[LibraryItem], list(session.execute(stmt).scalars().all()))

    def update_item(
        self, item_type: str, item_id: UUID, updates: dict[str, Any]
    ) -> LibraryItem | None:
        """Update a library item."""
        model_class = self._get_model_class(item_type)

        with self.db_manager.get_session() as session:
            updates["updated_at"] = utc_now_naive()
            stmt = (
                update(model_class)
                .where(model_class.id == item_id)
                .values(**updates)
                .returning(model_class)
            )
            result = session.execute(stmt)
            session.commit()
            return cast(LibraryItem | None, result.scalar_one_or_none())

    def delete_item(self, item_type: str, item_id: UUID) -> bool:
        """Delete a library item."""
        model_class = self._get_model_class(item_type)

        with self.db_manager.get_session() as session:
            stmt = delete(model_class).where(model_class.id == item_id)
            result = cast(CursorResult[Any], session.execute(stmt))
            session.commit()
            return result.rowcount > 0

    def close(self) -> None:
        """Close database connections."""
        self.db_manager.close()
