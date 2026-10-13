"""Persist evidence-backed strategy, owner recommendation approvals and experiment designs."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def workspace_column():
    return sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)


def created_column():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)


def upgrade():
    op.create_table("growth_strategy_runs",
                    sa.Column("id", sa.String(36), primary_key=True), workspace_column(),
                    sa.Column("investigation_id", sa.String(36), sa.ForeignKey("investigation_runs.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("generation_key", sa.String(64), nullable=False),
                    sa.Column("context_snapshot", sa.JSON(), nullable=False),
                    sa.Column("source_type", sa.String(30), nullable=False),
                    sa.Column("model", sa.String(100), nullable=True),
                    sa.Column("prompt_version", sa.String(30), nullable=False),
                    sa.Column("input_tokens", sa.Integer(), nullable=True),
                    sa.Column("output_tokens", sa.Integer(), nullable=True),
                    sa.Column("estimated_cost_usd", sa.Numeric(12, 8), nullable=True),
                    sa.Column("cost_schedule", sa.String(40), nullable=True), created_column(),
                    sa.UniqueConstraint("workspace_id", "investigation_id", "generation_key"))
    for column in ("workspace_id", "investigation_id"):
        op.create_index(f"ix_growth_strategy_runs_{column}", "growth_strategy_runs", [column])
    op.create_table("growth_recommendations",
                    sa.Column("id", sa.String(36), primary_key=True), workspace_column(),
                    sa.Column("strategy_run_id", sa.String(36), sa.ForeignKey("growth_strategy_runs.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("candidate_key", sa.String(60), nullable=False),
                    sa.Column("version", sa.Integer(), nullable=False),
                    sa.Column("status", sa.String(30), nullable=False),
                    sa.Column("content", sa.JSON(), nullable=False), created_column(),
                    sa.UniqueConstraint("strategy_run_id", "candidate_key"))
    for column in ("workspace_id", "strategy_run_id"):
        op.create_index(f"ix_growth_recommendations_{column}", "growth_recommendations", [column])
    op.create_table("recommendation_approvals",
                    sa.Column("id", sa.String(36), primary_key=True), workspace_column(),
                    sa.Column("recommendation_id", sa.String(36), sa.ForeignKey("growth_recommendations.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("recommendation_version", sa.Integer(), nullable=False),
                    sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("constraints_acknowledged", sa.Boolean(), nullable=False),
                    sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("recommendation_id", "recommendation_version"))
    for column in ("workspace_id", "recommendation_id", "approved_by_user_id"):
        op.create_index(f"ix_recommendation_approvals_{column}", "recommendation_approvals", [column])
    op.create_table("experiment_designs",
                    sa.Column("id", sa.String(36), primary_key=True), workspace_column(),
                    sa.Column("experiment_id", sa.String(36), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, unique=True),
                    sa.Column("recommendation_id", sa.String(36), sa.ForeignKey("growth_recommendations.id", ondelete="RESTRICT"), nullable=False, unique=True),
                    sa.Column("recommendation_approval_id", sa.String(36), sa.ForeignKey("recommendation_approvals.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("experiment_version", sa.Integer(), nullable=False),
                    sa.Column("design", sa.JSON(), nullable=False), created_column())
    op.create_index("ix_experiment_designs_workspace_id", "experiment_designs", ["workspace_id"])


def downgrade():
    for table in ("experiment_designs", "recommendation_approvals", "growth_recommendations", "growth_strategy_runs"):
        op.drop_table(table)
