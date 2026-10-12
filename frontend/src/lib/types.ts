export type Industry = {
  code: string; name: string; description: string; csv_columns: string[];
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
  series: { date: string; revenue: number; ad_spend: number }[];
  profit_note: string;
};
export type KnowledgeDocument = { id: string; name: string; mime_type: string; character_count: number; created_at: string };
export type InvestigationSummary = { id: string; question: string; status: string; created_at: string; evidence_count: number; model: string | null };
export type InvestigationReport = {
  id: string; question: string; status: string; created_at: string; model: string | null; confidence: number | null;
  estimated_cost_usd: number | null; cost_schedule?: string | null;
  result: { kpis: Record<string, number | null>; currency: string; findings: { kind: string; title: string; evidence: string; source_id?: string; confidence?: number | null; retrieval_methods?: string[] }[]; analysis_findings?: { title: string; evidence: string; source_ids: string[] }[]; assessment_source_ids?: string[]; confidence_note?: string; interpretation: string };
};
