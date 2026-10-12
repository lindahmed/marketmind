# Foundation verification — 2026-10-12

Verified locally on Windows with Python 3.13 and Node 22:

- Backend: **17 passed, 1 skipped**. Covers authentication/cookies, forged sessions, cross-tenant reads/writes/imports, profile persistence, currency locking, atomic invalid imports, duplicate-email rollback, upload limits, both industry packs, profit calculations, import replacement, Origin protection, shared graph context, SQL retrieval scoping, and approval denial before webhook dispatch.
- Ruff: all checks passed. `pip check`: no broken requirements.
- Alembic: upgrade, downgrade, re-upgrade, and schema drift checks passed using an isolated SQLite database.
- Frontend: TypeScript check and production build passed. npm reported no known vulnerabilities during installation.
- Headless Edge browser: registration, initial empty dashboard, profile/currency/goals saving, real CSV upload, updated KPIs, persistence after reload, logout, and login all passed. Mobile layout at 390px had no horizontal overflow; desktop/mobile screenshots were visually inspected. No browser page errors.
- Example e-commerce import produced revenue **3,000**, variable costs **1,500**, ad spend **720**, and estimated profit **780** in the selected currency.

The local preview uses SQLite, separate from the PostgreSQL Docker configuration. Real PostgreSQL/pgvector execution and Docker startup were **not run locally**: Docker is absent, and the installed PostgreSQL has no vector extension. GitHub Actions is configured to run migrations and API tests on pgvector/PostgreSQL, plus real vector tenant-isolation coverage; that CI run has not happened yet.

The local Git repository was initialized from an empty folder. No GitHub remote URL was supplied or configured, and no changes were pushed.
