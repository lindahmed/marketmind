from decimal import Decimal
from datetime import date, datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or "." not in value.split("@")[-1] or any(c.isspace() for c in value):
            raise ValueError("Enter a valid email address")
        return value


class Register(Login):
    business_name: str = Field(min_length=2, max_length=120)
    industry: Literal["ecommerce", "appointments"]


class BusinessProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    industry: str
    currency: str
    monthly_budget: Decimal
    goals: list[str]
    constraints: list[str]
    description: str


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    monthly_budget: Decimal = Field(ge=0, le=1_000_000_000, max_digits=14, decimal_places=2)
    goals: list[str] = Field(max_length=20)
    constraints: list[str] = Field(max_length=20)
    description: str = Field(max_length=2000)

    @field_validator("goals", "constraints")
    @classmethod
    def validate_lines(cls, value: list[str]) -> list[str]:
        if any(len(line) > 300 for line in value):
            raise ValueError("Each goal or constraint must be at most 300 characters")
        return [line.strip() for line in value if line.strip()]


class DataSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    provider: Literal["google_sheets"] = "google_sheets"
    source_identifier: str = Field(min_length=1, max_length=200)


class BusinessEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_event_id: str = Field(min_length=1, max_length=160)
    event_type: Literal["order", "fulfillment", "cancellation", "refund", "payment",
                        "marketing_spend", "appointment_outcome", "expense"]
    occurred_at: datetime
    booked_at: datetime | None = None
    scheduled_at: datetime | None = None
    completed_at: datetime | None = None
    entity_id: str | None = Field(default=None, max_length=160)
    amount: Decimal | None = Field(default=None, ge=0, le=1_000_000_000, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    status: str | None = Field(default=None, max_length=40)
    quantity: int = Field(default=1, ge=1, le=1_000_000)
    cost_category: Literal["variable", "fixed"] | None = None
    campaign_id: str | None = Field(default=None, max_length=160)
    channel: str | None = Field(default=None, max_length=80)
    record_locator: str | None = Field(default=None, max_length=240)


class DataCoverageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: date
    data_kind: Literal["payments", "refunds", "marketing_spend", "variable_costs", "fixed_costs",
                       "orders", "fulfillment", "appointments"]
    complete: bool
    record_locator: str | None = Field(default=None, max_length=240)


class DataSourceBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=120)
    records: list[BusinessEventInput] = Field(default_factory=list, max_length=5000)
    deleted_source_event_ids: list[str] = Field(default_factory=list, max_length=5000)
    coverage: list[DataCoverageInput] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def require_batch_content(self):
        if not self.records and not self.deleted_source_event_ids and not self.coverage:
            raise ValueError("Provide records, deleted_source_event_ids, or coverage")
        if len(set(self.deleted_source_event_ids)) != len(self.deleted_source_event_ids):
            raise ValueError("deleted_source_event_ids cannot contain duplicates")
        return self


class ConflictResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accept_incoming", "retain_existing", "mark_duplicate"]
    note: str = Field(default="", max_length=500)


class InvestigationRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)

    @field_validator("question")
    @classmethod
    def trim_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Enter a question with at least 3 characters")
        return value


class KnowledgeSearch(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def trim_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a search query")
        return value


class SimulationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["conversion_lift", "repeat_booking", "reminder_timing", "service_bundle"]


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=120)
    action_type: Literal["simulation_only"]
    metadata: SimulationMetadata

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Experiment name must have at least three characters")
        return value


class RecommendationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    constraints_acknowledged: bool = False


class ExperimentDesignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_start: date
    baseline_end: date
    estimated_cost: Decimal = Field(ge=0, le=1_000_000_000, max_digits=14, decimal_places=2)
    minimum_change: Decimal = Field(gt=0, le=1_000_000_000, max_digits=18, decimal_places=4)
    duration_days: int = Field(default=14, ge=7, le=90)
    minimum_volume: int = Field(default=30, ge=1, le=1_000_000_000)

    @model_validator(mode="after")
    def validate_period(self):
        if not 6 <= (self.baseline_end - self.baseline_start).days <= 89:
            raise ValueError("Baseline period must contain between 7 and 90 calendar days")
        return self


class SimulationCallbackResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_origin: Literal["simulated"]
    period_start: date
    period_end: date
    observed_days: int = Field(strict=True, ge=0, le=366)
    missing_days: int = Field(strict=True, ge=0, le=366)
    financial_data_complete: bool = Field(strict=True)
    volume: int = Field(strict=True, ge=0, le=1_000_000_000)
    metrics: dict[str, Decimal] = Field(default_factory=dict, max_length=12)

    @field_validator("metrics")
    @classmethod
    def validate_simulated_metrics(cls, value):
        if (any(not re.fullmatch(r"[a-z0-9_]{1,60}", name) for name in value)
                or any(not amount.is_finite() or abs(amount) > Decimal("1000000000000") for amount in value.values())):
            raise ValueError("Simulation metrics must be finite bounded numbers")
        return value

    @model_validator(mode="after")
    def validate_window(self):
        if self.period_end < self.period_start:
            raise ValueError("Simulation reporting period is invalid")
        return self


class N8nSimulationCallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    callback_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    workspace_id: str = Field(min_length=36, max_length=36)
    experiment_id: str = Field(min_length=36, max_length=36)
    experiment_version: int = Field(strict=True, ge=1)
    approval_id: str = Field(min_length=36, max_length=36)
    execution_id: str = Field(min_length=36, max_length=36)
    event: Literal["experiment.simulation.completed", "experiment.simulation.failed"]
    mode: Literal["simulation_only"]
    result: SimulationCallbackResult | None = None
    failure_code: str | None = Field(default=None, min_length=1, max_length=60,
                                     pattern=r"^[a-zA-Z0-9_.-]+$")

    @model_validator(mode="after")
    def validate_event_payload(self):
        if self.event == "experiment.simulation.completed" and (self.result is None or self.failure_code is not None):
            raise ValueError("Completed simulation callbacks require a result and cannot include a failure code")
        if self.event == "experiment.simulation.failed" and (self.result is not None or self.failure_code is None):
            raise ValueError("Failed simulation callbacks require a safe failure code and no result")
        return self
