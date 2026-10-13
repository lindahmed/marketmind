export type Industry = {
  code: string; name: string; description: string; csv_columns: string[]; detailed_csv_columns: string[];
  kpis: string[]; diagnostics: string[]; experiment_types: string[];
};
export type Session = { id: string; email: string; workspaces: { id: string; name: string; industry: string }[] };
export type Profile = {
  id: string; name: string; industry: string; currency: string; monthly_budget: string;
  goals: string[]; constraints: string[]; description: string;
};
export type Dashboard = {
  business_name: string; industry: Industry; currency: string; row_count: number;
  period_start: string | null; period_end: string | null;
  kpis: Record<string, number | null>;
  findings: { code: string; title: string; evidence: string; severity: string }[];
  series: { date: string; revenue: number; gross_revenue: number; refunds: number; ad_spend: number; variable_costs: number; fixed_costs: number }[];
  reporting_period: { start: string | null; end: string | null; observed_days: number; calendar_days: number; missing_days: number; complete: boolean };
  data_quality: { legacy_rows: number; detailed_rows: number; fixed_cost_unknown_rows: number; reconciled_event_rows?: number; event_type_coverage_gaps?: string[]; source_overlap_days?: number };
  source_metrics?: { accepted_events: number; observed_event_types: string[]; missing_event_types: string[]; recorded_campaign_payments: Record<string, number>; payments_without_campaign_id: number; campaign_interpretation: string; csv_overlap_dates: string[] };
  profit_note: string;
};
export type DataSourceView = { id: string; provider: string; source_identifier: string; name: string; status: string; sync_status: string; last_sync_at: string | null; created_at: string; ingestion_token?: string; token_notice?: string };
export type DataImportRun = { id: string; source_id: string; request_id: string; status: string; received_count: number; accepted_count: number; duplicate_count: number; conflict_count: number; missing_count: number; deleted_count: number; started_at: string; finished_at: string | null; error_code: string | null };
export type DataQuality = { source_count: number; sources: DataSourceView[]; imports: DataImportRun[]; conflicts: { id: string; source_id: string; source_event_id: string; event_type: string; entity_id: string | null; occurred_at: string; status: string; note: string | null; amount: number | null; currency: string | null; status_value: string | null; campaign_id: string | null; channel: string | null; matched_event_id: string | null; existing_record: { amount: number | null; currency: string | null; status_value: string | null; campaign_id: string | null } | null; provenance: Record<string, unknown> }[]; reconciliation: { accepted_events: number; duplicate_events: number; conflicting_events: number; records_missing_required_fields: number }; decisions: { id: string; conflict_event_id: string; selected_event_id: string; decision: string; note: string; provenance: Record<string, unknown>; created_at: string }[]; event_coverage: { observed_event_types: string[]; missing_event_types: string[] }; recorded_campaign_payments: Record<string, number>; payments_without_campaign_id: number; campaign_note: string };
export type KnowledgeDocument = { id: string; name: string; mime_type: string; character_count: number; created_at: string };
export type InvestigationSummary = { id: string; question: string; status: string; created_at: string; evidence_count: number; model: string | null };
export type InvestigationReport = {
  id: string; question: string; status: string; created_at: string; model: string | null; confidence: number | null;
  estimated_cost_usd: number | null; cost_schedule?: string | null;
  result: { kpis: Record<string, number | null>; currency: string; industry: string; reporting_period?: Dashboard["reporting_period"]; findings: { kind: string; title: string; evidence: string; source_id?: string; confidence?: number | null; retrieval_methods?: string[] }[]; analysis_findings?: { title: string; evidence: string; source_ids: string[] }[]; assessment_source_ids?: string[]; confidence_note?: string; interpretation: string };
};
export type GrowthRecommendation = {
  id: string; version: number; status: "proposed" | "approved" | "rejected"; investigation_id: string;
  source_type: "industry_rule" | "provider"; model: string | null; prompt_version: string;
  content: { title: string; rationale: string; action_type: string; action_details: string; hypothesis: string;
    success_metric: string; direction: string; evidence_ids: string[]; goal_links: string[];
    estimated_cost: string; cost_basis: string; priority: number; priority_reason: string; constraints_to_review: string[] };
};
export type ExperimentDesign = {
  id: string; experiment_id: string; recommendation_id: string; recommendation_approval_id: string;
  experiment_version: number;
  design: { hypothesis: string; action_details: string; currency: string; estimated_cost: string; cost_basis: string;
    duration_days: number; execution_mode: string; measurement_method: string;
    baseline: { start: string; end: string; days: number; primary_value: string; profit_per_day: string; volume: number };
    success_metrics: { metric: string; units: string; target: string; minimum_change: string; operator: string }[];
    evaluation_criteria: { measurement_window: string; minimum_volume: number; volume_metric: string; success: string; failure: string;
      inconclusive: string; interpretation: string } };
};
export type ExperimentHistory = {
  experiment_id: string; status: string;
  callback: { event: string; received_at: string; payload: { event: string; mode: string; result: {
    data_origin: string; period_start: string; period_end: string; observed_days: number; missing_days: number;
    financial_data_complete: boolean; volume: number; metrics: Record<string, string>;
  } | null; failure_code: string | null } } | null;
  evaluation: { id: string; classification: string; report: {
    conclusion: string; simulation_only: boolean; real_business_measurement: boolean;
    actual_profit_improvement_verified: boolean; data_quality: { acceptable: boolean; reasons: string[] };
    comparison: Record<string, string | boolean> | null; limitations: string[];
  } } | null;
  learning: { id: string; content: { hypothesis: string; conclusion: string; classification: string;
    evidence_ids: string[]; limitations: string[]; actual_profit_improvement_verified: boolean } } | null;
  evaluation_job: { id: string; status: string; current_step: string | null; error_code: string | null } | null;
  history: { action: string; created_at: string; details: Record<string, string | number | boolean | null> }[];
};
export type WorkflowJob = {
  id: string; kind: "investigation" | "growth_strategy" | "experiment_evaluation"; status: string;
  attempts: number; current_step: string | null; cancel_requested: boolean;
  result: { resource_id: string; report?: InvestigationReport; recommendations?: GrowthRecommendation[]; message?: string;
    strategy_run_id?: string; classification?: string; evaluation_id?: string; learning_id?: string } | null;
  error_code: string | null; created_at: string; updated_at: string; started_at: string | null;
  finished_at: string | null; duplicate?: boolean;
};
