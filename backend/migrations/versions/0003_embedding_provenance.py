"""Record the provider/model/dimensions used for each chunk vector."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("knowledge_chunks", sa.Column("embedding_model", sa.String(120), nullable=True))
    op.create_index("ix_knowledge_chunks_embedding_model", "knowledge_chunks", ["embedding_model"])


def downgrade():
    op.drop_index("ix_knowledge_chunks_embedding_model", table_name="knowledge_chunks")
    op.drop_column("knowledge_chunks", "embedding_model")
