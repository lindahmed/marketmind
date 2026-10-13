# n8n Cloud: approved simulation webhook

MarketMind sends only `simulation_only` experiments. The webhook payload contains the workspace, experiment and approval IDs, immutable version, execution ID, idempotency key, approved action type, approval timestamp and one allowlisted scenario value. It does not contain customer data or experiment notes. A successful HTTP response means n8n accepted the webhook; it does not mean the workflow or experiment finished successfully.

## Build the workflow manually in n8n Cloud

1. In n8n Cloud, create a workflow and add a **Webhook** trigger.
2. Set **HTTP Method** to `POST` and **Path** to `marketmind-experiment`.
3. Under **Authentication**, select **Header Auth**. Create a credential with header name `Authorization` and value `Bearer <the same random secret configured in the backend>`.
4. Set **Respond** to **Immediately**. This acknowledges receipt without waiting for the remaining nodes.
5. Add an **If** node. Check all three incoming body fields:
   - `{{ $json.body.schema_version }}` equals `1`
   - `{{ $json.body.mode }}` equals `simulation_only`
   - `{{ $json.body.approved_action_type }}` equals `simulation_only`
6. From the true output, add an **Edit Fields (Set)** node to create a simulation-only result. For example, add `simulation_status` with value `received_for_simulation` and copy `{{ $json.body.execution_id }}` into `execution_id`. Do not add an advertising, messaging, or other external action node for this first workflow. The false output can remain unconnected.
7. For a test, select **Test URL** on the Webhook node and click **Listen for Test Event**. For real backend dispatches, publish the workflow and use its **Production URL**. The production webhook is registered when the workflow is published. n8n documents the test and production URL behavior and Header Auth option in its [Webhook node guide](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/).

## Configure the FastAPI backend

Generate a random value locally, for example with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. In the root `.env`, set:

```dotenv
N8N_WEBHOOK_URL=https://your-instance.app.n8n.cloud/webhook/marketmind-experiment
N8N_WEBHOOK_TOKEN=<the-random-value>
```

Use the exact Production URL shown by your n8n Webhook node. For a temporary test, use the Test URL while **Listen for Test Event** is active; replace it with the Production URL afterward. Enter the same random value in the n8n Header Auth credential as `Bearer <value>`. Keep the value only in the backend `.env` and n8n credential; it is never returned by the API or sent to the frontend. Stop any previous local FastAPI process, then run from the repository root:

To copy the exact credential value from `.env` without printing the secret, run this in your own PowerShell terminal from the repository root, then paste into the credential's **Value** field. The credential's **Name** field must contain `Authorization`:

```powershell
.\.venv\Scripts\python.exe -c "from dotenv import dotenv_values; print('Bearer ' + dotenv_values('.env')['N8N_WEBHOOK_TOKEN'])" | Set-Clipboard
```

Apply migrations and start FastAPI:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

With Docker Compose, `docker compose up --build -d backend` applies migrations and restarts FastAPI.

If migration fails with **password authentication failed**, PostgreSQL rejected the credentials in `DATABASE_URL`; n8n has not been contacted. A generated `POSTGRES_PASSWORD` in `.env` does not change the password in an already installed PostgreSQL server. Use that server's actual credentials. If your API already uses a SQLite preview, set the root `.env` `DATABASE_URL` to the absolute path of that same existing preview database so Alembic and FastAPI use the same accounts and data. Restart FastAPI after editing `.env`; settings are cached until restart.

## Send a simulation test

Use an existing MarketMind account and its owner credentials in PowerShell. The login cookie is held in a web request session:

```powershell
$api = "http://localhost:8000/api"
$session = [Microsoft.PowerShell.Commands.WebRequestSession]::new()
$credentials = @{ email = "owner@example.com"; password = "YOUR_PASSWORD" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$api/auth/login" -WebSession $session -ContentType "application/json" -Body $credentials
$me = Invoke-RestMethod -Method Get -Uri "$api/auth/me" -WebSession $session
$workspaceId = $me.workspaces[0].id
$headers = @{ "X-Workspace-ID" = $workspaceId }
$experimentBody = @{
  name = "Conversion simulation"
  action_type = "simulation_only"
  metadata = @{ scenario = "conversion_lift" }
} | ConvertTo-Json -Depth 5
$experiment = Invoke-RestMethod -Method Post -Uri "$api/experiments" -WebSession $session -Headers $headers -ContentType "application/json" -Body $experimentBody
$dispatch = Invoke-RestMethod -Method Post -Uri "$api/experiments/$($experiment.id)/approve" -WebSession $session -Headers $headers
$dispatch | Format-List
```

Expected response fields include `dispatch_status: acknowledged`, an `execution_id`, and `completion_status: not_reported`. Confirm the execution appears in the n8n workflow's **Executions** view. Repeating the approve request returns the same execution ID and does not send another webhook. A failed dispatch is persisted and is not automatically retried, since a network failure can leave receipt uncertain; inspect n8n Executions before taking any manual recovery action.

For an HTTP `403`, check the selected Header Auth credential: the header name must be `Authorization`, and its complete value must be `Bearer ` followed by the backend's `N8N_WEBHOOK_TOKEN`, without angle brackets or the variable name. Save the credential and listen again. After correcting a failed dispatch, create and approve a fresh simulation experiment; reapproving the failed experiment deliberately does not send another webhook.

Only workspace owners who created the draft may approve it. Approval and dispatch records are workspace scoped, each experiment version has one approval and a database-unique idempotency key, and the adapter rechecks the persisted approval immediately before sending. The n8n credential is sent over HTTPS in an Authorization header; redirects are disabled so the secret cannot be forwarded to another host.
