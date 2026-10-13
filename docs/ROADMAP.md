# Development roadmap

## V1 freeze — 2026-10-13

Local V1 demonstration acceptance passed: both fictional industry workflows completed through owner-approved simulation, evaluation, and persisted learning in browser/API tests. Backend: 155 passed, 2 skipped; Ruff, frontend typecheck/build passed. Outbound cloud HTTP was substituted and model providers were disabled. See [V1_RELEASE_CHECKLIST.md](../V1_RELEASE_CHECKLIST.md) for explicit PASS/FAIL gates. Development is frozen; unchecked items below are deferred, not authorized implementation work. Live n8n/model requests, PostgreSQL/pgvector and Docker checks remain unverified; RLS and long-running worker lease fencing remain production blockers.

## Milestone 1 — Foundation

- [x] Next.js/TypeScript/Tailwind workspace dashboard and FastAPI API.
- [x] PostgreSQL + pgvector schema, Alembic migrations, Docker Compose configuration (full local pgvector/Docker verification pending).
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
- [x] Add inclusive reporting periods, calendar gap disclosures, refunds, reported variable costs, and validated fulfillment/appointment outcomes with regression coverage.
- [x] Correct fulfillment and monetary refund KPIs; support legacy data with missing-outcome warnings.
- [x] Verify migration 0006 financial backfill and round trips on SQLite and isolated PostgreSQL 18.
- [x] Introduce durable investigation, growth-strategy, and experiment-evaluation jobs with workspace-scoped LangGraph checkpoint persistence; revalidate membership, evidence, and persisted approvals inside workers.
- [x] Add fixed-cost imports and tenant-scoped estimated operating profit, preserving contribution profit and disclosing rows without fixed-cost coverage.
- [ ] Add source reconciliation, campaign attribution, and expanded industry-specific measurements.

Provider-backed shared analysis is opt-in; disabled workspaces receive evidence-only reviews. Source reconciliation, attribution, expanded industry measurements, and full PostgreSQL/pgvector integration verification remain; milestone 2 is not complete.

## Milestone 3 — Strategy and experiments

- [x] Persist manually created simulation drafts and owner approvals tied to workspace and experiment version.
- [x] Verify ownership, approval version/expiry/state, simulation budget and constraints before n8n dispatch.
- [x] Implement shared Growth Strategy and Experiment Design agents, adapted through goals, constraints, budget, and industry packs.
- [x] Persist prioritized evidence-backed recommendations; label industry rules and opt-in model proposals honestly.
- [x] Connect persisted investigation, shared strategy, and owner-gated deterministic experiment design in LangGraph.
- [x] Require owner approval/rejection of the exact recommendation version before design; recheck context, evidence, and approver membership.
- [x] Store immutable experiment drafts with hypotheses, cited evidence, measured baseline, owner-reviewed cost, targets, profit guardrail, and evaluation criteria.
- [x] Add frontend recommendation review, constraint acknowledgement, approval/rejection, design forms, and saved design details.
- [ ] Add aggregate budget reservation, plan revisions, and spend accounting before live experiments.
- [ ] Add approval/version lifecycle for revised designs and live business actions.
- [x] Add owner approval/rejection for safe simulation drafts and a workspace-scoped experiment dispatch status page.

## Milestone 4 — Approved execution and learning

