# Railway preparation verification — 2026-10-13

Repository checks use fictional data and an isolated PostgreSQL cluster on a separate loopback port. Existing local/customer data and n8n Cloud workflows were not changed. This is not a live Railway deployment.

## Checked

- Complete updated backend suite on PostgreSQL 18 / pgvector 0.8.7: **177 passed**. Includes both vector tests and isolated source/reconciliation migrations.
- Full Alembic chain from an empty PostgreSQL database and idempotent release rerun; restricted API/worker role provisioning and production startup gates. A release regression now asserts Alembic creates `version_num` as `varchar(64)`, preserving the existing long revision ID.
- Alembic head upgraded on the isolated PostgreSQL database and `alembic check` reports no model/schema drift. The check exposed an ORM metadata omission for the already migrated requester index; metadata now matches the existing migration, with no schema change required.
- RLS on all 25 workspace/tenant tables; transaction scope reapplied after commit, default-deny reads, rejected cross-tenant writes and clean pool reuse.
- Production secure cookie/logout, missing/hostile Origin rejection, credentialed CORS, shared authentication counters and two-account boundaries.
- Source bearer bootstrap, durable investigation/growth, persisted approval, callback/version authentication, idempotency, evaluation and saved simulation learning through restricted roles. External n8n dispatch alone was substituted.
- Competing PostgreSQL claims, real heartbeat renewal, stale-writer rejection and independent worker process health/job completion with sanitized logs.
- Frontend production build and type checking after the final API-aware health-route edit.
- Local TLS edge integration with the production Next.js standalone server and a fictional private API: HTTPS health forwarding, `/api` path/header forwarding and `Secure` `HttpOnly` cookie relay all passed. This exercises the app proxy over HTTPS; it does not validate Railway's edge or private network.
- SQLite regression suite: **168 passed, 9 skipped**. The skips are the disposable PostgreSQL-only release checks.
- Railway SDK type checking.

## Cloud gates still pending

- Docker is unavailable locally; CI is configured to build both Linux images. CI results and actual container startup remain pending.
- Railway private DNS, HTTPS domains, variables, restart/draining behavior and live deployment health checks need verification in the new project.
- Live n8n Cloud/provider delivery, credentials and costs were not exercised. Disabled providers yield labeled rules/evidence reviews.
- Backup schedules and an actual restore into a separate project remain to be performed. Customer data/workflow changes require the user's authorization.

## Reproduce

Run backend `pytest -q`, Ruff over `app tests migrations`, and frontend `npm run typecheck` / `npm run build`. Use dedicated PostgreSQL URLs for `TEST_DATABASE_URL` and `TEST_MIGRATION_DATABASE_URL`. `TEST_DEPLOYMENT_DATABASE_URL` requires a disposable cluster with CREATEDB/CREATEROLE privileges **without existing `marketmind_api` / `marketmind_worker` roles**. Release tests create/drop a database and these roles and refuse a cluster where they already exist. Never use customer database/cluster URLs.

Local tests use PostgreSQL 18 with pgvector 0.8.7; CI/Railway use PostgreSQL 17 with pgvector 0.8.7. CI establishes the Linux/version compatibility the local Windows run cannot prove.
