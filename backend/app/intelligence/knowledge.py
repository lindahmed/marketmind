import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intelligence.contracts import BusinessContext
from app.models import KnowledgeChunk


class PgVectorRetriever:
    """Tenant filtering happens in SQL before results leave the database."""

    def __init__(self, db: Session):
        self.db = db

    def search(self, context: BusinessContext, embedding: list[float], limit: int = 5,
               model_id: str | None = None) -> list[dict]:
        if (len(embedding) != 1536 or not all(math.isfinite(value) for value in embedding)
                or not 0 < math.hypot(*embedding) < float("inf")):
            raise ValueError("Expected 1536 finite embedding values")
        if not 1 <= limit <= 50:
            raise ValueError("Retrieval limit must be between 1 and 50")
        distance = KnowledgeChunk.embedding.cosine_distance(embedding)
        query = select(KnowledgeChunk, distance.label("distance")).where(
            KnowledgeChunk.workspace_id == context.workspace_id,
            KnowledgeChunk.embedding.is_not(None),
        ).order_by(distance).limit(limit)
        if model_id:
            query = query.where(KnowledgeChunk.embedding_model == model_id, KnowledgeChunk.document_id.is_not(None))
        return [{"id": row.id, "document_id": row.document_id, "source": row.source,
                 "content": row.content, "distance": float(score)}
                for row, score in self.db.execute(query)]
