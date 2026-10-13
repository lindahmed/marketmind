# n8n Cloud simulation feedback

MarketMind accepts callbacks only for an existing, owner-approved `simulation_only` execution. A callback records workflow completion; it does not prove a real business outcome. The callback secret is separate from the outbound webhook credential.

## Backend setup

Generate a different random value of at least 32 characters for `N8N_CALLBACK_TOKEN` in the backend `.env`. Keep it in the n8n credential too; never put it in frontend configuration or chat. Set the public backend URL in the workflow as `MARKETMIND_API_URL`, for example `https://api.example.com`; n8n Cloud cannot reach your computer through `localhost`. Run `alembic upgrade head` and restart FastAPI. The endpoint is:

```text
POST {MARKETMIND_API_URL}/api/integrations/n8n/simulation-callback
Authorization: Bearer <N8N_CALLBACK_TOKEN>
Content-Type: application/json
```

## Nodes to add manually

In the existing approved-experiment workflow:

1. Keep the **Webhook** node with Header Auth for `N8N_WEBHOOK_TOKEN`; preserve its incoming execution, experiment, approval, version, workspace, and scenario fields.
2. Add a **Switch** or **If** node that permits only `mode = simulation_only`. Connect it to simulation-only nodes such as **Code** or **Edit Fields** that produce bounded sample values. Do not add ad-spend, email, SMS, customer, or advertising nodes.
3. On the success path, add **Edit Fields** to build the callback body, then an **HTTP Request** node using POST, JSON body, and a Header Auth credential containing `Authorization: Bearer <N8N_CALLBACK_TOKEN>`. Use a stable `callback_id`, such as `<execution_id>:completed`.
4. On the failure path, use **Edit Fields** plus a second **HTTP Request** to send `event = experiment.simulation.failed`, the same IDs, and a short safe `failure_code`; omit `result`. Use `<execution_id>:failed` as its callback ID.

Success body shape (fill values from the incoming webhook and your simulation node):

```json
{
  "callback_id": "<execution_id>:completed",
  "workspace_id": "<workspace_id>",
  "experiment_id": "<experiment_id>",
  "experiment_version": 1,
  "approval_id": "<approval_id>",
  "execution_id": "<execution_id>",
  "event": "experiment.simulation.completed",
  "mode": "simulation_only",
  "result": {
    "data_origin": "simulated",
    "period_start": "2026-02-02",
    "period_end": "2026-02-15",
    "observed_days": 14,
    "missing_days": 0,
    "financial_data_complete": true,
    "volume": 30,
    "metrics": {"estimated_profit": "-35.0000"}
  }
}
```

For a designed experiment, include its saved primary metric alongside `estimated_profit`; use the design's evaluation window, volume threshold, metric key, and units. Backend data-quality checks can mark the evaluation inconclusive. All values remain explicitly simulated.

After execution, open **Experiments → View history and evaluation**. Repeated identical callbacks are acknowledged as duplicates; a second completion for one execution is rejected. A callback must match the persisted workspace, approved experiment version, approval, and execution ID.
