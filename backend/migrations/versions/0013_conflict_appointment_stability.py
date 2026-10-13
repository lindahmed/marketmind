"""Make reconciliation decisions single-shot and retain appointment lifecycle dates.

Revision ID: 0013_conflict_appointment_stability
Revises: 0012_reconciliation_state
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_conflict_appointment_stability"
down_revision = "0012_reconciliation_state"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("uq_reconciliation_decision_conflict", "reconciliation_decisions",
                    ["conflict_event_id"], unique=True)
    for column in ("booked_at", "scheduled_at", "completed_at"):
        op.add_column("business_events", sa.Column(column, sa.DateTime(timezone=True), nullable=True))


def downgrade():
    for column in ("completed_at", "scheduled_at", "booked_at"):
        op.drop_column("business_events", column)
    op.drop_index("uq_reconciliation_decision_conflict", table_name="reconciliation_decisions")
