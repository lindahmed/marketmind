from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intelligence.contracts import BusinessContext
from app.industries import PACKS
from app.models import Membership, User, Workspace


def verified_business_context(db: Session, user: User, workspace_id: str) -> BusinessContext:
    """Construct an agent context only after checking persisted workspace membership."""
    workspace = db.scalar(select(Workspace).join(Membership).where(
        Membership.user_id == user.id, Workspace.id == workspace_id,
    ))
    if workspace is None:
        raise PermissionError("Workspace access denied")
    return BusinessContext(workspace_id=workspace.id, industry_pack=PACKS[workspace.industry],
                           goals=tuple(workspace.goals), constraints=tuple(workspace.constraints),
                           monthly_budget=float(workspace.monthly_budget))
