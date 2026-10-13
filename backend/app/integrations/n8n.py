import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intelligence.contracts import ApprovalVerifier, BusinessContext
from app.models import Experiment, ExperimentApproval, Membership


@dataclass(frozen=True)
class DispatchOutcome:
    status: str
    http_status: int | None
    failure_code: str | None = None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the shared secret to another URL via a redirect.
        return None


class DatabaseApprovalVerifier:
    def __init__(self, db: Session):
        self.db = db

    def require_approved(self, workspace_id: str, experiment_id: str, approval_id: str) -> None:
        approval = self.db.scalar(select(ExperimentApproval).join(Experiment, Experiment.id == ExperimentApproval.experiment_id)
            .join(Membership, (Membership.user_id == ExperimentApproval.approved_by_user_id)
                  & (Membership.workspace_id == ExperimentApproval.workspace_id)).where(
            ExperimentApproval.id == approval_id,
            ExperimentApproval.workspace_id == workspace_id,
            ExperimentApproval.experiment_id == experiment_id,
            ExperimentApproval.experiment_version == Experiment.version,
            ExperimentApproval.status == "approved",
            Membership.role == "owner",
            Experiment.created_by_user_id == ExperimentApproval.approved_by_user_id,
            Experiment.workspace_id == workspace_id,
            Experiment.status == "approved",
        ))
        if approval is None:
            raise PermissionError("Experiment approval is invalid")


class N8nExecutor:
    """Dispatch an approved simulation request to an n8n Cloud webhook."""

    def __init__(self, webhook_url: str, token: str, approvals: ApprovalVerifier, timeout: float = 15):
        parsed = urllib.parse.urlsplit(webhook_url)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or not host.endswith(".n8n.cloud") or parsed.username or parsed.password
                or parsed.fragment or parsed.query or parsed.port not in (None, 443)
                or not (parsed.path.startswith("/webhook/") or parsed.path.startswith("/webhook-test/"))):
            raise ValueError("Configure an HTTPS n8n Cloud webhook URL")
        if not token.strip():
            raise ValueError("Webhook authentication token required")
        self.webhook_url, self.token, self.approvals, self.timeout = webhook_url, token, approvals, timeout

    def execute(self, context: BusinessContext, experiment_id: str, approval_id: str,
                experiment_version: int, execution_id: str, action_type: str,
                metadata: dict, idempotency_key: str, approved_at: datetime) -> DispatchOutcome:
        self.approvals.require_approved(context.workspace_id, experiment_id, approval_id)
        if action_type != "simulation_only" or set(metadata) != {"scenario"} or metadata.get("scenario") not in {
            "conversion_lift", "repeat_booking", "reminder_timing", "service_bundle",
        }:
            raise ValueError("Only approved simulation-only actions with safe scenario metadata are supported")
        payload = {
            "schema_version": 1,
            "event": "experiment.approved",
            "workspace_id": context.workspace_id,
            "experiment_id": experiment_id,
            "experiment_version": experiment_version,
            "approval_id": approval_id,
            "execution_id": execution_id,
            "approved_action_type": action_type,
            "mode": "simulation_only",
            "metadata": metadata,
            "idempotency_key": idempotency_key,
            "approved_at": (approved_at.replace(tzinfo=timezone.utc) if approved_at.tzinfo is None else approved_at).isoformat(),
        }
        request = urllib.request.Request(self.webhook_url, data=json.dumps(payload).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}",
                                     "Idempotency-Key": idempotency_key})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                status = response.status
            if 200 <= status < 300:
                return DispatchOutcome("acknowledged", status)
            return DispatchOutcome("failed", status, f"http_{status // 100}xx")
        except urllib.error.HTTPError as error:
            status = error.code
            return DispatchOutcome("failed", status, f"http_{status // 100}xx")
        except (urllib.error.URLError, TimeoutError, OSError):
            return DispatchOutcome("failed", None, "network_error")
