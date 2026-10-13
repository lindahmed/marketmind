"""Add tenant-scoped source imports and canonical business events.

Revision ID: 0011_trusted_data_sources
Revises: 0010_fixed_cost_reporting
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_trusted_data_sources"
down_revision = "0010_fixed_cost_reporting"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("source_identifier", sa.String(200), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("sync_status", sa.String(20), nullable=False, server_default="never"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "provider", "source_identifier",
                            name="uq_data_source_workspace_provider_identifier"),
    )
    op.create_index("ix_data_sources_workspace_id", "data_sources", ["workspace_id"])
    op.create_table(
        "data_import_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", sa.String(120), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("received_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(60)),
        sa.UniqueConstraint("source_id", "request_id", name="uq_data_import_source_request"),
    )
    op.create_index("ix_data_import_runs_workspace_id", "data_import_runs", ["workspace_id"])
    op.create_index("ix_data_import_runs_source_id", "data_import_runs", ["source_id"])
    op.create_table(
        "business_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("import_run_id", sa.String(36), sa.ForeignKey("data_import_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_event_id", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(160)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2)),
        sa.Column("currency", sa.String(3)),
        sa.Column("status_value", sa.String(40)),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cost_category", sa.String(30)),
        sa.Column("campaign_id", sa.String(160)),
        sa.Column("channel", sa.String(80)),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("record_hash", sa.String(64), nullable=False),
        sa.Column("reconciliation_status", sa.String(20), nullable=False),
        sa.Column("reconciliation_note", sa.String(200)),
        sa.Column("matched_event_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("workspace_id", "source_id", "import_run_id", "occurred_at", "reconciliation_status"):
        op.create_index(f"ix_business_events_{column}", "business_events", [column])
    op.create_index("ix_business_events_workspace_time", "business_events", ["workspace_id", "occurred_at"])
    op.create_index("ix_business_events_reconcile", "business_events", ["workspace_id", "event_type", "entity_id"])


def downgrade():
    op.drop_table("business_events")
    op.drop_table("data_import_runs")
    op.drop_table("data_sources")
