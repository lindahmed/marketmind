"""Add raw revision state, conflict decisions, and explicit coverage.

Revision ID: 0012_reconciliation_state
Revises: 0011_trusted_data_sources
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_reconciliation_state"
down_revision = "0011_trusted_data_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("data_import_runs", sa.Column("deleted_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("business_events", sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("business_events", sa.Column("supersedes_event_id", sa.String(36)))
    op.add_column("business_events", sa.Column("current_key", sa.String(400)))
    op.create_index("ix_business_events_is_current", "business_events", ["is_current"])
    op.create_index("uq_business_events_current_key", "business_events", ["workspace_id", "current_key"],
                    unique=True, sqlite_where=sa.text("current_key IS NOT NULL AND is_current = 1"),
                    postgresql_where=sa.text("current_key IS NOT NULL AND is_current = true"))
    op.create_table(
        "reconciliation_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conflict_event_id", sa.String(36), sa.ForeignKey("business_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("selected_event_id", sa.String(36), sa.ForeignKey("business_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decided_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("workspace_id", "conflict_event_id", "selected_event_id"):
        op.create_index(f"ix_reconciliation_decisions_{column}", "reconciliation_decisions", [column])
    op.create_table(
        "data_coverage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("import_run_id", sa.String(36), sa.ForeignKey("data_import_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("data_kind", sa.String(40), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("workspace_id", "source_id", "import_run_id"):
        op.create_index(f"ix_data_coverage_{column}", "data_coverage", [column])
    op.create_index("uq_data_coverage_current_source_day_kind", "data_coverage",
                    ["workspace_id", "source_id", "day", "data_kind"], unique=True,
                    sqlite_where=sa.text("is_current = 1"), postgresql_where=sa.text("is_current = true"))


def downgrade():
    op.drop_table("data_coverage")
    op.drop_table("reconciliation_decisions")
    op.drop_index("uq_business_events_current_key", table_name="business_events")
    op.drop_index("ix_business_events_is_current", table_name="business_events")
    op.drop_column("business_events", "current_key")
    op.drop_column("business_events", "supersedes_event_id")
    op.drop_column("business_events", "is_current")
    op.drop_column("data_import_runs", "deleted_count")
