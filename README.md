# MarketMind AI

A multi-tenant marketing intelligence platform for small businesses. Foundation milestone: private workspaces, authentication, business context, industry packs, daily CSV imports, and a profit-aware dashboard.

## Run with Docker

Requires Docker with Compose, Python 3.13+ for generating configuration, and available ports 3000, 8000, and 5432.

```powershell
python scripts/setup_env.py
docker compose up --build
```

Open [the dashboard](http://localhost:3000) and [API documentation](http://localhost:8000/docs). Register an account, set your business currency/goals/budget, and import the matching CSV from `examples/`. Data persists in the PostgreSQL volume. `docker compose down` preserves it.

Optional automation service: `docker compose --profile automation up --build`. Open [n8n](http://localhost:5678) and complete its owner setup. No external marketing actions or workflows run automatically.

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
backend/migrations/       Alembic schema history
backend/tests/            API, tenant boundaries, analytics, AI integration contracts
examples/                 CSV examples for both industries
docs/ROADMAP.md            Milestones and production requirements
```

Each account initially owns one workspace. Memberships support future access to multiple workspaces; `X-Workspace-ID` selects only a workspace the authenticated user belongs to. Every business-data query is scoped to that verified workspace. There is no public knowledge or execution API yet. Private knowledge supports BM25 search and opt-in OpenAI embeddings with tenant-filtered pgvector hybrid retrieval. Evidence investigations can optionally use OpenAI structured analysis with checked citations, saved usage/cost estimates, and tenant audit events. See [embedding setup](docs/EMBEDDINGS.md) and [investigation setup](docs/INVESTIGATIONS.md); durable processing remains under development.

The four-stage LangGraph factory accepts shared agents and one business context per run. It stops at experiment design. Execution/evaluation contracts are defined separately; the n8n adapter requires an injected approval verifier before any request. Concrete LLM agents, approval storage, and experiment execution are next milestones.

## Data and analytics

- E-commerce: `date,revenue,orders,ad_spend,cost_of_goods`.
- Appointments: `date,revenue,bookings,completed,ad_spend,variable_cost`.
- Dates are ISO `YYYY-MM-DD`, unique within a file. Values must be finite and nonnegative; counts must be integers. Completed appointments cannot exceed bookings.
- Uploads are limited to 2 MB / 10,000 rows. A successful import atomically replaces existing dates in the same workspace; dates omitted from the file remain.
- Estimated profit = revenue − variable costs − ad spend; fixed costs and taxes are excluded. ROAS uses total revenue, so it does not establish advertising attribution.
- Rule diagnostics flag negative profit, low revenue/spend ratio, low appointment completion, and a revenue drop across two complete consecutive seven-day windows. These are symptoms with evidence, not AI root-cause conclusions.

## Private evidence preview

Upload UTF-8 `.txt` or `.md` business notes from the Private knowledge workspace, find relevant chunks, and create a saved evidence review. Search uses BM25 by default. Configure the opt-in [embedding provider](docs/EMBEDDINGS.md) to embed newly uploaded chunks and combine PostgreSQL/pgvector cosine similarity with lexical search. The UI discloses when OpenAI processes uploads and queries. Reviews record metric rules and supporting excerpts; retrieval matches cannot establish a cause. Provider generated answers, long running jobs, checkpoints, and attributed root causes remain future Milestone 2 work.

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

See [local verification results](docs/VERIFICATION.md) for completed checks and the remaining Docker/pgvector verification gap.

## Security and deployment

Argon2 password hashes, expiring signed sessions in HttpOnly/SameSite cookies, explicit browser Origin checks, and server-verified memberships protect the foundation. Local Compose binds services to loopback. Configure HTTPS, `COOKIE_SECURE=true`, exact `ALLOWED_ORIGINS`, strong secrets, and a restricted runtime database role before deployment. Authentication rate limits, email verification/password recovery, revocable sessions, audit trails, and PostgreSQL RLS are tracked in the roadmap. The current deployment is intended for local development.
