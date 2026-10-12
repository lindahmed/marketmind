import json
import urllib.error
from contextlib import contextmanager

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings
from app.db import get_db
from app.intelligence.documents import fuse_results
from app.intelligence.embeddings import EmbeddingError, OpenAIEmbeddingProvider, validate_vectors
from app.main import app
from app.models import KnowledgeChunk, KnowledgeDocument
from tests.conftest import register


def unit_vector():
    return [1.0] + [0.0] * 1535


class FakeProvider:
    model_id = "openai:text-embedding-3-small:1536"

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        return [unit_vector() for text in texts]


def test_openai_request_batches_and_orders_results(monkeypatch):
    requests = []

    class Response:
        def __init__(self, content):
            self.content = content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return self.content[:limit]

    class Transport:
        def open(self, request, timeout):
            payload = json.loads(request.data)
            requests.append(payload)
            assert request.full_url == "https://api.openai.com/v1/embeddings"
            assert request.get_header("Authorization") == "Bearer private-test-key"
            assert timeout == 10
            assert payload["dimensions"] == 1536 and payload["encoding_format"] == "float"
            return Response(json.dumps({"model": payload["model"], "data": [
                {"index": index, "embedding": [float(dimension == index) for dimension in range(1536)]}
                for index in reversed(range(len(payload["input"])))
            ]}).encode())

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Transport())
    provider = OpenAIEmbeddingProvider("private-test-key", "text-embedding-3-small", timeout=10)
    vectors = provider.embed([f"Private note {i}" for i in range(33)])
    assert len(vectors) == 33
    assert vectors[0][0] == vectors[31][31] == vectors[32][0] == 1.0
    assert [len(request["input"]) for request in requests] == [32, 1]


def test_provider_http_errors_do_not_expose_private_details(monkeypatch):
    class Transport:
        def open(self, request, timeout):
            raise urllib.error.URLError("private provider error containing private-test-key")

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Transport())
    with pytest.raises(EmbeddingError) as error:
        OpenAIEmbeddingProvider("private-test-key", "text-embedding-3-small").embed(["Private text"])
    assert "private-test-key" not in str(error.value)
    assert "Private text" not in str(error.value)


@pytest.mark.parametrize("payload", [
    {"model": "wrong-model", "data": []},
    {"model": "text-embedding-3-small", "data": [{"index": 1, "embedding": unit_vector()}]},
    {"model": "text-embedding-3-small", "data": [{"index": 0, "embedding": [1]}]},
    {"model": "text-embedding-3-small", "data": [{"index": 0, "embedding": [0.0] * 1536}]},
    {"model": "text-embedding-3-small", "data": [{"index": 0, "embedding": [float("nan")] * 1536}]},
])
def test_provider_rejects_invalid_response(monkeypatch, payload):
    provider = OpenAIEmbeddingProvider("private-test-key", "text-embedding-3-small")
    monkeypatch.setattr(provider, "_request", lambda texts: payload)
    with pytest.raises(EmbeddingError):
        provider.embed(["Evidence"])


def test_configuration_requires_key_and_hides_it():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="test-secret-at-least-32-characters", embedding_provider="openai")
    settings = Settings(_env_file=None, jwt_secret="test-secret-at-least-32-characters",
                        embedding_provider="openai", openai_api_key="private-test-key")
    assert "private-test-key" not in repr(settings)


def test_upload_persists_vectors_and_provenance_atomically(clients, monkeypatch):
    first, second = clients
    tenant_a = register(first)
    register(second, "second@example.com")
    provider = FakeProvider()
    monkeypatch.setattr("app.intelligence.documents.get_embedding_provider", lambda: provider)
    text = ("Private fulfilment notes for this store. " * 80).encode()
    response = first.post("/api/knowledge/documents", files={"file": ("notes.txt", text, "text/plain")})
    assert response.status_code == 201
    with contextmanager(app.dependency_overrides[get_db])() as db:
        chunks = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.workspace_id == tenant_a)).all()
        assert len(chunks) == len(provider.calls[0]) > 1
        assert all(chunk.embedding_model == provider.model_id for chunk in chunks)
        assert all(list(chunk.embedding) == unit_vector() for chunk in chunks)
    assert first.post("/api/knowledge/documents", files={"file": ("copy.txt", text, "text/plain")}).status_code == 409
    assert len(provider.calls) == 1
    assert second.post("/api/knowledge/documents", headers={"X-Workspace-ID": tenant_a},
                       files={"file": ("foreign.txt", text, "text/plain")}).status_code == 403
    assert len(provider.calls) == 1


def test_provider_failure_saves_no_document_or_chunks(clients, monkeypatch):
    client, _ = clients
    register(client)

    class FailingProvider(FakeProvider):
        def embed(self, texts):
            raise EmbeddingError("Embedding provider is unavailable")

    monkeypatch.setattr("app.intelligence.documents.get_embedding_provider", lambda: FailingProvider())
    response = client.post("/api/knowledge/documents", files={"file": ("notes.md", b"Private note", "text/markdown")})
    assert response.status_code == 503
    with contextmanager(app.dependency_overrides[get_db])() as db:
        assert db.scalar(select(KnowledgeDocument.id)) is None
        assert db.scalar(select(KnowledgeChunk.id)) is None


def test_rank_fusion_deduplicates_and_retains_both_signals():
    lexical = [{"chunk_id": "both", "score": 3.0}, {"chunk_id": "word", "score": 2.0}]
    semantic = [{"chunk_id": "semantic", "vector_distance": 0.01},
                {"chunk_id": "both", "vector_distance": 0.05}]
    results = fuse_results(lexical, semantic, 3)
    assert results[0]["chunk_id"] == "both"
    assert results[0]["retrieval_methods"] == ["lexical", "vector"]
    assert results[0]["lexical_score"] == 3
    assert results[0]["vector_distance"] == 0.05
    assert len({match["chunk_id"] for match in results}) == 3
    assert len(fuse_results(lexical, semantic, 1)) == 1


def test_vector_validation_rejects_boolean_and_wrong_counts():
    with pytest.raises(EmbeddingError):
        validate_vectors([[True] * 1536], 1)
    with pytest.raises(EmbeddingError):
        validate_vectors([], 1)
    assert validate_vectors([[1e100] + [0.0] * 1535], 1) == [unit_vector()]
