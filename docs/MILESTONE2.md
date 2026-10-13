# Milestone 2 — Private evidence pilot

## Available

- The authenticated user and membership are rechecked to construct a `BusinessContext` before knowledge operations, evidence runs, or history lookups.
- UTF-8 Markdown and plain-text uploads are size/character bounded, SHA-256 deduplicated per workspace, split into overlapping chunks, and persisted with tenant-owned provenance.
- Workspace members can list, search, and remove documents. Retrieval filters on the verified workspace ID before ranking. BM25 has no external provider dependency; an opt-in OpenAI provider embeds new uploads and adds pgvector cosine search with matching model provenance. See [embedding configuration](EMBEDDINGS.md).
- The shared Data Intelligence agent combines the current industry pack's metrics/rule findings with matching document excerpts, their source IDs, and ranking scores. The shared Investigation agent optionally analyzes that tenant-bound evidence through a structured OpenAI Responses request. Output citations are checked against collected evidence IDs before saving.
- Investigation inputs/results, status, model/prompt version, confidence, token usage, cost estimate and timestamp have a tenant-scoped persisted record. With the provider disabled, unavailable AI measurements are stored as `null`; results are marked `evidence_ready` and do not claim a causal diagnosis. With analysis enabled, they are marked `analyzed` and retain model, prompt version, token usage, self-reported confidence, and estimated cost with its schedule version.
- `INVESTIGATION_PROVIDER=openai` opts in to external processing using `OPENAI_API_KEY` and `INVESTIGATION_MODEL`. The evidence screen discloses enabled external processing. Each request has bounded evidence and output, a timeout, no stored provider response, and tenant-only context.
- The dashboard links to the document library, evidence search and saved investigation review.
- Document uploads/deletions, embedding failures, workspace searches, and investigation attempts are recorded in a workspace-keyed audit table. Query and question text use a server-keyed HMAC digest in audit metadata. Investigation costs use a dated text-token price schedule; the amount remains an estimate and cached input is counted separately.
- Detailed and legacy CSV imports support inclusive reporting periods, calendar gap disclosures, refunds, reported variable costs, and validated order/appointment outcomes. The dashboard shows contribution profit estimates and missing-data warnings. See [financial definitions](FINANCIAL_REPORTING.md).

## Still in progress

- Evaluate a PostgreSQL HNSW index only after testing its recall under tenant and model filters on real pgvector. Current hybrid search uses exact vector retrieval plus BM25 and rank fusion.
- Introduce persistent jobs, worker authorization checks and tenant-bound LangGraph checkpoints before doing slow provider calls.
- Define evidence retention and deletion effects for existing investigation snapshots.
- Add fixed costs, attribution, reconciliation with source systems, and independently validated industry measurements before expanding causal claims.

Search scores describe retrieval relevance from lexical matching and, when configured, semantic similarity. Findings marked `industry_rule` are deterministic checks. A high score or rule is not a model confidence value or causal explanation.

## Local checks

See [current verification results](VERIFICATION.md) for test totals, financial migration checks, CORS deletion coverage, and outstanding pgvector/Docker verification. Earlier browser checks covered private upload, search, saved investigation history, and tenant denial; they were not rerun for this financial review.
