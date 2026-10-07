"""Database connection management with pooling and health checks."""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import Pool

from src.config.settings import get_settings

logger = logging.getLogger(__name__)

# Global database connection manager
_db_manager: Optional["DatabaseConnectionManager"] = None


class DatabaseConnectionManager:
    """Manages database connections with pooling and health checks."""

    def __init__(
        self,
        database_url: str,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
        echo: bool = False,
    ):
        """Initialize database connection manager.

        Args:
            database_url: PostgreSQL connection string
            pool_size: Number of connections to maintain in the pool
            max_overflow: Maximum number of connections to create beyond pool_size
            pool_timeout: Seconds to wait before giving up on getting a connection
            pool_recycle: Seconds after which to recycle connections
            echo: Whether to log SQL statements
        """
        self.database_url = database_url
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        self.echo = echo

        self._engine: Engine | None = None
        self._session_factory: sessionmaker | None = None

    @property
    def engine(self) -> Engine:
        """Get or create the database engine.

        Returns:
            SQLAlchemy Engine instance
        """
        if self._engine is None:
            self._engine = self._create_engine()
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        """Get or create the session factory.

        Returns:
            SQLAlchemy sessionmaker instance
        """
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
                bind=self.engine,
            )
        return self._session_factory

    def _create_engine(self) -> Engine:
        """Create SQLAlchemy engine with connection pooling.

        Returns:
            Configured SQLAlchemy Engine
        """
        # SQLAlchemy create_engine requires a sync driver (e.g. psycopg2)
        # If the URL is configured for asyncpg (postgresql+asyncpg://), we need to maintain compatibility
        # by converting it to a standard postgresql:// URL which defaults to psycopg2
        sync_db_url = self.database_url
        if sync_db_url and sync_db_url.startswith("postgresql+asyncpg://"):
            sync_db_url = sync_db_url.replace("postgresql+asyncpg://", "postgresql://")

        if sync_db_url.startswith("sqlite"):
            # Ensure the parent directory of the SQLite file exists
            from pathlib import Path

            db_path = sync_db_url.replace("sqlite:///", "", 1)
            if db_path and db_path != ":memory:":
                Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
            # SQLite: no server-side pool; allow cross-thread use for FastAPI
            engine = create_engine(
                sync_db_url,
                connect_args={"check_same_thread": False},
                echo=self.echo,
            )
        else:
            engine = create_engine(
                sync_db_url,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_timeout=self.pool_timeout,
                pool_recycle=self.pool_recycle,
                pool_pre_ping=True,  # Enable connection health checks
                echo=self.echo,
            )

        # Register event listeners
        self._register_event_listeners(engine)

        logger.info(
            f"Database engine created with pool_size={self.pool_size}, "
            f"max_overflow={self.max_overflow}"
        )

        return engine

    def _register_event_listeners(self, engine: Engine) -> None:
        """Register SQLAlchemy event listeners for monitoring.

        Args:
            engine: SQLAlchemy Engine instance
        """

        @event.listens_for(engine, "connect")
        def receive_connect(dbapi_conn, connection_record):
            """Log when a new connection is created."""
            logger.debug("New database connection established")

        @event.listens_for(engine, "checkout")
        def receive_checkout(dbapi_conn, connection_record, connection_proxy):
            """Log when a connection is checked out from the pool."""
            logger.debug("Connection checked out from pool")

        @event.listens_for(engine, "checkin")
        def receive_checkin(dbapi_conn, connection_record):
            """Log when a connection is returned to the pool."""
            logger.debug("Connection returned to pool")

        @event.listens_for(Pool, "invalidate")
        def receive_invalidate(dbapi_conn, connection_record, exception):
            """Log when a connection is invalidated."""
            logger.warning(f"Connection invalidated: {exception}")

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Get a database session with automatic cleanup.

        Yields:
            SQLAlchemy Session instance

        Example:
            with db_manager.get_session() as session:
                session.query(Model).all()
        """
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def health_check(self) -> bool:
        """Check if database connection is healthy.

        Returns:
            True if connection is healthy, False otherwise
        """
        try:
            with self.get_session() as session:
                session.execute(text("SELECT 1"))
            logger.debug("Database health check passed")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    def get_pool_status(self) -> dict:
        """Get current connection pool status.

        Returns:
            Dictionary with pool statistics
        """
        pool = self.engine.pool
        return {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "total": pool.size() + pool.overflow(),
        }

    def close(self) -> None:
        """Close all database connections and dispose of the engine."""
        if self._engine is not None:
            logger.info("Closing database connections")
            self._engine.dispose()
            self._engine = None
            self._session_factory = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.close()


def get_db_manager() -> DatabaseConnectionManager:
    """Get or create the global database connection manager.

    Falls back to a local SQLite database when DATABASE_URL is unset, so the
    platform works out of the box with zero configuration.
    """
    global _db_manager
    if _db_manager is None:
        settings = get_settings()
        _db_manager = DatabaseConnectionManager(
            database_url=settings.database_url, echo=settings.app.log_level.upper() == "DEBUG"
        )
    return _db_manager


def reset_db_manager() -> None:
    """Reset the global connection manager (useful for tests)."""
    global _db_manager
    if _db_manager is not None:
        _db_manager.close()
        _db_manager = None


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for getting database sessions."""
    db_manager = get_db_manager()
    with db_manager.get_session() as session:
        yield session
