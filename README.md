# MarketMind AI

A multi-tenant marketing intelligence platform for small businesses. The current implementation includes private workspaces, authentication, industry packs, financial CSV reporting, private knowledge, optional provider-backed investigations, and approval-gated n8n Cloud simulations.

**V1 is frozen for local simulation demonstrations.** Both industry browser/API journeys passed; actual cloud/provider delivery and production database/worker guarantees remain unverified. See [V1 release checklist](V1_RELEASE_CHECKLIST.md) and [fictional demonstration steps](docs/V1_DEMO.md).

## Run with Docker

Requires Docker with Compose, Python 3.13+ for generating configuration, and available ports 3000, 8000, and 5432.

```powershell
python scripts/setup_env.py
docker compose up --build
```

Open [the dashboard](http://localhost:3000) and [API documentation](http://localhost:8000/docs). Register an account, set your business currency/goals/budget, and import the matching CSV from `examples/`. Data persists in the PostgreSQL volume. `docker compose down` preserves it.

Optional automation: connect an n8n Cloud webhook using [manual setup instructions](docs/N8N_CLOUD_SETUP.md). MarketMind does not install or host n8n. Only simulation-only approved experiments can be dispatched by this integration.

## Local development

Requires Python 3.13+, Node 22+, and Docker for PostgreSQL. Run commands from the repository root unless a directory change is shown.

```powershell
python scripts/setup_env.py  # skip if .env already exists
docker compose up -d postgres
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

The browser defaults to `http://localhost:8000`; set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` to change it. Use `localhost` consistently for both services so cookies work. Backend settings load the root `.env` when run from `backend/`.

Without Docker, a **local SQLite preview** supports accounts, profiles, and CSV analytics, but does not support pgvector retrieval:

```powershell
cd backend
$env:DATABASE_URL = 'sqlite:///./preview.db'
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## Structure

```text
frontend/src/app/          Next.js application and workspace shell
frontend/src/components/  Auth, dashboard, profile, and import screens
frontend/src/lib/         Typed API client and response contracts
backend/app/              Auth, tenancy, business API, models, analytics
backend/app/industries.py Configurable e-commerce and appointment packs
backend/app/intelligence/ Shared LangGraph, agent contracts, scoped pgvector retrieval
backend/app/integrations/ Approval-gated n8n webhook adapter
backend/app/workflow_jobs.py Durable tenant-scoped LangGraph job worker
backend/migrations/       Alembic schema history
backend/tests/            API, tenant boundaries, analytics, AI integration contracts
examples/                 CSV examples for both industries
docs/ROADMAP.md            Milestones and production requirements
```

Each account initially owns one workspace. Memberships support future access to multiple workspaces; `X-Workspace-ID` selects only a workspace the authenticated user belongs to. Every business-data query is scoped to that verified workspace. Knowledge and experiment routes require authentication. Private knowledge supports BM25 search and opt-in OpenAI embeddings with tenant-filtered pgvector hybrid retrieval. Evidence investigations can optionally use OpenAI structured analysis with checked citations, saved usage/cost estimates, and tenant audit events. Investigation, growth-strategy, and experiment-evaluation work runs through persistent, tenant-scoped jobs with LangGraph checkpoints. See [embedding setup](docs/EMBEDDINGS.md), [investigation setup](docs/INVESTIGATIONS.md), and [durable workflow operations](docs/DURABLE_WORKFLOWS.md).

Shared LangGraph agents use verified business context, persisted owner gates, and tenant-scoped durable jobs. The n8n Cloud adapter verifies persisted workspace ownership and approval before sending a simulation-only event. A 2xx webhook response records receipt acknowledgement, not completed execution. Authenticated callbacks queue deterministic evaluation and persist labeled learning; see [simulation callback setup](docs/N8N_CLOUD_FEEDBACK.md). Live marketing actions are not enabled.

Shared Growth Strategy and Experiment Design agents now connect saved investigations to prioritized recommendations and measurable drafts. Open a saved investigation under **Private knowledge**, generate recommendations, approve one as its workspace owner, then supply a complete baseline, reviewed cost, and minimum improvement target. Drafts retain the hypothesis, evidence, baseline, profit guardrail, and success/failure/inconclusive criteria. See [strategy and experiment design](docs/STRATEGY_AND_EXPERIMENTS.md). Generating or designing does not dispatch n8n.

## Data and analytics

- The import screen offers detailed templates with gross revenue, refunds, variable costs, and fulfillment or appointment outcomes. Both original CSV formats remain supported. See [financial reporting definitions and CSV headers](docs/FINANCIAL_REPORTING.md).
- Connect a Google Sheet through a manually managed n8n Cloud workflow from **Data Sources & Data Quality**. MarketMind issues a source-scoped one-time token, retains import provenance, and flags duplicates, conflicts, and incomplete events. See [Google Sheets + n8n setup](docs/GOOGLE_SHEETS_N8N_SETUP.md).
- Dates are ISO `YYYY-MM-DD`, unique within a file. Monetary values must be finite, nonnegative, and have at most two decimal places; counts must be nonnegative integers. Fulfilled and cancelled orders are exclusive; delayed orders may overlap fulfilled orders but cannot overlap cancellations. Completed and cancelled appointments are exclusive.
- Uploads are limited to 2 MB / 10,000 rows. A successful import atomically replaces existing dates in the same workspace; dates omitted from the file remain.
- Estimated contribution profit = gross revenue − refunds − reported variable costs − ad spend. With full fixed-cost coverage, the dashboard also shows estimated operating profit. Both exclude taxes and unreported expenses and are not accounting profit. Campaign IDs are recorded as source labels without causal advertising attribution.
- `refund_revenue_percentage` measures refund money / gross revenue, not a product return count. Fulfillment rate measures fulfilled orders / total orders and is `null` if outcomes are unavailable for any selected row or total orders are zero.
- Select a reporting period in the dashboard or pass inclusive `start_date` and `end_date` to `GET /api/dashboard`. Missing dates are disclosed and never treated as zero-sales days. Legacy imports display a warning about omitted financial/outcome data.
- Rule diagnostics flag negative estimated profit, low net revenue/spend ratio, low appointment completion, and a revenue drop across two fully observed Monday–Sunday weeks. These are symptoms with evidence, not AI root-cause conclusions.

## Private evidence preview

Upload UTF-8 `.txt` or `.md` business notes from the Private knowledge workspace, find relevant chunks, and create a saved evidence review. Search uses BM25 by default. Configure the opt-in [embedding provider](docs/EMBEDDINGS.md) to embed newly uploaded chunks and combine PostgreSQL/pgvector cosine similarity with lexical search. The UI discloses when OpenAI processes uploads and queries. Reviews record metric rules and supporting excerpts; retrieval matches cannot establish a cause. Optional structured provider analysis and durable workflow jobs/checkpoints are implemented; independent validation of causal claims remains future work.

## Checks

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m ruff check app tests migrations
cd ../frontend
npm run typecheck
npm run build
```

Tests default to isolated SQLite databases. Set `TEST_DATABASE_URL` to a dedicated PostgreSQL test database with pgvector to also run API tests on PostgreSQL and test real vector retrieval. GitHub Actions runs both database modes plus frontend checks.

Migration 0006 also has a standalone financial backfill/round-trip test. Set `TEST_MIGRATION_DATABASE_URL` to a dedicated PostgreSQL database and run `python -m pytest -q tests/test_financial_migration.py` from `backend/`. This test creates and removes an isolated schema and needs schema creation permission; it does not require pgvector or replace the full-chain PostgreSQL checks. Run `alembic upgrade head` before starting the backend after pulling schema changes.

See [local verification results](docs/VERIFICATION.md) for completed checks and the remaining Docker/pgvector verification gap.

## Security and deployment

Argon2 password hashes, expiring signed sessions in HttpOnly/SameSite cookies, explicit browser Origin checks, and server-verified memberships protect the foundation. Local Compose binds services to loopback. Configure HTTPS, `COOKIE_SECURE=true`, exact `ALLOWED_ORIGINS`, strong secrets, and a restricted runtime database role before deployment. Authentication rate limits, email verification/password recovery, revocable sessions, audit trails, and PostgreSQL RLS are tracked in the roadmap. The current deployment is intended for local development.
