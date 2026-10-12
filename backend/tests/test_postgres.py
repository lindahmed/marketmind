"""Real vector semantics; only enabled against a dedicated PostgreSQL test database."""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db import Base
from app.intelligence.knowledge import PgVectorRetriever
from app.models import KnowledgeChunk, Workspace
from tests.test_intelligence import context
from tests.conftest import register
from tests.test_embeddings import FakeProvider


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"), reason="PostgreSQL not configured")
def test_vector_retrieval_returns_only_private_business_evidence():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    schema = f"test_vectors_{uuid.uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(scoped)
        with Session(scoped) as db:
            db.add_all([Workspace(id="tenant-a", name="A store", industry="ecommerce"),
                        Workspace(id="tenant-b", name="B store", industry="ecommerce")])
            db.flush()
            db.add_all([KnowledgeChunk(workspace_id="tenant-a", source="private-a", content="A private lesson", embedding=[0.1] * 1536),
                        KnowledgeChunk(workspace_id="tenant-b", source="private-b", content="B private lesson", embedding=[0.1] * 1536)])
            db.commit()
            results = PgVectorRetriever(db).search(context("tenant-a"), [0.1] * 1536)
            assert [row["source"] for row in results] == ["private-a"]
            assert results[0]["distance"] == pytest.approx(0, abs=1e-6)
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"), reason="PostgreSQL not configured")
def test_hybrid_search_embedded_upload_model_filter_and_tenant_isolation(clients, monkeypatch):
    first, second = clients
    tenant_a = register(first)
    register(second, "second@example.com")
    provider = FakeProvider()
    monkeypatch.setattr("app.intelligence.documents.get_embedding_provider", lambda: provider)
    for client, note in ((first, b"Order shipment is delayed"), (second, b"Private salon appointments")):
        assert client.post("/api/knowledge/documents", files={"file": ("notes.md", note, "text/markdown")}).status_code == 201
    matches = first.post("/api/knowledge/search", json={"query": "delivery"}).json()["results"]
    assert len(matches) == 1 and matches[0]["excerpt"] == "Order shipment is delayed"
    assert matches[0]["retrieval_methods"] == ["vector"]
    matches = first.post("/api/knowledge/search", json={"query": "shipment"}).json()["results"]
    assert len(matches) == 1 and set(matches[0]["retrieval_methods"]) == {"lexical", "vector"}
    assert second.post("/api/knowledge/search", headers={"X-Workspace-ID": tenant_a},
                       json={"query": "delivery"}).status_code == 403
    provider.model_id = "openai:text-embedding-3-large:1536"
    assert first.post("/api/knowledge/search", json={"query": "delivery"}).json()["results"] == []
    assert first.post("/api/knowledge/search", json={"query": "shipment"}).json()["results"][0]["retrieval_methods"] == ["lexical"]
