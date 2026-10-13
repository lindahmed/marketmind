# MarketMind on Railway

Deploy to **public HTTPS using fictional data first**. Customer data is not authorized by this preparation. The repository is prepared; live Railway networking, n8n/provider delivery, container startup and backup restore remain release gates. See [verification](docs/RAILWAY_VERIFICATION.md).

## 1. Publish the preparation

Review, commit and push these changes to `lindahmed/marketmind`. Wait for **GitHub → Actions → Foundation checks** to pass. CI checks backend/database workflows, migrations, worker safety, frontend and Linux Docker builds.

## 2. Create a new project and database

1. Railway → **New Project → Empty Project** → name **MarketMind**. Use a new empty database, separate from the existing local/customer database.
2. **+ New → Docker Image** → `pgvector/pgvector:0.8.7-pg17` → service name **postgres**. This includes pgvector; the standard PostgreSQL image does not guarantee it. [Official image tags](https://github.com/pgvector/pgvector#docker)
3. `postgres` → **Settings** → region **EU West / europe-west4**. Use this region for all services. Add a volume at **`/var/lib/postgresql/data`**. Leave public domains/TCP proxies unset and image auto-updates disabled.
4. **Variables → Raw Editor**:

```dotenv
POSTGRES_USER=railway_admin
POSTGRES_DB=marketmind
POSTGRES_PASSWORD=<new random URL-safe secret>
PGDATA=/var/lib/postgresql/data/pgdata
PGPORT=5432
DATABASE_URL=postgresql://railway_admin:${{postgres.POSTGRES_PASSWORD}}@${{postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/marketmind
```

5. Deploy. Require “database system is ready to accept connections”. Changing `POSTGRES_PASSWORD` after initialization does not change the database role's password.

Generate each new secret locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"`; use different values for admin, API, worker and JWT. Store them in Railway/password manager, never source or chat.

## 3. Create the app services and migration job

For every row: **+ New → GitHub Repo → lindahmed/marketmind**, rename the service, and set **Settings → Source → Root Directory**. Configure variables/settings before deployment. Each root has its Dockerfile; leave Build Command empty. Use one replica in the database region, enable **Wait for CI**, and disable **Serverless/App Sleeping**. Keep schema releases manual and run migration before app rollouts.

| Service | Root | Start Command | Healthcheck | Restart |
|---|---|---|---|---|
| migration | `/backend` | `python -m app.migrate` | none | Never |
| backend | `/backend` | `sh -c 'exec uvicorn app.main:app --host :: --port $PORT --no-access-log --no-proxy-headers'` | `/health`, 120 seconds | On Failure, 10 retries |
| worker | `/backend` | `python -m app.worker` | `/health`, 120 seconds | On Failure, 10 retries |
| frontend | `/frontend` | `node server.js` | `/health`, 120 seconds | On Failure, 10 retries |

The migration service is a short-lived release job that exits with code 0 on success. Only it receives administrator credentials. It runs Alembic under an advisory lock and provisions restricted `marketmind_api` / `marketmind_worker` roles. Do not put migrations or administrator URLs in API/worker startup or their pre-deploy commands.

## 4. Variables and HTTPS domains

`migration`:

```dotenv
MIGRATION_DATABASE_URL=${{postgres.DATABASE_URL}}
API_DATABASE_PASSWORD=<distinct random URL-safe secret>
WORKER_DATABASE_PASSWORD=<another distinct random URL-safe secret>
```

`frontend` → **Settings → Networking → Generate Domain**, target **3000**. Reserve a backend domain targeting **8000** for n8n Cloud. Domains can be generated before apps are healthy. Worker, migration and database get no public domain.

`backend`:

```dotenv
ENVIRONMENT=production
SERVICE_ROLE=api
PORT=8000
DATABASE_URL=postgresql://marketmind_api:${{migration.API_DATABASE_PASSWORD}}@${{postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/marketmind
JWT_SECRET=<random secret>
COOKIE_SECURE=true
WORKFLOW_WORKER_ENABLED=false
ALLOWED_ORIGINS=["https://YOUR-FRONTEND-DOMAIN"]
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=2
EMBEDDING_PROVIDER=disabled
INVESTIGATION_PROVIDER=disabled
STRATEGY_PROVIDER=disabled
```

Replace `ALLOWED_ORIGINS` with the exact generated frontend HTTPS origin: valid JSON, no trailing slash, path or wildcard.

`frontend`:

```dotenv
PORT=3000
DEPLOYMENT_ENVIRONMENT=production
NEXT_PUBLIC_API_URL=
BACKEND_API_URL=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000
```

The browser calls the frontend's HTTPS `/api/...`; Next.js forwards privately to FastAPI and relays the host-only HttpOnly/Secure/SameSite=Lax cookie. `BACKEND_API_URL` is server-only. The frontend receives no database URL, JWT/provider/n8n secret. Leave `NEXT_PUBLIC_API_URL` empty at build time; removing an old value requires a rebuild.

`worker`:

```dotenv
ENVIRONMENT=production
SERVICE_ROLE=worker
PORT=8000
DATABASE_URL=postgresql://marketmind_worker:${{migration.WORKER_DATABASE_PASSWORD}}@${{postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/marketmind
JWT_SECRET=${{backend.JWT_SECRET}}
COOKIE_SECURE=true
WORKFLOW_WORKER_ENABLED=false
ALLOWED_ORIGINS=${{backend.ALLOWED_ORIGINS}}
EMBEDDING_PROVIDER=${{backend.EMBEDDING_PROVIDER}}
INVESTIGATION_PROVIDER=${{backend.INVESTIGATION_PROVIDER}}
STRATEGY_PROVIDER=${{backend.STRATEGY_PROVIDER}}
WORKER_POLL_SECONDS=2
WORKER_LEASE_SECONDS=300
WORKER_HEARTBEAT_SECONDS=30
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=2
```

Start provider-disabled for the fictional smoke test. For existing AI analysis, set `OPENAI_API_KEY` only on backend, reference `${{backend.OPENAI_API_KEY}}` on worker, and enable the intended backend provider flags. Share nondefault model names/timeouts with worker. Enabling providers sends the existing flow's data externally; review data authorization first.

## 5. Deploy and check in order

1. **migration**: require `migration_completed revision=head runtime_roles=restricted` and exit code 0. Stop the release on failure.
2. **backend**: require `api_started ... inline_worker=False` and `https://BACKEND-DOMAIN/health` returning `{"status":"ok"}`. Startup rejects superuser/wrong-role credentials, stale schema, missing pgvector or missing tenant policies.
3. **worker**: require `worker_started` and Railway health check passing.
4. **frontend**: open its public **HTTPS** domain and `/health`. Readiness checks private API connectivity. Register two fictional accounts; import `examples/v1-ecommerce.csv` and `examples/v1-business-notes.md`; submit an investigation and wait for saved worker output. Verify account B cannot access account A's data. Refresh, logout and login again.
5. Browser DevTools: verify `marketmind_session` is HttpOnly/Secure/SameSite=Lax, requests use the frontend `/api/...`, and logout clears the cookie. Missing/hostile Origin writes return 403. PostgreSQL authentication counters apply across API replicas; network buckets can group users behind Next.js/Railway.

If initial GitHub deployments started early, redeploy in this order after configuration/migration. On later schema releases, back up and run the new migration job first. Coordinate breaking migrations with worker/API downtime. A worker renews its lease and fences domain/checkpoint commits; interrupted paid calls are not automatically replayed. Review failed jobs before explicitly submitting a new one.

## 6. Existing n8n Cloud URLs

Keep workflow logic, identifiers, approval/version fields and simulation-only behavior unchanged. Update existing URL/credential configuration only:

| Configuration | Production value |
|---|---|
| n8n `MARKETMIND_API_URL` / backend base URL | `https://BACKEND-DOMAIN` |
| Simulation callback HTTP Request URL | `https://BACKEND-DOMAIN/api/integrations/n8n/simulation-callback` |
| Google Sheets ingestion HTTP Request URL | `https://BACKEND-DOMAIN/api/integrations/google-sheets/<source_id>/ingest` |
| backend `N8N_WEBHOOK_URL` | existing active n8n Cloud production `/webhook/...` URL |
| backend `N8N_WEBHOOK_TOKEN` | existing outbound Header Auth secret |
| backend `N8N_CALLBACK_TOKEN` | separate existing callback bearer secret, at least 32 characters |

Webhook and callback secrets must differ. A new database has new source IDs/tokens: create a fictional source in MarketMind and put its one-time ingestion token in that source's existing n8n credential. Old database/source tokens will not authenticate it. Do not transfer customer records/workflows without approval.

Redeploy backend after setting n8n variables. Check an approved fictional simulation through acknowledgement, authenticated callback, queued evaluation and saved learning. Callback IDs are idempotent and must match the persisted tenant/execution/approval/version. Simulation completion is not a real business measurement.

## 7. Logs, backups and release gate

Use **Deployments → View Logs**. Useful events: `migration_completed`, `api_startup_failed`, `worker_started`, `job_started`, `job_finished`, `worker_poll_failed`, `lease_renewal_failed`, `api_proxy_failed`. Logs use safe codes and job/workspace IDs without prompts, payloads, tokens or database URLs. API `/live` checks process liveness; `/health` checks the database. Railway health checks gate deployments, not continuous uptime: configure external frontend/backend health monitoring. [Health checks](https://docs.railway.com/deployments/healthchecks)

`postgres` → **Backups**: enable daily/weekly volume backups and take a manual backup before migration. Keep an encrypted offsite `pg_dump -Fc` backup too, with admin credentials supplied through a protected environment/password file, never a command-line URL. Test restore in a separate empty project, run migration/role provisioning, and verify pgvector, tenant isolation and fictional records. Railway volume restores stay within the same project/environment. [Backup instructions](https://docs.railway.com/volumes/backups)

Production release requires green CI, HTTPS/cookies/CORS, independent jobs, two-account isolation, live n8n delivery, enabled-provider checks, restart behavior and a tested restore. Session revocation/password recovery and stronger edge abuse controls remain limits to review before customer onboarding. This preparation does not authorize customer imports.

## Optional current Railway IaC

[`.railway/railway.ts`](.railway/railway.ts) expresses the services/volume using Railway's current TypeScript SDK. The dashboard steps above need no CLI. Current documentation deprecates legacy `railway.json`/`railway.toml` and prevents new services opting into them. [Railway IaC](https://docs.railway.com/infrastructure-as-code)

After setting preserved variables in an empty project, install Railway CLI; run `npm ci --ignore-scripts` in `.railway`, then `railway login`, `railway link` and **`railway config plan`**. Review target/environment and every change before `railway config apply`. GitHub pushes do not apply this blueprint. Generate frontend/backend domains manually and fill the exact frontend origin; deploy migration before apps. For an existing project, import/reconcile its resources first: omitted resources in a whole-project file can be deleted.
