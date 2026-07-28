"""Versioned configuration service with optimistic locking support."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import delete, desc, inspect, select

from src.audit_logging.audit import AuditLogger
from src.infrastructure.database.connection import DatabaseConnectionManager
from src.infrastructure.database.schema import ConfigSnapshot


@dataclass
class ConfigVersion:
    """Configuration version metadata."""

    version: int
    etag: str
    last_updated: datetime
    updated_by: Optional[str]


@dataclass
class ConflictResponse:
    """Response when a configuration conflict is detected."""

    status: str = "conflict"
    current_version: int = 0
    current_etag: str = ""
    current_config: dict = None
    provided_version: Optional[int] = None
    provided_etag: Optional[str] = None
    diff: dict = None


class VersionedConfigService:
    """
    Service for managing versioned configurations with optimistic locking.
    
    Provides version token generation, conflict detection, configuration history,
    and rollback functionality for all configuration types (agents, workflows, tools).
    """

    def __init__(
        self,
        database_url: str,
        audit_logger: Optional[AuditLogger] = None,
        max_snapshots: int = 50,
    ):
        """
        Initialize versioned config service.

        Args:
            database_url: PostgreSQL connection string
            audit_logger: Optional audit logger for tracking changes
            max_snapshots: Maximum number of snapshots to retain per config
        """
        self.db_manager = DatabaseConnectionManager(database_url=database_url)
        self.audit_logger = audit_logger or AuditLogger()
        self.max_snapshots = max_snapshots

    def is_available(self) -> bool:
        """Return whether the versioning backend schema is available."""
        try:
            return inspect(self.db_manager.engine).has_table(ConfigSnapshot.__tablename__)
        except Exception:
            return False

    def generate_etag(self, config_data: dict) -> str:
        """
        Generate SHA256 hash of configuration content.

        Args:
            config_data: Configuration dictionary

        Returns:
            SHA256 hash as hex string
        """
        # Sort keys for consistent hashing
        config_json = json.dumps(config_data, sort_keys=True)
        return hashlib.sha256(config_json.encode()).hexdigest()

    def get_config(
        self,
        config_type: str,
        config_id: str,
        user_id: Optional[str] = None,
    ) -> tuple[Optional[dict], Optional[ConfigVersion]]:
        """
        Get configuration with version token.

        Args:
            config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
            config_id: Configuration identifier
            user_id: Optional user ID for audit logging

        Returns:
            Tuple of (config_data, version_info) or (None, None) if not found
        """
        with self.db_manager.get_session() as db_session:
            # Get latest snapshot
            stmt = (
                select(ConfigSnapshot)
                .where(
                    ConfigSnapshot.config_type == config_type,
                    ConfigSnapshot.config_id == config_id,
                )
                .order_by(desc(ConfigSnapshot.version))
                .limit(1)
            )
            snapshot = db_session.execute(stmt).scalar_one_or_none()

            if snapshot is None:
                # Log retrieval attempt
                self.audit_logger.log_config_retrieval(
                    config_type=config_type,
                    config_id=config_id,
                    user_id=user_id,
                    found=False,
                )
                return None, None

            version_info = ConfigVersion(
                version=snapshot.version,
                etag=snapshot.etag,
                last_updated=snapshot.created_at,
                updated_by=snapshot.updated_by,
            )

            # Log successful retrieval
            self.audit_logger.log_config_retrieval(
                config_type=config_type,
                config_id=config_id,
                user_id=user_id,
                version=snapshot.version,
                found=True,
            )

            return snapshot.config_data, version_info

    def update_config(
        self,
        config_type: str,
        config_id: str,
        updates: dict,
        version_token: Optional[str] = None,
        user_id: Optional[str] = None,
        change_summary: Optional[str] = None,
    ) -> tuple[bool, Optional[str], Optional[dict]]:
        """
        Update configuration with optimistic locking.

        Args:
            config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
            config_id: Configuration identifier
            updates: New configuration data
            version_token: Version token (etag or version number as string)
            user_id: Optional user ID for audit logging
            change_summary: Optional summary of changes

        Returns:
            Tuple of (success, new_etag_or_error, conflict_response)
            - If success: (True, new_etag, None)
            - If conflict: (False, None, ConflictResponse)
            - If not found: (False, "not_found", None)
        """
        with self.db_manager.get_session() as db_session:
            # Get current config
            current_config, current_version = self.get_config(
                config_type, config_id, user_id
            )

            # Check if config exists
            if current_config is None:
                # Create new config if it doesn't exist
                new_etag = self.generate_etag(updates)
                new_snapshot = ConfigSnapshot(
                    config_type=config_type,
                    config_id=config_id,
                    version=1,
                    etag=new_etag,
                    config_data=updates,
                    created_at=datetime.utcnow(),
                    updated_by=str(user_id) if user_id else None,
                    change_summary=change_summary or "Initial configuration",
                )
                db_session.add(new_snapshot)
                db_session.commit()

                # Log creation
                self.audit_logger.log_config_creation(
                    config_type=config_type,
                    config_id=config_id,
                    user_id=user_id,
                    version=1,
                    etag=new_etag,
                    config_data=updates,
                )

                return True, new_etag, None

            # Validate version token if provided
            if version_token:
                # Check if token is etag or version number
                if version_token.isdigit():
                    provided_version = int(version_token)
                    if provided_version != current_version.version:
                        # Version conflict
                        diff = self._compute_diff(current_config, updates)
                        conflict = ConflictResponse(
                            status="conflict",
                            current_version=current_version.version,
                            current_etag=current_version.etag,
                            current_config=current_config,
                            provided_version=provided_version,
                            diff=diff,
                        )

                        # Log conflict
                        self.audit_logger.log_config_conflict(
                            config_type=config_type,
                            config_id=config_id,
                            user_id=user_id,
                            current_version=current_version.version,
                            provided_version=provided_version,
                            resolution="rejected",
                        )

                        return False, None, conflict.__dict__
                else:
                    # Token is etag
                    if version_token != current_version.etag:
                        # Etag conflict
                        diff = self._compute_diff(current_config, updates)
                        conflict = ConflictResponse(
                            status="conflict",
                            current_version=current_version.version,
                            current_etag=current_version.etag,
                            current_config=current_config,
                            provided_etag=version_token,
                            diff=diff,
                        )

                        # Log conflict
                        self.audit_logger.log_config_conflict(
                            config_type=config_type,
                            config_id=config_id,
                            user_id=user_id,
                            current_etag=current_version.etag,
                            provided_etag=version_token,
                            resolution="rejected",
                        )

                        return False, None, conflict.__dict__

            # No conflict, proceed with update
            new_version = current_version.version + 1
            new_etag = self.generate_etag(updates)

            # Create snapshot
            new_snapshot = ConfigSnapshot(
                config_type=config_type,
                config_id=config_id,
                version=new_version,
                etag=new_etag,
                config_data=updates,
                created_at=datetime.utcnow(),
                updated_by=str(user_id) if user_id else None,
                change_summary=change_summary,
            )
            db_session.add(new_snapshot)

            # Apply retention policy
            self._apply_retention_policy(db_session, config_type, config_id)

            db_session.commit()

            # Log successful update
            self.audit_logger.log_config_update(
                config_type=config_type,
                config_id=config_id,
                user_id=user_id,
                old_version=current_version.version,
                new_version=new_version,
                old_etag=current_version.etag,
                new_etag=new_etag,
                before=current_config,
                after=updates,
                change_summary=change_summary,
            )

            return True, new_etag, None

    def get_config_history(
        self,
        config_type: str,
        config_id: str,
        limit: int = 10,
        user_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Get configuration change history.

        Args:
            config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
            config_id: Configuration identifier
            limit: Maximum number of history entries to return
            user_id: Optional user ID for audit logging

        Returns:
            List of history entries with version, timestamp, user, and summary
        """
        with self.db_manager.get_session() as db_session:
            stmt = (
                select(ConfigSnapshot)
                .where(
                    ConfigSnapshot.config_type == config_type,
                    ConfigSnapshot.config_id == config_id,
                )
                .order_by(desc(ConfigSnapshot.version))
                .limit(limit)
            )
            snapshots = db_session.execute(stmt).scalars().all()

            history = [
                {
                    "version": snapshot.version,
                    "etag": snapshot.etag,
                    "created_at": snapshot.created_at.isoformat(),
                    "updated_by": snapshot.updated_by,
                    "change_summary": snapshot.change_summary,
                    "config_data": snapshot.config_data,
                }
                for snapshot in snapshots
            ]

            # Log history retrieval
            self.audit_logger.log_config_history_retrieval(
                config_type=config_type,
                config_id=config_id,
                user_id=user_id,
                entries_returned=len(history),
            )

            return history

    def rollback_config(
        self,
        config_type: str,
        config_id: str,
        target_version: int,
        user_id: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Rollback configuration to a previous version.

        Args:
            config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
            config_id: Configuration identifier
            target_version: Version number to rollback to
            user_id: Optional user ID for audit logging

        Returns:
            Tuple of (success, new_etag_or_error)
        """
        with self.db_manager.get_session() as db_session:
            # Get target snapshot
            stmt = select(ConfigSnapshot).where(
                ConfigSnapshot.config_type == config_type,
                ConfigSnapshot.config_id == config_id,
                ConfigSnapshot.version == target_version,
            )
            target_snapshot = db_session.execute(stmt).scalar_one_or_none()

            if target_snapshot is None:
                return False, f"Version {target_version} not found"

            # Get current version
            current_config, current_version = self.get_config(
                config_type, config_id, user_id
            )

            if current_version is None:
                return False, "Configuration not found"

            # Create new snapshot with rolled back data
            new_version = current_version.version + 1
            new_etag = self.generate_etag(target_snapshot.config_data)

            rollback_snapshot = ConfigSnapshot(
                config_type=config_type,
                config_id=config_id,
                version=new_version,
                etag=new_etag,
                config_data=target_snapshot.config_data,
                created_at=datetime.utcnow(),
                updated_by=str(user_id) if user_id else None,
                change_summary=f"Rollback to version {target_version}",
            )
            db_session.add(rollback_snapshot)

            # Apply retention policy
            self._apply_retention_policy(db_session, config_type, config_id)

            db_session.commit()

            # Log rollback
            self.audit_logger.log_config_rollback(
                config_type=config_type,
                config_id=config_id,
                user_id=user_id,
                from_version=current_version.version,
                to_version=target_version,
                new_version=new_version,
                new_etag=new_etag,
            )

            return True, new_etag

    def _compute_diff(self, current: dict, proposed: dict) -> dict:
        """
        Compute difference between current and proposed configurations.

        Args:
            current: Current configuration
            proposed: Proposed configuration

        Returns:
            Dictionary with added, removed, and modified fields
        """
        diff = {"added": [], "removed": [], "modified": []}

        current_keys = set(current.keys())
        proposed_keys = set(proposed.keys())

        # Find added keys
        diff["added"] = list(proposed_keys - current_keys)

        # Find removed keys
        diff["removed"] = list(current_keys - proposed_keys)

        # Find modified keys
        for key in current_keys & proposed_keys:
            if current[key] != proposed[key]:
                diff["modified"].append(
                    {"field": key, "current": current[key], "proposed": proposed[key]}
                )

        return diff

    def _apply_retention_policy(
        self, db_session, config_type: str, config_id: str
    ) -> None:
        """
        Apply snapshot retention policy (keep last N versions).

        Args:
            db_session: Database session
            config_type: Type of config
            config_id: Configuration identifier
        """
        # Count snapshots
        count_stmt = select(ConfigSnapshot).where(
            ConfigSnapshot.config_type == config_type,
            ConfigSnapshot.config_id == config_id,
        )
        count = len(db_session.execute(count_stmt).scalars().all())

        if count > self.max_snapshots:
            # Get snapshots to delete (oldest ones)
            delete_count = count - self.max_snapshots
            stmt = (
                select(ConfigSnapshot.id)
                .where(
                    ConfigSnapshot.config_type == config_type,
                    ConfigSnapshot.config_id == config_id,
                )
                .order_by(ConfigSnapshot.version)
                .limit(delete_count)
            )
            ids_to_delete = db_session.execute(stmt).scalars().all()

            # Delete old snapshots
            delete_stmt = delete(ConfigSnapshot).where(
                ConfigSnapshot.id.in_(ids_to_delete)
            )
            db_session.execute(delete_stmt)

    def health_check(self) -> bool:
        """
        Check if database connection is healthy.

        Returns:
            True if connection is healthy, False otherwise
        """
        return self.db_manager.health_check()

    def close(self) -> None:
        """Close database connections and cleanup resources."""
        self.db_manager.close()
