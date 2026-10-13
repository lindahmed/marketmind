"""Add fixed cost reporting for estimated operating profit.

Revision ID: 0010_fixed_cost_reporting
Revises: 0009_durable_workflows
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_fixed_cost_reporting"
down_revision = "0009_durable_workflows"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("daily_metrics", sa.Column("fixed_costs", sa.Numeric(14, 2), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("daily_metrics", "fixed_costs")
