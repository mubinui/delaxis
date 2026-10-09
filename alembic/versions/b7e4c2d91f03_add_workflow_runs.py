"""add workflow_runs

Revision ID: b7e4c2d91f03
Revises: a3d9f10b7c42
Create Date: 2026-10-09 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7e4c2d91f03"
down_revision: Union[str, Sequence[str], None] = "a3d9f10b7c42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("agents_called", sa.JSON(), nullable=False),
        sa.Column("tools_called", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("replay_of", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("meta_data", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_workflow_runs_workflow_started", "workflow_runs", ["workflow_id", "started_at"]
    )
    op.create_index("idx_workflow_runs_started_at", "workflow_runs", ["started_at"])
    op.create_index("idx_workflow_runs_status", "workflow_runs", ["status"])
    op.create_index("idx_workflow_runs_session_id", "workflow_runs", ["session_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_workflow_runs_session_id", table_name="workflow_runs")
    op.drop_index("idx_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("idx_workflow_runs_started_at", table_name="workflow_runs")
    op.drop_index("idx_workflow_runs_workflow_started", table_name="workflow_runs")
    op.drop_table("workflow_runs")
