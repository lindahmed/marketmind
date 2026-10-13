# MarketMind V1 release checklist

Reviewed: 2026-10-13. Development is frozen.

**Local demonstration acceptance: PASS. Live cloud and production release gates: FAIL / unverified.** A FAIL below can mean a verification requirement could not be completed; it is not presented as a confirmed application defect.

The tested journey was onboarding → financial CSV ingestion → private evidence investigation → prioritized recommendation → measured experiment design → separate owner approval → n8n adapter acknowledgement → authenticated simulated completion → background evaluation → persisted learning. Both e-commerce and appointment businesses used fictional data. Shared agents ran the actual industry rules with external model providers disabled. Only the outbound n8n HTTP transport was substituted; no agent, financial calculation, approval check, callback handler, or evaluation result was mocked.

## Local V1 demonstration criteria

| Acceptance criterion | Result | Evidence |
| --- | --- | --- |
| Both industries can register, sign out, sign in, and save goals/budget | PASS | API journeys and browser onboarding/profile saves |
| Fourteen complete fictional baseline days import successfully | PASS | Both browser journeys and six API journeys |
| Financial metrics handle refunds/costs/unknown outcomes conservatively | PASS | Financial reporting and reconciliation regression suites |
| Sources retain duplicate/conflict/correction/deletion provenance | PASS | Data-source and migration regression suites |
| Private documents support scoped retrieval and investigation evidence | PASS | Browser uploads, API evidence assertions, RAG regression suites |
| Browser document deletion and clearing investigation selection work | PASS | Both browser journeys confirmed authenticated deletion and removal of stale report UI |
| Investigation runs as a durable job and shows saved evidence | PASS | Browser worker/polling flow and checkpoint tests |
| Recommendations have evidence, priorities, and budget/constraint checks | PASS | Actual rule-agent output and growth regression tests |
| An unapproved recommendation cannot create an experiment design | PASS | Both industry API journeys return 409 before approval |
| Designs save hypotheses, baseline, primary target, cost, and guardrails | PASS | Both industries; appointment primary completion-rate and store profit tests |
| Recommendation approval does not dispatch; experiment approval is separate | PASS | No dispatch rows before exact experiment approval |
| Owner authorization and tenant boundaries hold throughout the journey | PASS | Foreign tenant denials for jobs, approvals, experiment history, and private learning |
| n8n adapter sends structured, approved simulation-only payloads | PASS | Real adapter with captured transport, server-only bearer header and safe metadata |
| Repeat approval does not produce a second dispatch | PASS | Same execution ID returned, one outbound request |
| HTTP acknowledgement cannot be mistaken for completion/evaluation | PASS | `acknowledged` / `not_reported`; no evaluation before callback |
| Callback authentication, persisted relationships, replay protection hold | PASS | Unauthorized/mismatched/duplicate callbacks covered by regression tests |
| Success, failure, and incomplete data produce appropriate evaluations | PASS | All three cases tested through the complete journey for both industries |
| Simulated outcomes never change imported dashboard financial results | PASS | Before/after KPI equality in both industries, all callback outcomes |
| Learning is persisted once, tenant-scoped, and usable in later investigations | PASS | Six API journeys; browser history shows saved learning |
| Reports disclose simulated data and no verified actual profit improvement | PASS | Explicit report/learning flags and browser text |
| Frontend completes the full journey without JavaScript runtime errors | PASS | Headless Edge browser, both industries, actual FastAPI worker and UI |
| Desktop/mobile experiment reports remain usable without page overflow | PASS | Desktop screenshots and 390px mobile assertions/screenshots |
| Backend regression suite and lint pass | PASS | 155 passed, 2 pgvector checks skipped; Ruff passed |
| Frontend type check and production build pass | PASS | `npm run typecheck`; `npm run build` |
| Fresh SQLite database applies the entire migration chain | PASS | Browser database migrated through `0013_conflict_appointment_stability` |
| Release instructions and truthful limitations are documented | PASS | This checklist, V1 demo guide, verification record, roadmap |

## External verification and production gates

| Acceptance criterion | Result | Remaining limitation |
| --- | --- | --- |
| Actual manually configured n8n Cloud workflow completes its callback | FAIL | Cloud transport was substituted. Website workflow, credentials, public callback reachability, and node mappings were not exercised live |
| Live model-provider investigation/strategy and embedding requests verified | FAIL | Providers were disabled. Existing structured-provider contract tests passed; live requests were not made |
| PostgreSQL full migration chain, current reconciliation concurrency, and pgvector verified | FAIL | No dedicated PostgreSQL test URL configured; local noninteractive `psql` authentication failed. Two vector tests skipped |
| Docker Compose deployment starts and persists data | FAIL | Docker executable unavailable in this review environment |
| Database RLS and robust competing-worker lease safety support production | FAIL | RLS absent; five-minute leases lack heartbeats and token-fenced domain writes. Production blockers remain |

## Fixes made during acceptance

- Missing simulation-result evaluation now returns an inconclusive report instead of raising a keyword-argument error.
- SQLite tests use separate file-backed connections for LangGraph checkpoint threads. The original shared in-memory connection produced intermittent failures and a Windows access violation; the full corrected suite passed.
- Clearing the saved-investigation selector also clears the displayed report. Frontend completion types now cover completed/failed callbacks, and the shell identifies V1 simulations clearly.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_v1_acceptance.py -q --basetemp=.tmp/v1-acceptance
.\.venv\Scripts\python.exe -m pytest backend/tests -q --basetemp=.tmp/v1-regression
.\.venv\Scripts\ruff.exe check backend/app backend/tests backend/migrations
cd frontend
npm run typecheck
npm run build
```

See [the manual demonstration guide](docs/V1_DEMO.md). Automated API acceptance uses isolated temporary databases and a substituted external transport, so no cloud secrets or external spend are required. Browser acceptance used an isolated SQLite database, actual single-process FastAPI worker, Next.js UI, and a disposable transport test harness; desktop/mobile evidence is retained locally under `.tmp/v1-*.png`, with results in `.tmp/v1-browser-results.json`. Those local artifacts are ignored by Git.

All local demonstration criteria passed. No further feature development was performed. External and production FAIL entries must remain visible when presenting V1.
