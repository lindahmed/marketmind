"""Persist authenticated callback receipts, deterministic evaluations and private learning."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def workspace_column():
    return sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)


def created_column():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)


def upgrade():
    op.create_table("n8n_callback_receipts",
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("callback_id", sa.String(120), nullable=False, unique=True), workspace_column(),
                    sa.Column("experiment_id", sa.String(36), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("dispatch_id", sa.String(36), sa.ForeignKey("n8n_dispatches.id", ondelete="CASCADE"), nullable=False, unique=True),
                    sa.Column("event_type", sa.String(60), nullable=False),
                    sa.Column("payload_hash", sa.String(64), nullable=False),
                    sa.Column("payload", sa.JSON(), nullable=False),
                    sa.Column("received_at", sa.DateTime(timezone=True), nullable=False))
    for column in ("workspace_id", "experiment_id", "dispatch_id"):
        op.create_index(f"ix_n8n_callback_receipts_{column}", "n8n_callback_receipts", [column])

    op.create_table("experiment_evaluations",
                    sa.Column("id", sa.String(36), primary_key=True), workspace_column(),
                    sa.Column("experiment_id", sa.String(36), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("callback_receipt_id", sa.String(36), sa.ForeignKey("n8n_callback_receipts.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("outcome", sa.String(40), nullable=False), sa.Column("report", sa.JSON(), nullable=False), created_column(),
                    sa.UniqueConstraint("experiment_id"), sa.UniqueConstraint("callback_receipt_id"))
    for column in ("workspace_id", "experiment_id", "callback_receipt_id"):
        op.create_index(f"ix_experiment_evaluations_{column}", "experiment_evaluations", [column])

    op.create_table("experiment_learnings",
                    sa.Column("id", sa.String(36), primary_key=True), workspace_column(),
                    sa.Column("experiment_id", sa.String(36), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("evaluation_id", sa.String(36), sa.ForeignKey("experiment_evaluations.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("content", sa.JSON(), nullable=False), created_column(),
                    sa.UniqueConstraint("experiment_id"), sa.UniqueConstraint("evaluation_id"))
    for column in ("workspace_id", "experiment_id", "evaluation_id"):
        op.create_index(f"ix_experiment_learnings_{column}", "experiment_learnings", [column])


def downgrade():
    op.drop_table("experiment_learnings")
    op.drop_table("experiment_evaluations")
    op.drop_table("n8n_callback_receipts")
