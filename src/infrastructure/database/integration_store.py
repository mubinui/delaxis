"""SQL-backed store for external-integration OAuth credentials (e.g. Gmail).

Token blobs arrive already Fernet-encrypted (see src/infrastructure/secrets.py);
this store never sees plaintext tokens.
"""

from datetime import datetime
from uuid import UUID

import structlog

from src.infrastructure.database.connection import get_db_manager
from src.infrastructure.database.schema import IntegrationCredential

logger = structlog.get_logger(__name__)


class IntegrationStore:
    """CRUD operations for integration credentials on the SQL database."""

    def __init__(self) -> None:
        self._db = get_db_manager()

    def upsert_credential(
        self,
        provider: str,
        account_email: str,
        encrypted_token: str,
        scopes: list[str],
        token_expiry: datetime | None = None,
        user_id: UUID | None = None,
    ) -> IntegrationCredential:
        with self._db.get_session() as session:
            credential = (
                session.query(IntegrationCredential)
                .filter(
                    IntegrationCredential.provider == provider,
                    IntegrationCredential.account_email == account_email,
                )
                .one_or_none()
            )
            if credential is None:
                credential = IntegrationCredential(
                    provider=provider,
                    account_email=account_email,
                    encrypted_token=encrypted_token,
                    scopes=scopes,
                    token_expiry=token_expiry,
                    user_id=user_id,
                )
                session.add(credential)
            else:
                credential.encrypted_token = encrypted_token
                credential.scopes = scopes
                credential.token_expiry = token_expiry
                if user_id is not None:
                    credential.user_id = user_id
            session.flush()
            session.refresh(credential)
            session.expunge(credential)
            logger.info(
                "integration_credential_upserted",
                provider=provider,
                account_email=account_email,
            )
            return credential

    def get_credential(self, provider: str, account_email: str) -> IntegrationCredential | None:
        with self._db.get_session() as session:
            credential = (
                session.query(IntegrationCredential)
                .filter(
                    IntegrationCredential.provider == provider,
                    IntegrationCredential.account_email == account_email,
                )
                .one_or_none()
            )
            if credential:
                session.expunge(credential)
            return credential

    def list_credentials(self, provider: str) -> list[IntegrationCredential]:
        with self._db.get_session() as session:
            credentials = (
                session.query(IntegrationCredential)
                .filter(IntegrationCredential.provider == provider)
                .order_by(IntegrationCredential.created_at)
                .all()
            )
            for credential in credentials:
                session.expunge(credential)
            return credentials

    def delete_credential(self, provider: str, account_email: str) -> bool:
        with self._db.get_session() as session:
            deleted = (
                session.query(IntegrationCredential)
                .filter(
                    IntegrationCredential.provider == provider,
                    IntegrationCredential.account_email == account_email,
                )
                .delete()
            )
            if deleted:
                logger.info(
                    "integration_credential_deleted",
                    provider=provider,
                    account_email=account_email,
                )
            return bool(deleted)


_integration_store: IntegrationStore | None = None


def get_integration_store() -> IntegrationStore:
    """Get the singleton integration store instance."""
    global _integration_store
    if _integration_store is None:
        _integration_store = IntegrationStore()
    return _integration_store
