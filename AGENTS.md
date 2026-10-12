# MarketMind contributor instructions

- Use English or Franco-Arabic in communication and documentation.
- Keep this a modular monorepo: Next.js in `frontend`, FastAPI in `backend`.
- Agents are shared. Adapt behavior through `IndustryPack` and verified `BusinessContext`; never fork agents by industry or tenant.
- Every business query, knowledge retrieval, cache key, queued job, and memory record must include its verified workspace ID. Resolve workspace access through authenticated membership, never a request body alone.
- Do not add execution routes that bypass persisted human approval. Approval must belong to the workspace and exact experiment version; budgets and constraints must be checked before dispatch.
- Keep JWTs in HttpOnly cookies. Never put session tokens or provider secrets into browser storage, logs, source control, or public Next.js environment variables.
- Use Alembic migrations for schema changes. Do not create tables on application startup.
- Add industries through the pack registry and compatible metric validation. New industry codes also need registration schema/frontend options and tests.
- Show real imported data and explicit empty states. Label estimates and rule findings accurately.
- Run relevant backend tests, Ruff, frontend type checking, and production build before reporting a milestone complete. PostgreSQL integration checks are required when database behavior changes.
- Prefer small dependencies and clear modules. Avoid speculative services, duplicated abstractions, and implementing future milestones prematurely.
