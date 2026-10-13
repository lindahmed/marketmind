# Durable workflow jobs

MarketMind stores long-running work in the application database; no broker or separate worker service is required. Migration `0009_durable_workflows` adds the job, checkpoint, and checkpoint-write tables. The FastAPI lifespan starts a polling worker that claims queued work with a lease. Migration `0010_fixed_cost_reporting` adds fixed-cost coverage to daily financial records.

## Supported jobs

- `investigation`: evidence collection and investigation; the frontend submits this from Private knowledge.
- `growth_strategy`: recommendations for a saved, workspace-owned investigation; the frontend submits this from Experiments.
- `experiment_evaluation`: queued atomically when an authenticated n8n simulation callback is accepted.

Authenticated clients can submit an investigation or strategy with `POST /api/workflow-jobs`, check workspace-scoped status through `GET /api/workflow-jobs` or `GET /api/workflow-jobs/{id}`, and request cancellation with `POST /api/workflow-jobs/{id}/cancel`. Supply a stable `idempotency_key` and reuse it for HTTP retries. Reusing a key with a different payload returns `409`.

Jobs persist `queued`, `running`, `completed`, `failed`, and `cancelled` states, attempt count, current step, safe error code, timestamps, and result. Only the requester or workspace owner may cancel; every request is tenant-checked. Workers revalidate requester membership, saved investigation/evidence freshness, and experiment approval/dispatch relationships before processing and before saving outputs.

## Checkpoints, recovery, and retry limits

LangGraph checkpoints and pending writes are stored in tenant- and job-scoped tables. Checkpoint reads and writes require the job ID to belong to the supplied workspace. The job graph state is JSON-only: ORM instances, agent clients, and secrets are not serialized. Checkpoints inherit the database's access controls and at-rest protection; this feature does not add separate application-level encryption.

After a FastAPI restart, queued jobs are picked up from the database. A lease that expired before the graph started can be retried once. When the saved domain result exists but the job status update was interrupted, recovery marks the job complete without rerunning the agent. A crash during an in-flight AI step is marked failed rather than automatically replayed, because the provider may already have processed the request. There is no manual retry endpoint yet. Cancellation is immediate while queued and cooperative while running; the worker checks it before persisting new results.

The current job graph checkpoints at the job-step boundary. An in-flight model call cannot resume from its internal progress. For that case the durable job remains failed with a safe error code and requires a new, explicitly submitted job after review.

## Operational requirements and verification limits

Run `alembic upgrade head` before starting a version that includes durable workflows. The worker runs inside each FastAPI process and uses database row claims. Use one API process for the V1 local demonstration. Five-minute worker leases have no heartbeat; domain output writes are not fenced against a replaced lease, so jobs exceeding the lease and competing-worker production operation remain unsafe/unverified. PostgreSQL row claims alone do not close that gap. SQLite is suitable for local single-process development.

Automated tests cover idempotency, completed jobs, failure sanitization, membership revocation, tenant-scoped status/checkpoints, safe pre-start retry, process-restart recovery, queued cancellation, growth strategy jobs, and evaluation-time approval revalidation. PostgreSQL `SKIP LOCKED` concurrency, a full PostgreSQL migration chain, pgvector, and Docker startup still require verification in an environment with a dedicated PostgreSQL/pgvector test database and Docker.
