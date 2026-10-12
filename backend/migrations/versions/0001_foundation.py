"""Initial tenant, account, analytics and private knowledge schema."""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("users", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("email", sa.String(254), nullable=False),
                    sa.Column("password_hash", sa.String(255), nullable=False))
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table("workspaces", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("name", sa.String(120), nullable=False),
                    sa.Column("industry", sa.String(50), nullable=False),
                    sa.Column("currency", sa.String(3), nullable=False),
                    sa.Column("monthly_budget", sa.Numeric(14, 2), nullable=False),
                    sa.Column("goals", sa.JSON(), nullable=False),
                    sa.Column("constraints", sa.JSON(), nullable=False),
                    sa.Column("description", sa.String(2000), nullable=False))
    op.create_table("memberships", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("role", sa.String(20), nullable=False),
                    sa.UniqueConstraint("user_id", "workspace_id"))
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_workspace_id", "memberships", ["workspace_id"])
    op.create_table("daily_metrics", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("day", sa.Date(), nullable=False), sa.Column("values", sa.JSON(), nullable=False),
                    sa.UniqueConstraint("workspace_id", "day"))
    op.create_index("ix_daily_metrics_workspace_id", "daily_metrics", ["workspace_id"])
    op.create_table("knowledge_chunks", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("source", sa.String(255), nullable=False), sa.Column("content", sa.String(), nullable=False),
                    sa.Column("embedding", Vector(1536) if postgres else sa.JSON(), nullable=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_knowledge_chunks_workspace_id", "knowledge_chunks", ["workspace_id"])


def downgrade():
    for table in ("knowledge_chunks", "daily_metrics", "memberships", "workspaces", "users"):
        op.drop_table(table)