- [x] Trigger manually managed n8n Cloud simulation webhooks with server-only authentication, durable dispatch idempotency, failure records, and audit events.
- [x] Treat webhook acceptance as acknowledgement only; preserve unknown completion status.
- [x] Add a separately authenticated simulation callback, validate persisted dispatch/approval/tenant relationships, deduplicate callback receipts, reconcile terminal execution state, and queue evaluation durably.
- [x] Implement a shared deterministic Evaluation Agent for baseline, primary target, profit guardrail, and reported data-quality checks.
- [x] Persist tenant-scoped experiment learning with hypotheses, decisions, results, evidence references, conclusions, and simulation limitations; provide relevant prior learning to investigations.
- [x] Add frontend dispatch/completion status, evaluation reports, and experiment history.
- [x] Cover completion, failure, duplicate/replay, unauthorized, tenant mismatch, and inconclusive outcomes with automated tests.
- [ ] Add automatic retry/reconciliation for missed callbacks and operational recovery workflows.
- [ ] Enforce live spend ceilings, cancellation, and a kill switch before every external marketing action.
- [x] Compare simulated outcomes with saved baselines/targets/guardrails and store private lessons with provenance.
- [ ] Evaluate real business measurements and statistical uncertainty before making causal or profit-improvement claims.
- [ ] Add e-commerce and scheduling API connectors, then new industry packs.

## Before production access

- Add PostgreSQL row-level security and a least-privilege runtime role, including vector/worker integration tests.
- Add rate limiting, email verification, password recovery, invitation roles, session revocation, and audit logs.
- Deploy behind HTTPS with secure cookies, host restrictions, a content security policy, and secret management.
- Establish backups/restore checks, monitoring, data retention/deletion, and connection-pool capacity.
- Run full PostgreSQL/pgvector and Docker smoke checks; add browser regression coverage for critical flows.

Execution remains simulation-only. Callback results and evaluation reports are explicitly labeled simulated; webhook acknowledgement does not establish completion, measured business impact, or actual profit improvement. Live actions, automatic recovery, real measurement connectors, and statistical uncertainty analysis remain future work.

## Milestone 5 — Trusted business data integration & source reconciliation

- [x] Add tenant-scoped data sources with one-time bearer credentials, revocation, import history, sync timestamps, and provenance.
- [x] Add a canonical event model for orders, fulfillment, cancellations, refunds, payments, marketing spend, appointments, and expenses.
- [x] Reconcile exact duplicate and conflicting records append-only; retain missing-required-field records for review and never overwrite an accepted event.
- [x] Add a secure n8n Cloud push endpoint and a documented manual Google Sheets → n8n → MarketMind setup.
- [x] Feed accepted reconciled events into financial analytics for dates without a CSV summary; flag overlaps and retain existing CSV totals until they can be safely compared.
- [x] Add e-commerce and appointment outcome rollups and show data source/reconciliation status in the frontend.
- [x] Record campaign IDs and payment totals as source labels only; do not claim causal attribution.
- [x] Add owner-reviewed conflict resolution with idempotent decisions, stale-match revalidation, competing-conflict handling, provenance snapshots, and audit history.
- [x] Support explicit Google Sheets record corrections and deletion tombstones while retaining financial event history and import provenance.
- [x] Track source/day coverage revisions, distinguish complete zero-activity days, and withhold profit estimates when a financial category is partial or has unresolved conflicts.
- [x] Preserve appointment booking, scheduled, and completion dates independently when a source provides them.
- [ ] Add scheduled incremental sync controls and automatic snapshot-difference discovery; n8n remains manually configured and must submit deleted IDs explicitly.
- [ ] Verify migrations 0011–0013, source ingestion concurrency, and analytics rollups on PostgreSQL; PostgreSQL credentials are not configured in this environment.
- [ ] Add and verify PostgreSQL row-level security policies. Tenant protection currently depends on API-level workspace scoping and source-scoped bearer tokens, so production database-level isolation remains a blocker.

The first working source path supports n8n-pushed Google Sheets rows only. MarketMind does not fetch Sheets directly. Conflict decisions, raw correction/deletion history, explicit coverage, and appointment lifecycle dates are implemented. Automatic source snapshot diffing and scheduled sync controls remain future work. PostgreSQL RLS and the long-running worker lease fencing issue remain production blockers. See [Google Sheets setup](GOOGLE_SHEETS_N8N_SETUP.md) and [verification gaps](VERIFICATION.md).
