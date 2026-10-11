"""integration_credentials become connections

Revision ID: c4f1a8e2b6d0
Revises: b7e4c2d91f03
Create Date: 2026-10-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f1a8e2b6d0'
down_revision: Union[str, Sequence[str], None] = 'b7e4c2d91f03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('integration_credentials') as batch:
        batch.alter_column('account_email', existing_type=sa.String(length=255), nullable=True)
        batch.add_column(sa.Column('account_label', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('base_url', sa.String(length=500), nullable=True))
        batch.add_column(
            sa.Column('auth_kind', sa.String(length=20), nullable=False, server_default='oauth')
        )
        batch.add_column(sa.Column('options', sa.JSON(), nullable=False, server_default='{}'))
        batch.add_column(sa.Column('last_status', sa.String(length=20), nullable=True))
        batch.add_column(sa.Column('last_error', sa.Text(), nullable=True))
        batch.add_column(sa.Column('last_verified_at', sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE integration_credentials SET account_label = account_email "
        "WHERE account_label IS NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM integration_credentials WHERE account_email IS NULL")
    with op.batch_alter_table('integration_credentials') as batch:
        batch.drop_column('last_verified_at')
        batch.drop_column('last_error')
        batch.drop_column('last_status')
        batch.drop_column('options')
        batch.drop_column('auth_kind')
        batch.drop_column('base_url')
        batch.drop_column('account_label')
        batch.alter_column('account_email', existing_type=sa.String(length=255), nullable=False)
