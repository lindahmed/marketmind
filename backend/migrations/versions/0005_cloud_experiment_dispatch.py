"""Persist owner approvals and idempotent Cloud webhook dispatches."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("experiments",
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("name", sa.String(120), nullable=False),
                    sa.Column("action_type", sa.String(40), nullable=False),
                    sa.Column("status", sa.String(30), nullable=False),
                    sa.Column("version", sa.Integer(), nullable=False),
                    sa.Column("metadata", sa.JSON(), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_experiments_workspace_id", "experiments", ["workspace_id"])
    op.create_index("ix_experiments_created_by_user_id", "experiments", ["created_by_user_id"])
    op.create_table("experiment_approvals",
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("experiment_id", sa.String(36), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("experiment_version", sa.Integer(), nullable=False),
                    sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("status", sa.String(20), nullable=False),
                    sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("experiment_id", "experiment_version"))
    for column in ("workspace_id", "experiment_id", "approved_by_user_id"):
        op.create_index(f"ix_experiment_approvals_{column}", "experiment_approvals", [column])
    op.create_table("n8n_dispatches",
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("experiment_id", sa.String(36), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("approval_id", sa.String(36), sa.ForeignKey("experiment_approvals.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("execution_id", sa.String(36), nullable=False, unique=True),
                    sa.Column("idempotency_key", sa.String(180), nullable=False, unique=True),
                    sa.Column("status", sa.String(30), nullable=False),
                    sa.Column("http_status", sa.Integer(), nullable=True),
                    sa.Column("failure_code", sa.String(60), nullable=True),
                    sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for column in ("workspace_id", "experiment_id", "approval_id", "status"):
        op.create_index(f"ix_n8n_dispatches_{column}", "n8n_dispatches", [column])


def downgrade():
    op.drop_table("n8n_dispatches")
    op.drop_table("experiment_approvals")
    op.drop_table("experiments")
