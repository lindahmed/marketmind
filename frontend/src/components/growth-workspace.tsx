"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ExperimentDesign, GrowthRecommendation, InvestigationReport, WorkflowJob } from "@/lib/types";

const label = (value: string) => value.replaceAll("_", " ");

export function GrowthWorkspace({ workspaceId, report, strategyModel, onChanged }: {
  workspaceId: string; report: InvestigationReport; strategyModel: string | null; onChanged?: () => void;
}) {
  const [recommendations, setRecommendations] = useState<GrowthRecommendation[]>([]);
  const [designs, setDesigns] = useState<ExperimentDesign[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [acknowledged, setAcknowledged] = useState<Record<string, boolean>>({});
  const [strategyJob, setStrategyJob] = useState<WorkflowJob | null>(null);

  const refresh = useCallback(async () => {
    const [rows, savedDesigns] = await Promise.all([
      api<GrowthRecommendation[]>(`/growth/recommendations?investigation_id=${encodeURIComponent(report.id)}`, {}, workspaceId),
      api<ExperimentDesign[]>("/experiment-designs", {}, workspaceId),
    ]);
    setRecommendations(rows); setDesigns(savedDesigns);
  }, [workspaceId, report.id]);

  useEffect(() => {
    void refresh().catch(e => setError(e.message)).finally(() => setLoading(false));
  }, [refresh]);

  useEffect(() => {
    if (!strategyJob || !["queued", "running"].includes(strategyJob.status)) return;
    let timer = 0;
    const poll = async () => {
      try {
        const latest = await api<WorkflowJob>(`/workflow-jobs/${strategyJob.id}`, {}, workspaceId);
        setStrategyJob(latest);
        if (latest.status === "completed") {
          await refresh(); onChanged?.();
          setMessage(latest.result?.message ?? "Growth strategy completed and saved.");
          window.clearInterval(timer);
        } else if (["failed", "cancelled"].includes(latest.status)) {
          setError(latest.status === "cancelled" ? "Strategy generation cancelled." : `Strategy generation failed (${latest.error_code ?? "workflow_step_failed"}).`);
          window.clearInterval(timer);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not refresh strategy status");
        window.clearInterval(timer);
      }
    };
    timer = window.setInterval(() => void poll(), 1200);
    void poll();
    return () => window.clearInterval(timer);
  }, [strategyJob?.id, strategyJob?.status, workspaceId, refresh, onChanged]);

  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not complete the strategy action"); }
    finally { setBusy(false); }
  }

  async function generate() {
    await perform(async () => {
      const job = await api<WorkflowJob>(
        "/workflow-jobs", { method: "POST", body: JSON.stringify({ kind: "growth_strategy",
          payload: { investigation_id: report.id }, idempotency_key: crypto.randomUUID() }) }, workspaceId,
      );
      setStrategyJob(job); setMessage("Strategy generation queued. It will recheck this workspace’s evidence and goals before saving recommendations.");
    });
  }

  async function decide(row: GrowthRecommendation, decision: "approve" | "reject") {
    await perform(async () => {
      await api(`/growth/recommendations/${row.id}/${decision}`, {
        method: "POST", body: JSON.stringify({ version: row.version, constraints_acknowledged: acknowledged[row.id] ?? false }),
      }, workspaceId);
      await refresh(); onChanged?.();
      setMessage(decision === "approve" ? "Recommendation approved for experiment design. No experiment was executed." : "Recommendation rejected.");
    });
  }

  async function design(event: React.FormEvent<HTMLFormElement>, row: GrowthRecommendation) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await perform(async () => {
      await api<ExperimentDesign>(`/growth/recommendations/${row.id}/experiment-design`, {
        method: "POST", body: JSON.stringify({ baseline_start: form.get("baseline_start"), baseline_end: form.get("baseline_end"),
          estimated_cost: form.get("estimated_cost"), minimum_change: form.get("minimum_change"),
          duration_days: Number(form.get("duration_days")), minimum_volume: Number(form.get("minimum_volume")) }),
      }, workspaceId);
      await refresh(); onChanged?.(); setMessage("Measurable experiment draft saved. Execution still requires a separate experiment approval.");
    });
  }

  async function cancelGeneration() {
    if (!strategyJob) return;
    try {
      setStrategyJob(await api<WorkflowJob>(`/workflow-jobs/${strategyJob.id}/cancel`, { method: "POST" }, workspaceId));
    } catch (e) { setError(e instanceof Error ? e.message : "Could not cancel strategy generation"); }
  }

  return <section className="card grid gap-5">
    <div><p className="eyebrow text-[#087f69]">Growth strategy & experiment design</p>
      <h2 className="mt-2 text-xl font-semibold">Turn this investigation into a reviewable improvement</h2>
      <p className="muted mt-2 text-sm leading-6">{strategyModel ? `Generating recommendations sends this investigation and business context to OpenAI (${strategyModel}).` : "Evidence-backed industry rules propose conservative pilots. These are rule recommendations, not AI-generated diagnoses."} Hypotheses and costs are estimates. Owner approval authorizes design; it does not authorize execution.</p>
    </div>
    <div className="flex flex-wrap items-center gap-3"><button className="primary" disabled={busy || loading || Boolean(strategyJob && ["queued", "running"].includes(strategyJob.status))} onClick={() => void generate()}>{busy ? "Queueing…" : "Generate prioritized recommendations"}</button>{strategyJob && <span role="status" className="muted text-xs">Strategy job {strategyJob.status}{strategyJob.current_step ? ` · ${strategyJob.current_step.replaceAll("_", " ")}` : ""} · attempt {strategyJob.attempts}</span>}{strategyJob && ["queued", "running"].includes(strategyJob.status) && <button className="secondary text-xs" onClick={() => void cancelGeneration()}>Cancel</button>}</div>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-4 text-sm text-red-700">{error}</p>}
    {message && <p role="status" className="rounded-lg bg-[#eaf7f1] p-4 text-sm text-[#087f69]">{message}</p>}
    {loading ? <p role="status" className="muted text-sm">Loading saved strategy…</p> : !recommendations.length && <p className="muted text-sm">No recommendations saved for this investigation yet. Generation returns an empty result when the evidence does not support a permitted improvement.</p>}
    {recommendations.map(row => {
      const item = row.content;
      const saved = designs.find(plan => plan.recommendation_id === row.id);
      return <article key={row.id} className="grid gap-3 rounded-xl border border-[#dfe7e7] p-5">
        <p className="eyebrow text-[#087f69]">Priority {item.priority} · {row.source_type === "provider" ? `Model proposal: ${row.model}` : "Industry rule proposal"} · {row.status}</p>
        <h3 className="font-semibold">{item.title}</h3>
        <p className="muted text-sm">{item.rationale}</p><p className="text-sm">{item.action_details}</p>
        <p className="muted text-sm"><strong>Hypothesis:</strong> {item.hypothesis}</p>
        <p className="muted text-xs">{item.priority_reason} {item.goal_links.length ? `Goals: ${item.goal_links.join("; ")}.` : "No explicit goal match; review alignment."}</p>
        <p className="muted text-xs">Evidence IDs: {item.evidence_ids.join(", ")} · Version {row.version}</p>
        <p className="muted text-sm">Estimated cost: {report.result.currency} {item.estimated_cost}. {item.cost_basis}</p>
        {item.constraints_to_review.length > 0 && <div className="rounded-lg bg-amber-50 p-3 text-sm"><p>Review every constraint: {item.constraints_to_review.join("; ")}</p>{row.status === "proposed" && <label className="mt-3 flex items-start gap-2"><input type="checkbox" checked={acknowledged[row.id] ?? false} onChange={event => setAcknowledged(previous => ({ ...previous, [row.id]: event.target.checked }))} />I reviewed these constraints and accept this recommendation for design.</label>}</div>}
        {row.status === "proposed" && <div className="flex flex-wrap gap-3"><button className="primary" disabled={busy || (item.constraints_to_review.length > 0 && !acknowledged[row.id])} onClick={() => void decide(row, "approve")}>Approve recommendation for design</button><button className="secondary" disabled={busy} onClick={() => void decide(row, "reject")}>Reject recommendation</button></div>}
        {row.status === "approved" && !saved && <form className="mt-3 grid gap-4 border-t border-[#dfe7e7] pt-4 sm:grid-cols-2" onSubmit={event => void design(event, row)}>
          <p className="muted text-sm sm:col-span-2">Choose a complete 7–90 day baseline with detailed costs. Monetary/count metrics are compared per calendar day; rates use period ratios. The target is your minimum desired change, not a forecast.</p>
          <label className="label">Baseline start<input className="input" type="date" name="baseline_start" defaultValue={report.result.reporting_period?.start ?? ""} required /></label>
          <label className="label">Baseline end<input className="input" type="date" name="baseline_end" defaultValue={report.result.reporting_period?.end ?? ""} required /></label>
          <label className="label">Reviewed direct cash cost ({report.result.currency})<input className="input" type="number" name="estimated_cost" min="0" step="0.01" defaultValue={item.estimated_cost} required /></label>
          <label className="label">Minimum {item.direction} in {label(item.success_metric)}<input className="input" type="number" name="minimum_change" min="0.0001" step="0.0001" required /><span className="muted text-xs">Daily currency for revenue/profit; percentage points for rates; ratio units for unattributed revenue/ad-spend ratio.</span></label>
          <label className="label">Measurement duration (days)<input className="input" type="number" name="duration_days" min="7" max="90" defaultValue="14" required /></label>
          <label className="label">Minimum orders/bookings per period<input className="input" type="number" name="minimum_volume" min="1" defaultValue={report.result.industry === "appointments" ? "20" : "30"} required /></label>
          <div className="sm:col-span-2"><button className="primary" disabled={busy}>Create measurable experiment draft</button></div>
        </form>}
        {saved && <div className="grid gap-3 rounded-lg bg-[#eaf7f1] p-4 text-sm">
          <h4 className="font-semibold">Saved experiment draft · simulation only</h4>
          <p>{saved.design.hypothesis}</p><p>Baseline: {saved.design.baseline.start} through {saved.design.baseline.end} · {saved.design.baseline.volume} orders/bookings.</p>
          {saved.design.success_metrics.map(metric => <p key={metric.metric}>{label(metric.metric)}: baseline {saved.design.baseline.primary_value}; target {metric.operator === "gte" ? "at least" : "at most"} {metric.target} {label(metric.units)}.</p>)}
          <p>Daily profit guardrail: at least {saved.design.currency} {saved.design.baseline.profit_per_day}. Reviewed cost: {saved.design.currency} {saved.design.estimated_cost}.</p>
          <p>{saved.design.duration_days} fully observed days and at least {saved.design.evaluation_criteria.minimum_volume} {saved.design.evaluation_criteria.volume_metric} required.</p>
          <p>{saved.design.evaluation_criteria.measurement_window}</p>
          <p><strong>Success:</strong> {saved.design.evaluation_criteria.success}</p><p><strong>Failure:</strong> {saved.design.evaluation_criteria.failure}</p><p><strong>Inconclusive:</strong> {saved.design.evaluation_criteria.inconclusive}</p>
          <p className="muted text-xs">{saved.design.evaluation_criteria.interpretation}</p>
        </div>}
      </article>;
    })}
  </section>;
}
