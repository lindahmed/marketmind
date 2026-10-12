# Development roadmap

## Milestone 1 — Foundation

- [x] Next.js/TypeScript/Tailwind workspace dashboard and FastAPI API.
- [x] PostgreSQL + pgvector schema, Alembic migrations, Docker Compose.
- [x] Registration, login/logout, HttpOnly sessions, verified tenant memberships.
- [x] Business profiles, goals, budgets, constraints, two industry packs.
- [x] Validated daily CSV imports, private persisted data, KPI summaries and rule findings.
- [x] Shared LangGraph factory, tenant-scoped retrieval implementation, approval-gated n8n adapter.
- [x] Backend tests, frontend build/type checking, and CI configuration.

## Milestone 2 — Private evidence and investigation

- [x] Add private Markdown/plain-text document ingestion, deduplication, chunking, listing, and deletion.
- [x] Add tenant-scoped BM25 text retrieval and a tenant-verified business context factory.
- [x] Collect workspace KPI/rule evidence and citations from private documents.
- [x] Persist evidence reviews with workspace scope, question, prompt revision, status, and explicit unknown model/token/cost fields.
- [x] Add tenant-checked API history/detail and frontend knowledge/evidence review flows.
- [x] Configure an embedding provider and embed newly uploaded chunks; use pgvector similarity alongside lexical search.
- [x] Implement shared Data Intelligence and Investigation agents with structured outputs and citations to tenant-owned evidence.
- [x] Persist investigation runs, model/prompt versions, token cost, confidence, and a tenant-scoped audit log.
- Introduce durable jobs and tenant-scoped LangGraph checkpoints; enforce authorization again inside workers.
- Add reporting periods, calendar gaps, refunds, fixed costs, attribution, and industry-specific metric definitions.

Provider-backed shared analysis is opt-in; disabled workspaces receive evidence-only reviews. Durable jobs, tenant-scoped checkpoints, and expanded financial definitions remain before milestone 2 is complete.

## Milestone 3 — Strategy and experiments

- Implement shared Growth Strategy and Experimentation agents.
- Store experiment hypotheses, evidence, success metrics, baseline, budgets, versions, and status transitions.
- Require owner approval of an immutable experiment version before execution.
- Implement an approval verifier checking tenant, version, expiry, status, and budget.
- Add approval/rejection UI and pending experiment dashboard.

## Milestone 4 — Approved execution and learning

- Implement shared Execution and Evaluation/Memory agents.
- Add authenticated n8n workflows, callback validation, retries, and durable idempotency receipts.
- Enforce spend ceilings, constraints, cancellation, and a kill switch before every external action.
- Compare experiment outcomes with baselines, account for uncertainty, and store private lessons with provenance.
- Add e-commerce and scheduling API connectors, then new industry packs.

## Before production access

- Add PostgreSQL row-level security and a least-privilege runtime role, including vector/worker integration tests.
- Add rate limiting, email verification, password recovery, invitation roles, session revocation, and audit logs.
- Deploy behind HTTPS with secure cookies, host restrictions, a content security policy, and secret management.
- Establish backups/restore checks, monitoring, data retention/deletion, and connection-pool capacity.
- Run full PostgreSQL/pgvector and Docker smoke checks; add browser regression coverage for critical flows.

No advertising actions are enabled. AI stages will ship with tenant-bound evidence and persisted approvals before automated execution is exposed.
