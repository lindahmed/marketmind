import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    industry: Mapped[str] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    monthly_budget: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    goals: Mapped[list] = mapped_column(JSON, default=list)
    constraints: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(String(2000), default="")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    __table_args__ = (UniqueConstraint("workspace_id", "day"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    day: Mapped[date]
    values: Mapped[dict] = mapped_column(JSON)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    gross_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    refunds: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    ad_spend: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    variable_costs: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    fixed_costs: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fulfilled_orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancelled_orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delayed_orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bookings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_appointments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancelled_appointments: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("workspace_id", "provider", "source_identifier",
                                       name="uq_data_source_workspace_provider_identifier"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="google_sheets")
    source_identifier: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="active")
    sync_status: Mapped[str] = mapped_column(String(20), default="never")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DataImportRun(Base):
    __tablename__ = "data_import_runs"
    __table_args__ = (UniqueConstraint("source_id", "request_id", name="uq_data_import_source_request"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)
    request_id: Mapped[str] = mapped_column(String(120))
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="completed")
    received_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_count: Mapped[int] = mapped_column(Integer, default=0)
    deleted_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)


class BusinessEvent(Base):
    __tablename__ = "business_events"
    __table_args__ = (Index("ix_business_events_workspace_time", "workspace_id", "occurred_at"),
                      Index("ix_business_events_reconcile", "workspace_id", "event_type", "entity_id"),
                      Index("uq_business_events_current_key", "workspace_id", "current_key", unique=True,
                            postgresql_where=text("current_key IS NOT NULL AND is_current = true"),
                            sqlite_where=text("current_key IS NOT NULL AND is_current = 1")))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)
    import_run_id: Mapped[str] = mapped_column(ForeignKey("data_import_runs.id", ondelete="CASCADE"), index=True)
    source_event_id: Mapped[str] = mapped_column(String(160))
    event_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    status_value: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    cost_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    campaign_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    record_hash: Mapped[str] = mapped_column(String(64))
    reconciliation_status: Mapped[str] = mapped_column(String(20), index=True)
    reconciliation_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    matched_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Raw versions are immutable. Only the latest reconciled version contributes to reporting.
    is_current: Mapped[bool] = mapped_column(default=True, server_default="1", index=True)
    supersedes_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ReconciliationDecision(Base):
    __tablename__ = "reconciliation_decisions"
    __table_args__ = (Index("uq_reconciliation_decision_conflict", "conflict_event_id", unique=True),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    conflict_event_id: Mapped[str] = mapped_column(ForeignKey("business_events.id", ondelete="CASCADE"), index=True)
    selected_event_id: Mapped[str] = mapped_column(ForeignKey("business_events.id", ondelete="CASCADE"), index=True)
    decided_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decision: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(String(500), default="")
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DataCoverage(Base):
    __tablename__ = "data_coverage"
    __table_args__ = (Index("uq_data_coverage_current_source_day_kind", "workspace_id", "source_id", "day",
                            "data_kind", unique=True,
                            postgresql_where=text("is_current = true"),
                            sqlite_where=text("is_current = 1")),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)
    import_run_id: Mapped[str] = mapped_column(ForeignKey("data_import_runs.id", ondelete="CASCADE"), index=True)
    day: Mapped[date]
    data_kind: Mapped[str] = mapped_column(String(40))
    complete: Mapped[bool] = mapped_column(default=False)
    is_current: Mapped[bool] = mapped_column(default=True, server_default="1")
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("workspace_id", "sha256"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(100))
    character_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(String())
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536).with_variant(JSON(), "sqlite"), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class InvestigationRun(Base):
    __tablename__ = "investigation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True, index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(30), default="evidence_ready")
    result: Mapped[dict] = mapped_column(JSON)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(30), default="evidence-v1")
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    cost_schedule: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    action_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ExperimentApproval(Base):
    __tablename__ = "experiment_approvals"
    __table_args__ = (UniqueConstraint("experiment_id", "experiment_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    experiment_version: Mapped[int] = mapped_column(Integer)
    approved_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="approved")
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class N8nDispatch(Base):
    __tablename__ = "n8n_dispatches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    approval_id: Mapped[str] = mapped_column(ForeignKey("experiment_approvals.id", ondelete="RESTRICT"), index=True)
    execution_id: Mapped[str] = mapped_column(String(36), unique=True, default=new_id)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="dispatching", index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class GrowthStrategyRun(Base):
    __tablename__ = "growth_strategy_runs"
    __table_args__ = (UniqueConstraint("workspace_id", "investigation_id", "generation_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id", ondelete="CASCADE"), index=True)
    generation_key: Mapped[str] = mapped_column(String(64))
    context_snapshot: Mapped[dict] = mapped_column(JSON)
    source_type: Mapped[str] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(30))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    cost_schedule: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class GrowthRecommendation(Base):
    __tablename__ = "growth_recommendations"
    __table_args__ = (UniqueConstraint("strategy_run_id", "candidate_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    strategy_run_id: Mapped[str] = mapped_column(ForeignKey("growth_strategy_runs.id", ondelete="CASCADE"), index=True)
    candidate_key: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="proposed")
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RecommendationApproval(Base):
    __tablename__ = "recommendation_approvals"
    __table_args__ = (UniqueConstraint("recommendation_id", "recommendation_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    recommendation_id: Mapped[str] = mapped_column(ForeignKey("growth_recommendations.id", ondelete="CASCADE"), index=True)
    recommendation_version: Mapped[int] = mapped_column(Integer)
    approved_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    constraints_acknowledged: Mapped[bool]
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ExperimentDesign(Base):
    __tablename__ = "experiment_designs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), unique=True)
    recommendation_id: Mapped[str] = mapped_column(ForeignKey("growth_recommendations.id", ondelete="RESTRICT"), unique=True)
    recommendation_approval_id: Mapped[str] = mapped_column(ForeignKey("recommendation_approvals.id", ondelete="RESTRICT"))
    experiment_version: Mapped[int] = mapped_column(Integer, default=1)
    design: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class N8nCallbackReceipt(Base):
    __tablename__ = "n8n_callback_receipts"
    __table_args__ = (UniqueConstraint("dispatch_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    callback_id: Mapped[str] = mapped_column(String(120), unique=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    dispatch_id: Mapped[str] = mapped_column(ForeignKey("n8n_dispatches.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ExperimentEvaluation(Base):
    __tablename__ = "experiment_evaluations"
    __table_args__ = (UniqueConstraint("experiment_id"), UniqueConstraint("callback_receipt_id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    callback_receipt_id: Mapped[str] = mapped_column(ForeignKey("n8n_callback_receipts.id", ondelete="CASCADE"), index=True)
    outcome: Mapped[str] = mapped_column(String(40))
    report: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ExperimentLearning(Base):
    __tablename__ = "experiment_learnings"
    __table_args__ = (UniqueConstraint("experiment_id"), UniqueConstraint("evaluation_id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("experiment_evaluations.id", ondelete="CASCADE"), index=True)
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WorkflowJob(Base):
    __tablename__ = "workflow_jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "kind", "idempotency_key", name="uq_workflow_jobs_workspace_kind_key"),
        Index("ix_workflow_jobs_workspace_status_created", "workspace_id", "status", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    requested_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_step: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                                                   onupdate=lambda: datetime.now(timezone.utc))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowCheckpoint(Base):
    __tablename__ = "workflow_checkpoints"
    __table_args__ = (
        UniqueConstraint("workspace_id", "thread_id", "checkpoint_ns", "checkpoint_id",
                         name="uq_workflow_checkpoint_tenant_thread_id"),
        Index("ix_workflow_checkpoints_job", "workspace_id", "job_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("workflow_jobs.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str] = mapped_column(String(36))
    checkpoint_ns: Mapped[str] = mapped_column(String(200), default="")
    checkpoint_id: Mapped[str] = mapped_column(String(120))
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    checkpoint: Mapped[dict] = mapped_column(JSON)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WorkflowCheckpointWrite(Base):
    __tablename__ = "workflow_checkpoint_writes"
    __table_args__ = (
        UniqueConstraint("workspace_id", "thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "write_index",
                         name="uq_workflow_checkpoint_write_key"),
        Index("ix_workflow_checkpoint_writes_scope", "workspace_id", "thread_id", "checkpoint_ns", "checkpoint_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("workflow_jobs.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str] = mapped_column(String(36))
    checkpoint_ns: Mapped[str] = mapped_column(String(200), default="")
    checkpoint_id: Mapped[str] = mapped_column(String(120))
    task_id: Mapped[str] = mapped_column(String(120))
    task_path: Mapped[str] = mapped_column(String(500), default="")
    write_index: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(120))
    value: Mapped[dict] = mapped_column(JSON)
