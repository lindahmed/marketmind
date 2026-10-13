# Growth Strategy and Experiment Design

Migration 0007 adds strategy runs, recommendations, version-bound owner approvals, and immutable experiment designs. Existing investigations, industry packs, authentication, tenant verification, and n8n simulation approval remain in use.

## Run the milestone

Apply migrations before restarting FastAPI:

```powershell
Set-Location C:\Users\Linda\marketmind\backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Use `http://localhost:3000` for the frontend and `http://localhost:8000` for FastAPI, matching the default cookie/CORS configuration. Run `npm run dev` from `frontend/` in another terminal.

1. Configure business goals, monthly budget and constraints. Import detailed financial records covering at least seven consecutive days with adequate orders/bookings.
2. In **Private knowledge**, create a new investigation. Older investigations without financial snapshot provenance remain readable, but need rerunning before strategy generation.
3. Select the saved investigation and click **Generate prioritized recommendations**. Review evidence, hypothesis, goal alignment, cost assumptions, and priority.
4. As a workspace owner, approve a recommendation for design or reject it. Nonempty constraints require explicit acknowledgement. Approval is saved for that exact version; it is not permission to execute a marketing action.
5. Supply a 7–90 day baseline inside the investigation's reporting period, reviewed cash cost, minimum absolute improvement, 7–90 day measurement duration, and minimum volume. Save the experiment draft.
6. Open **Experiments** to review draft plans. The creating workspace owner can approve a draft for a simulation webhook or reject it. Approval rechecks current budget, constraints, evidence, and baseline. A rejected draft cannot be dispatched.
7. Refresh the experiment list to see the execution ID, webhook acknowledgement/failure, and completion status. An acknowledgement is receipt only; completion stays `not_reported` until an authenticated simulation callback arrives. Then background evaluation compares simulated values with saved criteria and stores labeled learning. Open history to inspect the evaluation, limitations, and decisions; see [callback setup](N8N_CLOUD_FEEDBACK.md).

## Shared agents and honest outputs

`GrowthStrategyAgent` is shared across workspaces. Each industry pack supplies conservative diagnostic/action plays. The default `STRATEGY_PROVIDER=disabled` uses actual investigation rule evidence, labels results `industry_rule`, and leaves model/usage fields `null`. It ranks by evidence severity, configured business-goal matches, and estimated cost after budget/explicit action filters. If no permitted action is supported, it persists an empty strategy result instead of inventing recommendations.

For model-generated recommendations, explicitly configure root `.env`:

```dotenv
INVESTIGATION_PROVIDER=openai
STRATEGY_PROVIDER=openai
INVESTIGATION_MODEL=gpt-4o-mini
OPENAI_API_KEY=<your server-only key>
```

The strategy provider reuses the bounded structured OpenAI transport, timeout, usage accounting, and cost schedule. It requires an analyzed investigation and cites evidence actually referenced by its analysis. Action types, KPIs, goal links, direction, cost limits, and citation IDs are validated before persistence. Provider recommendations remain proposals, not established causes or promised uplift. The frontend discloses external processing before generation. The key never goes to the browser.

Rule-play cash estimates start at zero for review/pilots using existing tools and explicitly exclude staff time and paid services. Model estimates are unverified estimates with assumptions. The owner supplies the reviewed experiment cost. The monthly budget check is a cap; it does not verify remaining funds or reserve aggregate spend. Free-form constraints require owner review even when explicit action restrictions are filtered automatically.

`ExperimentDesignAgent` is shared and computes its baseline from tenant-owned imported data, rather than asking a model to invent numbers. It requires fully observed detailed financial data and at least 30 orders or 20 bookings (or the larger owner-selected minimum). These pilot volume thresholds do not establish statistical power. Money/count metrics use per-calendar-day values; rates and unattributed revenue/ad-spend ratio use period ratios. Minimum change is an absolute target in the displayed units, not a forecast.

Success requires the primary target and the daily contribution-profit guardrail, complete comparable observations, and adequate volume. Missing dates/costs, insufficient volume, concurrent changes, or inconsistent definitions make the result inconclusive. Measurement must follow the baseline and actual intervention. A before/after pilot cannot prove causation or statistical significance; simulated results cannot prove live improvement.

## API and lifecycle

All routes use HttpOnly sessions and verified workspace membership. `X-Workspace-ID` can only select an authorized workspace.

| Route | Purpose |
| --- | --- |
| `POST /api/investigations/{id}/recommendations` | Generate/retrieve one strategy for the evidence/context/provider revision |
| `GET /api/growth/recommendations?investigation_id={id}` | List persisted recommendations for that investigation |
| `POST /api/growth/recommendations/{id}/approve` | Owner approval; body `{"version":1,"constraints_acknowledged":true}` |
| `POST /api/growth/recommendations/{id}/reject` | Owner rejection of a proposed version |
| `POST /api/growth/recommendations/{id}/experiment-design` | Owner creates an immutable draft after persisted recommendation approval |
| `GET /api/experiment-designs` | List private saved designs |
| `GET /api/experiment-designs/{id}` | Read one private saved design |
| `GET /api/experiments` | List workspace experiments, safe plan summary, approval capability, and dispatch status |
| `POST /api/experiments/{id}/approve` | Recheck owner, version, budget, constraints, and plan freshness; dispatch the approved simulation idempotently |
| `POST /api/experiments/{id}/reject` | Reject a draft created by the current owner; never dispatches |

Example design request:

```json
{
  "baseline_start": "2026-01-05",
  "baseline_end": "2026-01-18",
  "estimated_cost": "10.00",
  "minimum_change": "5.0000",
  "duration_days": 14,
  "minimum_volume": 30
}
```

Strategy generation is deduplicated by investigation, business snapshot, provider/model, and prompt version. Approval binds to an immutable recommendation version. One immutable design can be created per recommendation; repeating identical parameters returns it, while changed parameters conflict. Plan revisions are future work.

Changing goals, budget, constraints, industry configuration, relevant imported financial data, or deleting source chunks invalidates new approval/design attempts. Recompute the investigation when evidence changes; regenerate recommendations when context changes. Saved historical records remain readable. Approval and design recheck membership, including whether the approving user remains an owner, and write tenant-scoped audit events.

The LangGraph growth path connects the persisted investigation agent result to the shared strategy agent. Recommendation generation ends before the owner gate; design crosses a separate node only after a persisted exact-version owner approval is loaded and checked. The shared deterministic design agent computes financial metrics and experiment constraints from tenant-owned records. No model computes or changes those values.

Each design links to an existing `Experiment` record in `draft` state, with a safe `simulation_only` dispatch action. The proposed business action and private plan stay in the design record; n8n receives only the existing safe scenario metadata contract after a separate exact-version experiment approval. Recommendation approval, experiment approval, webhook acknowledgement, and successful business completion are distinct events.

## Validation and remaining work

See [verification results](VERIFICATION.md). Tests cover both industries, goals/constraints/budget, exact approval versions, tenant/owner denial, changed context/data, source deletion, insufficient baseline data, persisted drafts, idempotency, structured provider contracts, and complete simulated callback/evaluation/learning journeys. Browser acceptance passed for both industries with substituted outbound n8n transport. Full PostgreSQL/pgvector and live-cloud/provider verification remain incomplete.

Simulation outcome evaluation and tenant-scoped learning are implemented. Live spend reservation, experiment revisions, real business measurements, and statistical comparisons are outside frozen V1. No real advertising spend is enabled.
