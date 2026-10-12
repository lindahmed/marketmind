import pytest
from sqlalchemy.dialects import postgresql

from app.industries import PACKS
from app.intelligence.contracts import BusinessContext
from app.intelligence.knowledge import PgVectorRetriever
from app.intelligence.workflow import ANALYSIS_STAGES, build_analysis_graph
from app.intelligence.context import verified_business_context
from app.intelligence.investigation import AnalysisOutput, InvestigationAgent, InvestigationError
from app.intelligence.investigation import OpenAIInvestigationProvider
import json
from app.integrations.n8n import N8nExecutor


def context(workspace_id="tenant-a"):
    return BusinessContext(workspace_id, PACKS["ecommerce"], ("Profit",), (), 100)


def test_shared_graph_preserves_private_context_and_stops_before_execution():
    visits = []

    def agent(name):
        def run(state):
            visits.append((name, state["context"].workspace_id))
            return {"evidence": state["evidence"] + [{"stage": name}]}
        return run

    graph = build_analysis_graph({name: agent(name) for name in ANALYSIS_STAGES})
    for tenant in ("tenant-a", "tenant-b"):
        state = graph.invoke({"context": context(tenant), "evidence": [], "recommendations": [],
                              "experiment": None, "approval_id": None})
        assert state["context"].workspace_id == tenant
        assert len(state["evidence"]) == 4
    assert visits == [(name, tenant) for tenant in ("tenant-a", "tenant-b") for name in ANALYSIS_STAGES]
    with pytest.raises(ValueError):
        build_analysis_graph({})


def test_retrieval_contains_sql_tenant_filter():
    class RecordingSession:
        def execute(self, statement):
            self.statement = statement
            return []

    session = RecordingSession()
    assert PgVectorRetriever(session).search(context(), [0.1] * 1536) == []
    compiled = session.statement.compile(dialect=postgresql.dialect())
    assert "knowledge_chunks.workspace_id =" in str(compiled)
    assert "tenant-a" in compiled.params.values()
    with pytest.raises(ValueError):
        PgVectorRetriever(session).search(context(), [1])
    PgVectorRetriever(session).search(context(), [0.1] * 1536, model_id="openai:text-embedding-3-small:1536")
    compiled = session.statement.compile(dialect=postgresql.dialect())
    assert "knowledge_chunks.embedding_model =" in str(compiled)
    assert "openai:text-embedding-3-small:1536" in compiled.params.values()


def test_execution_cannot_dispatch_without_approval(monkeypatch):
    class DenyApproval:
        def require_approved(self, workspace_id, experiment_id, approval_id):
            raise PermissionError("Approval not found in this workspace")

    def forbidden_network(*args, **kwargs):
        pytest.fail("Webhook must not be called without approval")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_network)
    executor = N8nExecutor("https://automation.example/webhook", "test-token", DenyApproval())
    with pytest.raises(PermissionError):
        executor.execute(context(), "experiment-a", "forged-approval")


def test_verified_context_requires_persisted_membership():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db import Base
    from app.models import Membership, User, Workspace

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            outsider = User(email="outsider@example.com", password_hash="test-only")
            workspace = Workspace(name="Private Store", industry="ecommerce")
            session.add_all([outsider, workspace])
            session.commit()
            with pytest.raises(PermissionError):
                verified_business_context(session, outsider, workspace.id)
            session.add(Membership(user_id=outsider.id, workspace_id=workspace.id))
            session.commit()
            assert verified_business_context(session, outsider, workspace.id).workspace_id == workspace.id
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_investigation_agent_checks_model_citations_against_workspace_evidence():
    evidence = {"industry": "ecommerce", "currency": "USD", "kpis": {}, "findings": [],
                "evidence_sources": [{"id": "chunk-a", "document": "notes.txt", "score": 0.8}],
                "interpretation": "Evidence summary."}

    class DataAgent:
        def investigate(self, db, business_context, question):
            assert business_context.workspace_id == "tenant-a"
            return evidence

    class Provider:
        model_id = "test:model"

        def analyze(self, question, business_context, workspace_evidence):
            assert question == "Why did sales decline?"
            assert business_context["industry"] == "ecommerce"
            assert workspace_evidence is evidence
            return (AnalysisOutput.model_validate({"assessment": "The supplied note reports a delivery delay.",
                "assessment_source_ids": ["chunk-a"],
                "findings": [{"title": "Delivery issue", "evidence": "The note reports delays.",
                              "source_ids": ["chunk-a"]}], "confidence": 0.7}),
                {"input_tokens": 100, "output_tokens": 50})

    result = InvestigationAgent(DataAgent(), Provider()).investigate(None, context(), "Why did sales decline?")
    assert result["status"] == "analyzed"
    assert result["result"]["analysis_findings"][0]["source_ids"] == ["chunk-a"]
    assert result["input_tokens"] == 100
    assert result["model"] == "test:model"

    class ForgedProvider(Provider):
        def analyze(self, *_):
            return AnalysisOutput.model_validate({"assessment": "Unsupported.", "assessment_source_ids": [], "findings": [
                {"title": "Forged", "evidence": "No such source.", "source_ids": ["tenant-b-secret"]}],
                "confidence": 1}), {"input_tokens": 10, "output_tokens": 10}

    with pytest.raises(InvestigationError, match="unknown evidence citation"):
        InvestigationAgent(DataAgent(), ForgedProvider()).investigate(None, context(), "Why did sales decline?")


def test_openai_investigation_uses_structured_output_and_calculates_versioned_cost(monkeypatch):
    response_data = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text",
        "text": json.dumps({"assessment": "The report cites a delay.", "assessment_source_ids": ["chunk-a"],
            "findings": [{"title": "Delivery delay", "evidence": "The report describes late delivery.",
                          "source_ids": ["chunk-a"]}], "confidence": 0.6})}]}],
        "usage": {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 200}, "output_tokens": 500}}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, _):
            return json.dumps(response_data).encode()

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "https://api.openai.com/v1/responses"
            assert timeout == 7
            assert "Bearer secret" == request.get_header("Authorization")
            body = json.loads(request.data)
            assert body["store"] is False
            assert body["text"]["format"]["strict"] is True
            assert "tenant-id" not in request.data.decode()
            return Response()

    monkeypatch.setattr("app.intelligence.investigation.urllib.request.build_opener", lambda *_: Opener())
    provider = OpenAIInvestigationProvider("secret", "gpt-4o-mini", 7)
    _, usage = provider.analyze("Why?", {"industry": "ecommerce", "goals": [], "constraints": [],
                                          "monthly_budget": 100}, {"evidence_sources": [{"id": "chunk-a"}]})
    assert usage["input_tokens"] == 1000
    assert usage["output_tokens"] == 500
    assert str(usage["estimated_cost_usd"]) == "0.00043500"
    assert usage["cost_schedule"] == "openai-text-2026-10-12-v1"
