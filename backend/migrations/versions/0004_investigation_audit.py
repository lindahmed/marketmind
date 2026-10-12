"""Persist investigation pricing provenance and tenant audit events."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("investigation_runs", sa.Column("cost_schedule", sa.String(40), nullable=True))
    op.create_table("audit_events",
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
                    sa.Column("action", sa.String(80), nullable=False),
                    sa.Column("resource_type", sa.String(40), nullable=False),
                    sa.Column("resource_id", sa.String(36), nullable=True),
                    sa.Column("details", sa.JSON(), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_audit_events_workspace_id", "audit_events", ["workspace_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])


def downgrade():
    op.drop_table("audit_events")
    op.drop_column("investigation_runs", "cost_schedule")
