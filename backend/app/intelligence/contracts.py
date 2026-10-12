from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

from app.industries import IndustryPack

AgentName = Literal["data_intelligence", "investigation", "growth_strategy", "experimentation", "execution", "evaluation_memory"]


@dataclass(frozen=True)
class BusinessContext:
    workspace_id: str
    industry_pack: IndustryPack
    goals: tuple[str, ...]
    constraints: tuple[str, ...]
    monthly_budget: float


class AgentState(TypedDict):
    context: BusinessContext
    evidence: list[dict]
    recommendations: list[dict]
    experiment: dict | None
    # An ID alone is not approval. Execution must verify persisted approval ownership.
    approval_id: str | None


class Agent(Protocol):
    def __call__(self, state: AgentState) -> dict: ...


class Retriever(Protocol):
    def search(self, context: BusinessContext, embedding: list[float], limit: int = 5) -> list[dict]: ...


class ApprovalVerifier(Protocol):
    def require_approved(self, workspace_id: str, experiment_id: str, approval_id: str) -> None: ...


class ExperimentExecutor(Protocol):
    def execute(self, context: BusinessContext, experiment_id: str, approval_id: str) -> dict: ...
