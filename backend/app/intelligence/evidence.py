from sqlalchemy.orm import Session

from app.analytics import dashboard
from app.intelligence.contracts import BusinessContext
from app.intelligence.documents import search_documents
from app.models import Workspace


class DataIntelligenceAgent:
    """Collect metric facts and matching private text for one verified tenant."""

    name = "data_intelligence"

    def investigate(self, db: Session, context: BusinessContext, question: str) -> dict:
        business = db.get(Workspace, context.workspace_id)
        if business is None:
            raise PermissionError("Workspace access denied")
        overview = dashboard(db, business, context.industry_pack)
        matches = search_documents(db, context, question, limit=8) if question.strip() else []
        findings = [{"kind": "industry_rule", "source_id": finding["code"], **finding}
                    for finding in overview["findings"]]
        findings += [{"kind": "private_document", "title": row["source"], "evidence": row["excerpt"],
                      "source_id": row["chunk_id"], "confidence": None} for row in matches]
        return {"industry": overview["industry"]["code"], "currency": overview["currency"],
                "kpis": overview["kpis"], "findings": findings,
                "evidence_sources": [{"id": row["chunk_id"], "document": row["source"], "score": row["score"]}
                                     for row in matches],
                "interpretation": "Evidence comes from this workspace's metrics and documents. A causal explanation is not established by retrieved matches or rule thresholds."}
