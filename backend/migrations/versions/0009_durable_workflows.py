"""Add durable workflow jobs and tenant-scoped LangGraph checkpoints.

Revision ID: 0009_durable_workflows
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_durable_workflows"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workflow_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_step", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workspace_id", "kind", "idempotency_key", name="uq_workflow_jobs_workspace_kind_key"),
    )
    op.create_index("ix_workflow_jobs_workspace_id", "workflow_jobs", ["workspace_id"])
    op.create_index("ix_workflow_jobs_requested_by_user_id", "workflow_jobs", ["requested_by_user_id"])
    op.create_index("ix_workflow_jobs_kind", "workflow_jobs", ["kind"])
    op.create_index("ix_workflow_jobs_status", "workflow_jobs", ["status"])
    op.create_index("ix_workflow_jobs_workspace_status_created", "workflow_jobs", ["workspace_id", "status", "created_at"])

    op.create_table(
        "workflow_checkpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("workflow_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread_id", sa.String(36), nullable=False),
        sa.Column("checkpoint_ns", sa.String(200), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.String(120), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(120), nullable=True),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "thread_id", "checkpoint_ns", "checkpoint_id",
                            name="uq_workflow_checkpoint_tenant_thread_id"),
    )
    op.create_index("ix_workflow_checkpoints_workspace_id", "workflow_checkpoints", ["workspace_id"])
    op.create_index("ix_workflow_checkpoints_job_id", "workflow_checkpoints", ["job_id"])
    op.create_index("ix_workflow_checkpoints_job", "workflow_checkpoints", ["workspace_id", "job_id"])

    op.create_table(
        "workflow_checkpoint_writes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("workflow_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread_id", sa.String(36), nullable=False),
        sa.Column("checkpoint_ns", sa.String(200), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.String(120), nullable=False),
        sa.Column("task_id", sa.String(120), nullable=False),
        sa.Column("task_path", sa.String(500), nullable=False, server_default=""),
        sa.Column("write_index", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(120), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.UniqueConstraint("workspace_id", "thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "write_index",
                            name="uq_workflow_checkpoint_write_key"),
    )
    op.create_index("ix_workflow_checkpoint_writes_workspace_id", "workflow_checkpoint_writes", ["workspace_id"])
    op.create_index("ix_workflow_checkpoint_writes_job_id", "workflow_checkpoint_writes", ["job_id"])
    op.create_index("ix_workflow_checkpoint_writes_scope", "workflow_checkpoint_writes",
                    ["workspace_id", "thread_id", "checkpoint_ns", "checkpoint_id"])

    op.add_column("investigation_runs", sa.Column("job_id", sa.String(36), nullable=True))
    op.create_index("ix_investigation_runs_job_id", "investigation_runs", ["job_id"], unique=True)


def downgrade():
    op.drop_index("ix_investigation_runs_job_id", table_name="investigation_runs")
    op.drop_column("investigation_runs", "job_id")
    op.drop_table("workflow_checkpoint_writes")
    op.drop_table("workflow_checkpoints")
    op.drop_table("workflow_jobs")
