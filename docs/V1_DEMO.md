# MarketMind V1 fictional demonstration

V1 is frozen as a local simulation demonstration. All imported values below are fictional. Evidence rules and hypotheses are not verified root causes; simulation criteria are not actual business improvement.

## Preparation

1. Follow the local startup instructions in the root README and run `alembic upgrade head` before FastAPI. Start one FastAPI process and the frontend, using `localhost` consistently. SQLite supports this demonstration with lexical retrieval; semantic vector retrieval requires PostgreSQL/pgvector.
2. For the same evidence-rule mode used in acceptance, set `INVESTIGATION_PROVIDER=disabled`, `STRATEGY_PROVIDER=disabled`, and `EMBEDDING_PROVIDER=disabled` in backend configuration before restarting. The UI labels evidence reviews and industry-rule recommendations accurately. Enabling a provider sends private data externally and is a separate, unverified live-provider path.
3. To use real n8n Cloud, manually configure the nodes and separate credentials in [webhook setup](N8N_CLOUD_SETUP.md) and [callback setup](N8N_CLOUD_FEEDBACK.md). n8n Cloud must be able to reach your configured public HTTPS callback URL; `localhost` on your computer is not reachable from n8n Cloud. The review did not call a cloud workflow. Automated acceptance substitutes outbound HTTP only.

## Repeat for each business type

1. Register a new fictional workspace using **E-commerce** or **Appointment-based**. Under Business profile, set USD, a monthly budget of 100, goals `Improve profit` and `Improve completion`, and save. Keep the account separate for each industry.
2. Import [v1-ecommerce.csv](../examples/v1-ecommerce.csv) or [v1-appointments.csv](../examples/v1-appointments.csv). Each contains fourteen complete days, 2026-01-05 through 2026-01-18, with explicitly reported zero fixed costs. Confirm fourteen saved rows; review refunds, contribution profit, and fulfillment/completion metrics in Overview. The negative fictional profit is deliberate.
3. Under Private knowledge, upload [v1-business-notes.md](../examples/v1-business-notes.md). Ask `Why are profit and completion weak?` and choose **Collect evidence +**. Wait for the investigation job to complete. Inspect rule findings, private excerpts, and evidence IDs before proceeding.
4. Generate prioritized recommendations. For the store, choose a profit-related proposal. For appointments, choose the proposal targeting completion rate to show its industry-specific path. Review the hypothesis, evidence, constraints, and estimated costs, then **Approve recommendation for design**.
5. Set baseline start `2026-01-05`, end `2026-01-18`, reviewed cost `10`, minimum increase `5`, duration `14`, and minimum volume `30`. Create the experiment draft and inspect its saved baseline, target, and profit guardrail. These targets are desired thresholds, not forecasts.
6. Open Experiments. **Approve and dispatch simulation** is a separate owner action. A missing cloud configuration produces a clear configuration error. With a configured webhook, acknowledgement indicates receipt; completion remains `not_reported` until a valid callback arrives. Repeated approval must return the same execution ID.
7. In your manually managed n8n simulation, preserve the incoming IDs. Submit an explicitly simulated callback for 2026-01-19 through 2026-02-01, with fourteen observed days, zero missing days, reported complete costs, and at least thirty orders/bookings. Use the saved primary metric key and target plus `estimated_profit` in daily currency units at or above the saved guardrail. For completion rate, values use percentage points, not fractions. The incoming webhook contains safe scenario metadata; copy the reviewed measurement criteria from the saved design into your simulation node.
8. Refresh status and open **View history and evaluation**. Wait for the evaluation job to complete. Check the comparison, limitations, audit history, and saved learning. A success is labeled `simulation_met_criteria`; it verifies only the callback's simulated values against saved criteria. Dashboard imported financial totals must remain unchanged.
9. Run another investigation asking `What did the profit and completion simulation teach?`. Relevant saved learning should appear explicitly marked as simulation evidence. The other business's workspace must not expose this history or learning.

For the failure demonstration, submit `experiment.simulation.failed` with a safe failure code and no result for a separate approved execution. For the incomplete-data demonstration, submit a completed simulated result with `financial_data_complete=false`; evaluation must be inconclusive. Do not submit contradictory terminal callbacks for one execution: different second completions are rejected, while identical callback retries are idempotent.

## Release limits

See [V1_RELEASE_CHECKLIST.md](../V1_RELEASE_CHECKLIST.md) and [VERIFICATION.md](VERIFICATION.md). Local browser/API acceptance passed. Actual n8n Cloud delivery, live models, PostgreSQL/pgvector and Docker remain unverified. RLS and worker lease fencing remain production blockers. Use one local API process for the demonstration; do not present this release as production-ready or as evidence of actual profit uplift.
