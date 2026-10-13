# Implementation verification — 2026-10-13

## Verified in this workspace

- Backend suite: **155 passed, 2 skipped**. Coverage includes source corrections and deletion tombstones, idempotent and competing conflict decisions, stale conflict matches, tenant authorization, appointment lifecycle dates, partial payments, explicit zero-activity coverage, unresolved/conflicting source completeness, concurrent source updates, and six complete fictional industry/outcome journeys.
- Ruff: all backend checks passed.
- Frontend: `npm run typecheck` and `npm run build` passed during V1 acceptance. Headless Edge browser journeys passed for both industries through onboarding, CSV/document uploads, actual background investigation and strategy, design, owner approval, callback evaluation, and saved learning. The appointment rerun exercised completion rate as the primary metric. Both journeys also verified document deletion and clearing the selected investigation. Outbound n8n HTTP alone was substituted. No browser runtime errors or 390px mobile page overflow were observed; desktop/mobile screenshots were inspected.
- V1 fixes: missing-result evaluation returns inconclusive; clearing the investigation selector clears its displayed report; completion types cover terminal callbacks. SQLite test sessions now use separate file-backed connections rather than one connection shared across LangGraph threads. The first review run encountered a Windows access violation with the original fixture; the complete corrected suite passed.
- Alembic full chain: upgraded a disposable SQLite database from empty schema through `0013_conflict_appointment_stability`; Alembic reported 0013 as head. The temporary database was removed.
- SQLite migration tests: revisions 0011–0013 applied and downgraded in isolation, including current-record uniqueness, coverage history, decision uniqueness, deletion counts, and appointment date columns.
- Reconciliation concurrency test: concurrent requests from separate sources targeting the same business entity left at most one current accepted record. This test uses SQLite and does not establish PostgreSQL concurrency behavior.

## PostgreSQL status and production blockers

- A local PostgreSQL server answers on port 5432, but `psql` cannot authenticate noninteractively (`password authentication failed`); neither `TEST_MIGRATION_DATABASE_URL` nor `TEST_DATABASE_URL` is configured. No credentials were requested or read. PostgreSQL migration 0012/0013 and the complete PostgreSQL migration chain are **unverified**.
- Earlier isolated PostgreSQL checks for selected revisions 0006–0009 are recorded in prior verification history; these do not prove the complete chain or current source-reconciliation migrations.
- PostgreSQL RLS policies are **not configured**. Tenant isolation currently relies on application-level workspace-scoped queries and source-scoped bearer tokens. Database-level RLS is a production blocker until policies and transaction tenant context are added and tested for every tenant-owned table.
- Workflow job leases expire after five minutes and have no heartbeat. The job completion update checks the lease token, but workflow nodes can commit domain records before that final fenced update. A worker that outlives its lease can therefore persist output after another worker has recovered the job. Add lease renewal and token-checked domain writes (or an equivalent fencing design), then verify with competing PostgreSQL workers before production.
- Two pgvector-dependent tests were skipped; local pgvector availability, vector retrieval integration, PostgreSQL tenant isolation, PostgreSQL source-import uniqueness under concurrency, and Docker Compose startup remain unverified. Docker was unavailable in this review environment. The PostgreSQL authentication failure was rechecked during V1 acceptance; no dedicated test URLs were configured.

## Scope limits

- n8n Cloud workflows remain manually managed. No n8n workflow was generated or hosted.
- Google Sheets deletion requires the workflow to submit `deleted_source_event_ids`; automatic snapshot difference discovery and scheduled sync management are not implemented.
- Appointment bookings, scheduled appointments, and completions are separated by supplied dates; missing dates fall back to the source event timestamp, so date quality depends on source data.
- Live model-provider and n8n requests were not made. Shared agents ran actual industry rules and lexical retrieval in acceptance; no AI results were invented. Simulation results are not real business measurements or evidence of actual profit improvement. The captured n8n request/acknowledgement and authenticated callback tests verify the backend contract, not the website workflow or cloud reachability.

See [V1 release acceptance](../V1_RELEASE_CHECKLIST.md) for PASS/FAIL criteria and [the fictional demo guide](V1_DEMO.md). V1 development is frozen after local demonstration acceptance; external and production gates remain failed/unverified.

To run PostgreSQL migration tests, set `TEST_MIGRATION_DATABASE_URL` to a dedicated PostgreSQL database with permission to create schemas. The tests create and remove temporary schemas. Use `TEST_DATABASE_URL` for the PostgreSQL/API suite and a pgvector-enabled database for vector tests. Do not use a production or personal application database.
