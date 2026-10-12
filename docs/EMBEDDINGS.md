# Document embeddings and hybrid retrieval

The backend supports an opt-in OpenAI embedding provider. Existing documents remain searchable by BM25; new uploads receive vectors only when the provider is enabled. This implements the embedding/retrieval roadmap item.

## Configure

Set these values in the root `.env` (keep the key out of source control):

```dotenv
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=<your API key>
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_TIMEOUT_SECONDS=30
```

Apply the additive migration and restart the backend:

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

For Docker: `docker compose up --build` applies migrations at backend startup. PostgreSQL with pgvector is required for semantic retrieval. SQLite stores optional vectors for development, but its search remains lexical.

The provider also supports `text-embedding-3-large`, requesting 1536 dimensions to match the schema. Requests use the official [OpenAI embeddings API](https://developers.openai.com/api/reference/resources/embeddings/methods/create), float encoding, batches of up to 32 chunks, bounded responses, and a configurable timeout. No new dependencies are required.

## Behavior

- Enabling the provider sends newly uploaded chunk text and search query text to OpenAI. The knowledge screen discloses this before upload/search. With `EMBEDDING_PROVIDER=disabled` (the default), no embedding API calls occur.
- Uploads validate vector count/order, dimensions, finite nonzero values, and the returned model before saving. Provider failures return a sanitized HTTP 503 and save no document or chunks.
- Each vector records its provider/model/dimensions. Query vectors are compared only with the same recorded model. Existing unembedded chunks and chunks from another model remain eligible for lexical search.
- PostgreSQL cosine searches filter by verified workspace, associated document, and embedding model in SQL. Only this tenant's chunks enter the similarity ranking. Retrieval is exact; there is no approximate index that could filter out a tenant's matches after choosing global neighbors.
- Reciprocal rank fusion combines BM25 and cosine rankings and deduplicates chunk IDs. Results expose `retrieval_methods`, `lexical_score` and `vector_distance` where applicable. These scores express retrieval relevance, not confidence in a causal explanation.
- When a workspace has no compatible vectors, search uses BM25 without sending its query to OpenAI. If a required query embedding fails, search returns HTTP 503 rather than presenting an incomplete hybrid result as successful.
- Historical chunks are not backfilled by this task. Switching models applies to subsequent uploads; existing vectors retain their provenance. Document deletion removes its vectors through the existing tenant-scoped deletion path.

## Verification

Provider requests are tested with a mocked transport, including batching, response ordering, malformed vectors, and sanitized network errors. Upload tests cover atomic persistence, duplicate suppression, failure rollback, and tenant access denial. PostgreSQL CI tests exercise semantic-only retrieval, rank fusion, model filtering, and tenant isolation with deterministic test embeddings; no API key is needed for those tests.

Local results: **34 tests passed, 2 PostgreSQL tests skipped**; Ruff, frontend TypeScript/production build, and the additive migration/schema check passed.

Local PostgreSQL/pgvector integration was not run because pgvector is unavailable. No live OpenAI request was made; provider transport was verified with test responses. CI includes the PostgreSQL integration tests.
