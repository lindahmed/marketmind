"""Tenant-owned text knowledge and evidence-backed investigation runs."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("knowledge_documents",
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("name", sa.String(255), nullable=False),
                    sa.Column("sha256", sa.String(64), nullable=False),
                    sa.Column("mime_type", sa.String(100), nullable=False),
                    sa.Column("character_count", sa.Integer(), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("workspace_id", "sha256"))
    op.create_index("ix_knowledge_documents_workspace_id", "knowledge_documents", ["workspace_id"])
    with op.batch_alter_table("knowledge_chunks") as batch:
        batch.add_column(sa.Column("document_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("position", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_knowledge_chunks_document_id_knowledge_documents", "knowledge_documents",
                                 ["document_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_knowledge_chunks_document_id", ["document_id"])
    op.create_table("investigation_runs",
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("question", sa.String(1000), nullable=False),
                    sa.Column("status", sa.String(30), nullable=False),
                    sa.Column("result", sa.JSON(), nullable=False),
                    sa.Column("model", sa.String(100), nullable=True),
                    sa.Column("prompt_version", sa.String(30), nullable=False),
                    sa.Column("input_tokens", sa.Integer(), nullable=True),
                    sa.Column("output_tokens", sa.Integer(), nullable=True),
                    sa.Column("estimated_cost_usd", sa.Numeric(12, 8), nullable=True),
                    sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_investigation_runs_workspace_id", "investigation_runs", ["workspace_id"])


def downgrade():
    op.drop_table("investigation_runs")
    with op.batch_alter_table("knowledge_chunks") as batch:
        batch.drop_index("ix_knowledge_chunks_document_id")
        batch.drop_constraint("fk_knowledge_chunks_document_id_knowledge_documents", type_="foreignkey")
        batch.drop_column("position")
        batch.drop_column("document_id")
    op.drop_table("knowledge_documents")
