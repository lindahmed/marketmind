from app.models import AuditEvent


def record_audit(db, context, actor_user_id: str, action: str, resource_type: str,
                 resource_id: str | None, details: dict) -> AuditEvent:
    """Append a workspace-bound event. Call within the business action transaction."""
    event = AuditEvent(workspace_id=context.workspace_id, actor_user_id=actor_user_id,
                       action=action, resource_type=resource_type,
                       resource_id=resource_id, details=details)
    db.add(event)
    return event
