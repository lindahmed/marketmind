# Durable workflow jobs

MarketMind stores long-running work in the application database. Production runs `python -m app.worker` as a separate service with a restricted PostgreSQL login; `WORKFLOW_WORKER_ENABLED=false` disables the FastAPI lifespan worker. An optional inline worker remains available for local development. Migration `0009_durable_workflows` adds jobs/checkpoints; production revision `0014` adds tenant policies.

## Supported jobs

- `investigation`: evidence collection and investigation; the frontend submits this from Private knowledge.
- `growth_strategy`: recommendations for a saved, workspace-owned investigation; the frontend submits this from Experiments.
- `experiment_evaluation`: queued atomically when an authenticated n8n simulation callback is accepted.

Authenticated clients can submit an investigation or strategy with `POST /api/workflow-jobs`, check workspace-scoped status through `GET /api/workflow-jobs` or `GET /api/workflow-jobs/{id}`, and request cancellation with `POST /api/workflow-jobs/{id}/cancel`. Supply a stable `idempotency_key` and reuse it for HTTP retries. Reusing a key with a different payload returns `409`.

Jobs persist `queued`, `running`, `completed`, `failed`, and `cancelled` states, attempt count, current step, safe error code, timestamps, and result. Only the requester or workspace owner may cancel; every request is tenant-checked. Workers revalidate requester membership, saved investigation/evidence freshness, and experiment approval/dispatch relationships before processing and before saving outputs.

## Checkpoints, recovery, and retry limits

LangGraph checkpoints and pending writes are stored in tenant- and job-scoped tables. Checkpoint reads and writes require the job ID to belong to the supplied workspace. The job graph state is JSON-only: ORM instances, agent clients, and secrets are not serialized. Checkpoints inherit the database's access controls and at-rest protection; this feature does not add separate application-level encryption.

After a worker restart, queued jobs are picked up from the database. A lease that expired before the graph started can be retried once. When the saved domain result exists but the job status update was interrupted, recovery marks the job complete without rerunning the agent. A crash during an in-flight AI step is marked failed rather than automatically replayed, because the provider may already have processed the request. There is no manual retry endpoint yet. Cancellation is immediate while queued and cooperative while running; the worker checks it before persisting new results.

The current job graph checkpoints at the job-step boundary. An in-flight model call cannot resume from its internal progress. For that case the durable job remains failed with a safe error code and requires a new, explicitly submitted job after review.

## Operational requirements and verification limits

Run the separate release migration job before starting a new production version. Workers renew five-minute leases every 30 seconds by default. Domain/checkpoint writes check and lock the queue row with the exact tenant, job, lease token, unexpired ownership and cancellation state before committing. Recovery cannot race that commit. Expired/replaced workers cannot save output; ambiguous in-flight provider calls fail without automatic replay. SQLite remains suitable for local development; production requires PostgreSQL.

Automated tests cover existing workflows plus restricted-role PostgreSQL execution, competing claims, renewal and stale-writer rejection. See [Railway verification](RAILWAY_VERIFICATION.md) for current checks/cloud limits and [deployment steps](../RAILWAY_DEPLOYMENT.md) for health checks/logs.
