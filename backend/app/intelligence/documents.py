import hashlib
import math
import re
from pathlib import PurePosixPath

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.intelligence.contracts import BusinessContext
from app.intelligence.audit import record_audit
from app.intelligence.embeddings import EmbeddingError, get_embedding_provider, validate_vectors
from app.intelligence.knowledge import PgVectorRetriever
from app.models import KnowledgeChunk, KnowledgeDocument

MAX_DOCUMENT_BYTES = 200 * 1024
MAX_DOCUMENT_CHARACTERS = 100_000
MAX_CHUNKS = 100
CHUNK_SIZE = 1_200
CHUNK_OVERLAP = 150


def split_document(content: str) -> list[str]:
    clean = re.sub(r"\s+", " ", content).strip()
    chunks = []
    start = 0
    while start < len(clean):
        end = min(start + CHUNK_SIZE, len(clean))
        if end < len(clean):
            boundary = clean.rfind(" ", start + CHUNK_SIZE * 3 // 4, end)
            if boundary > start + CHUNK_OVERLAP * 2:
                end = boundary
        chunks.append(clean[start:end].strip())
        if end == len(clean):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    if not chunks or len(chunks) > MAX_CHUNKS:
        raise HTTPException(422, "Document must contain text and fit within 100 chunks")
    return chunks


async def save_document(db: Session, context: BusinessContext, file: UploadFile,
                        actor_user_id: str | None = None) -> KnowledgeDocument:
    raw_name = (file.filename or "").replace("\\", "/")
    name = PurePosixPath(raw_name).name
    if not name or len(name) > 255 or any(ord(char) < 32 for char in name):
        raise HTTPException(422, "Provide a short, plain filename")
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in {".txt", ".md"}:
        raise HTTPException(415, "Upload a .txt or .md document")
    content_bytes = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content_bytes) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "Document limit is 200 KB")
    try:
        content = content_bytes.decode("utf-8-sig")
    except UnicodeError:
        raise HTTPException(422, "Document must be valid UTF-8 text") from None
    if "\x00" in content or len(content) > MAX_DOCUMENT_CHARACTERS:
        raise HTTPException(422, "Document must be readable UTF-8 text under 100,000 characters")
    parts = split_document(content)
    digest = hashlib.sha256(content_bytes).hexdigest()
    existing = db.scalar(select(KnowledgeDocument).where(
        KnowledgeDocument.workspace_id == context.workspace_id, KnowledgeDocument.sha256 == digest,
    ))
    if existing:
        raise HTTPException(409, "This document is already in this workspace")
    provider = get_embedding_provider()
    vectors = None
    if provider:
        try:
            vectors = validate_vectors(await run_in_threadpool(provider.embed, parts), len(parts))
        except EmbeddingError as error:
            if actor_user_id:
                record_audit(db, context, actor_user_id, "knowledge.embedding.failed", "knowledge_document", None,
                         {"source_digest": digest, "failure": "provider_or_vector_validation"})
                db.commit()
            raise HTTPException(503, str(error)) from None
    document = KnowledgeDocument(workspace_id=context.workspace_id, name=name, sha256=digest,
                                 mime_type="text/markdown" if suffix == ".md" else "text/plain",
                                 character_count=len(content))
    try:
        db.add(document)
        db.flush()
        db.add_all([KnowledgeChunk(workspace_id=context.workspace_id, document_id=document.id, position=i,
                                   source=name, content=part,
                                   embedding=vectors[i] if vectors else None,
                                   embedding_model=provider.model_id if provider else None)
                    for i, part in enumerate(parts)])
        if actor_user_id:
            record_audit(db, context, actor_user_id, "knowledge.document.uploaded", "knowledge_document",
                         document.id, {"sha256": digest, "character_count": len(content),
                                       "chunk_count": len(parts),
                                       "embedding_model": provider.model_id if provider else None})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This document was added concurrently to this workspace") from None
    except Exception:
        db.rollback()
        raise
    db.refresh(document)
    return document


def lexical_search(db: Session, context: BusinessContext, query: str, limit: int = 5) -> list[dict]:
    terms = list(dict.fromkeys(re.findall(r"[\w'-]+", query.casefold())))
    if not terms:
        raise HTTPException(422, "Enter a search with at least one word or number")
    rows = db.scalars(select(KnowledgeChunk).where(
        KnowledgeChunk.workspace_id == context.workspace_id, KnowledgeChunk.document_id.is_not(None),
    ).order_by(KnowledgeChunk.created_at.desc(), KnowledgeChunk.position).limit(5_000)).all()
    if not rows:
        return []
    tokenized = [re.findall(r"[\w'-]+", row.content.casefold()) for row in rows]
    average_length = max(1.0, sum(map(len, tokenized)) / len(tokenized))
    document_frequency = {term: sum(term in words for words in tokenized) for term in terms}
    ranked = []
    for row, words in zip(rows, tokenized, strict=True):
        length = max(1, len(words))
        score = 0.0
        for term in terms:
            frequency = words.count(term)
            if frequency:
                inverse = math.log(1 + (len(rows) - document_frequency[term] + 0.5) /
                                   (document_frequency[term] + 0.5))
                score += inverse * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / average_length))
        if score:
            ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return [{"chunk_id": row.id, "document_id": row.document_id, "source": row.source,
             "excerpt": row.content, "score": round(score, 4), "retrieval_methods": ["lexical"]}
            for score, row in ranked[:limit]]


def fuse_results(lexical: list[dict], semantic: list[dict], limit: int) -> list[dict]:
    """Reciprocal rank fusion combines unlike scores and deduplicates chunk IDs."""
    results = {}
    for method, matches in (("lexical", lexical), ("vector", semantic)):
        for rank, match in enumerate(matches, start=1):
            chunk_id = match["chunk_id"]
            if chunk_id not in results:
                results[chunk_id] = {**match, "score": 0.0, "retrieval_methods": []}
            result = results[chunk_id]
            result["score"] += 1 / (60 + rank)
            result["retrieval_methods"].append(method)
            if method == "lexical":
                result["lexical_score"] = match["score"]
            else:
                result["vector_distance"] = match["vector_distance"]
    return sorted(results.values(), key=lambda item: (-item["score"], item["chunk_id"]))[:limit]


def search_documents(db: Session, context: BusinessContext, query: str, limit: int = 5) -> list[dict]:
    if not 1 <= limit <= 10:
        raise HTTPException(422, "Search limit must be between 1 and 10")
    candidate_limit = min(50, max(10, limit * 3))
    lexical = lexical_search(db, context, query, candidate_limit)
    provider = get_embedding_provider()
    if provider is None or db.get_bind().dialect.name != "postgresql":
        return lexical[:limit]
    has_vectors = db.scalar(select(KnowledgeChunk.id).where(
        KnowledgeChunk.workspace_id == context.workspace_id,
        KnowledgeChunk.document_id.is_not(None), KnowledgeChunk.embedding.is_not(None),
        KnowledgeChunk.embedding_model == provider.model_id,
    ).limit(1))
    if not has_vectors:
        return lexical[:limit]
    try:
        embedding = validate_vectors(provider.embed([query]), 1)[0]
    except EmbeddingError as error:
        raise HTTPException(503, str(error)) from None
    semantic = [{"chunk_id": row["id"], "document_id": row["document_id"], "source": row["source"],
                 "excerpt": row["content"], "vector_distance": row["distance"]}
                for row in PgVectorRetriever(db).search(context, embedding, candidate_limit, provider.model_id)]
    return fuse_results(lexical, semantic, limit)
