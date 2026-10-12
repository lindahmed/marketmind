import json
import urllib.request

from app.intelligence.contracts import ApprovalVerifier, BusinessContext


class N8nExecutor:
    """Explicitly constructed by a future approved-job worker; never an open API route."""

    def __init__(self, webhook_url: str, token: str, approvals: ApprovalVerifier):
        if not webhook_url.startswith(("http://n8n:5678/", "https://")):
            raise ValueError("Use an internal n8n webhook or HTTPS")
        if not token:
            raise ValueError("Webhook authentication token required")
        self.webhook_url, self.token, self.approvals = webhook_url, token, approvals

    def execute(self, context: BusinessContext, experiment_id: str, approval_id: str) -> dict:
        self.approvals.require_approved(context.workspace_id, experiment_id, approval_id)
        payload = {"workspace_id": context.workspace_id, "experiment_id": experiment_id,
                   "approval_id": approval_id, "idempotency_key": f"{context.workspace_id}:{experiment_id}:{approval_id}"}
        request = urllib.request.Request(self.webhook_url, data=json.dumps(payload).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read(1_000_000))
