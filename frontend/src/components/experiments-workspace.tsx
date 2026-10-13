"use client";

import { useCallback, useEffect, useState } from "react";
import { GrowthWorkspace } from "@/components/growth-workspace";
import { api } from "@/lib/api";
import type { ExperimentDesign, ExperimentHistory, InvestigationReport, InvestigationSummary } from "@/lib/types";

type ExperimentRow = {
  id: string; name: string; status: string; version: number; action_type: string; created_at: string;
  can_approve: boolean; approval_id: string | null; design: ExperimentDesign | null;
  execution: { execution_id: string; status: string; http_status: number | null; failure_code: string | null;
    acknowledged_at: string | null; completion_status: "not_reported" | "completed" | "failed" } | null;
  evaluation: { classification: string } | null;
  evaluation_job: { id: string; status: string; current_step: string | null; error_code: string | null } | null;
};

function ExperimentHistoryPanel({ history }: { history: ExperimentHistory }) {
  const result = history.callback?.payload.result;
  const evaluation = history.evaluation;
  const learning = history.learning;
  return <div className="grid gap-4 rounded-xl border border-[#c9e6dc] bg-[#f5fbf8] p-5">
    <h4 className="font-semibold">Experiment history</h4>
    {result && <p className="muted text-sm">Simulated window: {result.period_start} to {result.period_end} · {result.observed_days} reported days · {result.volume} reported volume.</p>}
    {evaluation ? <article className="grid gap-2 text-sm"><p><strong>Evaluation:</strong> {evaluation.classification}</p><p>{evaluation.report.conclusion}</p><p><strong>Simulation data quality:</strong> {evaluation.report.data_quality.acceptable ? "passed reported checks" : "inconclusive"}{evaluation.report.data_quality.reasons.length ? ` · ${evaluation.report.data_quality.reasons.join(", ")}` : ""}</p>{evaluation.report.comparison && <pre className="overflow-auto rounded-lg bg-white p-3 text-xs">{JSON.stringify(evaluation.report.comparison, null, 2)}</pre>}<p className="font-medium">Limitations</p><ul className="list-disc pl-5">{evaluation.report.limitations.map((reason, index) => <li key={index}>{reason}</li>)}</ul></article> : <p className="muted text-sm">No evaluation report is available yet.</p>}
    {learning && <article className="grid gap-2 border-t border-[#dfe7e7] pt-4 text-sm"><h5 className="font-semibold">Saved learning</h5><p><strong>Hypothesis:</strong> {learning.content.hypothesis}</p><p>{learning.content.conclusion}</p><p className="muted text-xs">Evidence IDs: {learning.content.evidence_ids.join(", ") || "none"}. Simulation learning is not an actual business measurement.</p></article>}
    {history.evaluation_job && <p role="status" className="muted text-xs">Evaluation job: {history.evaluation_job.status}{history.evaluation_job.current_step ? ` · ${history.evaluation_job.current_step.replaceAll("_", " ")}` : ""}{history.evaluation_job.error_code ? ` · ${history.evaluation_job.error_code}` : ""}</p>}
    <ol className="grid gap-2 border-t border-[#dfe7e7] pt-4">{history.history.map((event, index) => <li key={`${event.action}-${index}`} className="flex flex-wrap justify-between gap-2 text-xs"><span>{event.action.replaceAll("_", " ")}</span><time className="muted">{new Date(event.created_at).toLocaleString()}</time></li>)}</ol>
  </div>;
}

export function ExperimentsWorkspace({ workspaceId }: { workspaceId: string }) {
  const [runs, setRuns] = useState<InvestigationSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [report, setReport] = useState<InvestigationReport | null>(null);
  const [strategyModel, setStrategyModel] = useState<string | null>(null);
  const [experiments, setExperiments] = useState<ExperimentRow[]>([]);
  const [busyId, setBusyId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [history, setHistory] = useState<Record<string, ExperimentHistory>>({});
  const [historyBusy, setHistoryBusy] = useState("");

  const refreshExperiments = useCallback(async () => {
    setExperiments(await api<ExperimentRow[]>("/experiments", {}, workspaceId));
  }, [workspaceId]);

  useEffect(() => {
    void Promise.all([
      api<InvestigationSummary[]>("/investigations", {}, workspaceId),
      api<{ strategy_model: string | null }>("/knowledge/retrieval", {}, workspaceId),
      refreshExperiments(),
    ]).then(([savedRuns, retrieval]) => {
      setRuns(savedRuns); setStrategyModel(retrieval.strategy_model);
    }).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, [workspaceId, refreshExperiments]);

  const pendingEvaluationHistory = Object.entries(history).filter(([, item]) =>
    item.evaluation_job && ["queued", "running"].includes(item.evaluation_job.status),
  ).map(([id]) => id).join(",");

  useEffect(() => {
    if (!pendingEvaluationHistory) return;
    let timer = 0;
    const poll = async () => {
      const ids = pendingEvaluationHistory.split(",");
      try {
        const updates = await Promise.all(ids.map(async id => [id,
          await api<ExperimentHistory>(`/experiments/${id}/history`, {}, workspaceId)] as const));
        setHistory(current => ({ ...current, ...Object.fromEntries(updates) }));
        await refreshExperiments();
      } catch (e) { setError(e instanceof Error ? e.message : "Could not refresh evaluation progress"); }
    };
    timer = window.setInterval(() => void poll(), 1400);
    return () => window.clearInterval(timer);
  }, [pendingEvaluationHistory, workspaceId, refreshExperiments]);

  async function openInvestigation(id: string) {
    setSelected(id); setReport(null); setError("");
    try { setReport(await api<InvestigationReport>(`/investigations/${id}`, {}, workspaceId)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load investigation"); }
  }

  async function approve(experiment: ExperimentRow) {
    setBusyId(experiment.id); setError(""); setNotice("");
    try {
      const receipt = await api<{ execution_id: string; dispatch_status: string; completion_status: string; message: string }>(
        `/experiments/${experiment.id}/approve`, { method: "POST" }, workspaceId,
      );
      await refreshExperiments();
      setNotice(`${receipt.message} Execution ${receipt.execution_id} · ${receipt.dispatch_status}.`);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not approve simulation"); }
    finally { setBusyId(""); }
  }

  async function reject(experiment: ExperimentRow) {
    setBusyId(experiment.id); setError(""); setNotice("");
    try {
      await api(`/experiments/${experiment.id}/reject`, { method: "POST" }, workspaceId);
      await refreshExperiments(); setNotice("Experiment draft rejected. No webhook was sent.");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not reject experiment draft"); }
    finally { setBusyId(""); }
  }

  async function toggleHistory(experimentId: string) {
    if (history[experimentId]) { setHistory(current => { const next = { ...current }; delete next[experimentId]; return next; }); return; }
    setHistoryBusy(experimentId);
    try {
      const data = await api<ExperimentHistory>(`/experiments/${experimentId}/history`, {}, workspaceId);
      setHistory(current => ({ ...current, [experimentId]: data }));
    } catch (e) { setError(e instanceof Error ? e.message : "Could not load experiment history"); }
    finally { setHistoryBusy(""); }
  }

  return <div className="grid gap-6">
    <section className="card grid gap-4">
      <div><p className="eyebrow text-[#087f69]">Evidence to owner-approved simulation</p>
        <h2 className="mt-2 text-xl font-semibold">Review recommendations and design a safe experiment</h2>
        <p className="muted mt-2 max-w-3xl text-sm leading-6">Choose a saved investigation to generate or review its evidence-backed recommendations. Owners can approve or reject each recommendation and create a measured simulation draft. A separate owner approval dispatches the simulation to your configured n8n Cloud webhook. No advertising spend is authorized.</p>
      </div>
      <label className="label">Saved investigation<select className="input mt-1" value={selected} onChange={event => { if (event.target.value) void openInvestigation(event.target.value); else { setSelected(""); setReport(null); } }}>
        <option value="">Choose an investigation</option>{runs.map(run => <option key={run.id} value={run.id}>{run.question} · {new Date(run.created_at).toLocaleDateString()}</option>)}
      </select></label>
      {!loading && !runs.length && <p className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900">Create an evidence review in Private knowledge first, then return here to develop experiments.</p>}
    </section>

    {error && <p role="alert" className="rounded-lg bg-red-50 p-4 text-sm text-red-700">{error}</p>}
    {notice && <p role="status" className="rounded-lg bg-[#eaf7f1] p-4 text-sm text-[#087f69]">{notice}</p>}
    {report && <GrowthWorkspace key={`${workspaceId}:${report.id}`} workspaceId={workspaceId} report={report}
      strategyModel={strategyModel} onChanged={() => void refreshExperiments().catch(e => setError(e.message))} />}

    <section className="card grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="eyebrow text-[#087f69]">Simulation queue</p><h2 className="mt-2 text-xl font-semibold">Experiments and execution status</h2><p className="muted mt-1 text-sm">A webhook acknowledgement confirms receipt only. A callback reports simulation status, never real business performance.</p></div>
        <button className="secondary" onClick={() => void refreshExperiments().catch(e => setError(e.message))}>Refresh status</button></div>
      {loading ? <p role="status" className="muted text-sm">Loading experiments…</p> : !experiments.length ? <p className="muted rounded-lg bg-[#f4f7f7] p-4 text-sm">No experiments yet. Review an investigation above to create a draft.</p> : experiments.map(item => <article key={item.id} className="grid gap-3 rounded-xl border border-[#dfe7e7] p-5">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow text-[#087f69]">{item.action_type.replaceAll("_", " ")} · {item.status} · v{item.version}</p><h3 className="mt-2 font-semibold">{item.name}</h3></div>
          {item.design && item.status === "draft" && item.can_approve && <div className="flex flex-wrap gap-2"><button className="primary" disabled={busyId === item.id} onClick={() => void approve(item)}>{busyId === item.id ? "Dispatching simulation…" : "Approve and dispatch simulation"}</button><button className="secondary" disabled={busyId === item.id} onClick={() => void reject(item)}>Reject draft</button></div>}
        </div>
        {item.design && <div className="rounded-lg bg-[#f4f7f7] p-4 text-sm"><p className="font-medium">{item.design.design.hypothesis}</p><p className="muted mt-2">Baseline {item.design.design.baseline.start} to {item.design.design.baseline.end} · estimated cost {item.design.design.currency} {item.design.design.estimated_cost} · simulation only</p><p className="muted mt-1 text-xs">{item.design.design.evaluation_criteria.success}</p></div>}
        {item.execution ? <div className="grid gap-1 rounded-lg border border-[#c9e6dc] bg-[#f5fbf8] p-4 text-sm"><p><strong>Dispatch:</strong> {item.execution.status}{item.execution.http_status ? ` · HTTP ${item.execution.http_status}` : ""}</p><p><strong>Execution ID:</strong> <code>{item.execution.execution_id}</code></p>{item.execution.failure_code && <p><strong>Failure:</strong> {item.execution.failure_code}</p>}<p><strong>Experiment completion:</strong> {item.execution.completion_status}</p>{item.evaluation && <p><strong>Simulation evaluation:</strong> {item.evaluation.classification}</p>}{item.evaluation_job && <p role="status"><strong>Evaluation job:</strong> {item.evaluation_job.status}{item.evaluation_job.error_code ? ` · ${item.evaluation_job.error_code}` : ""}</p>}</div> : <p className="muted text-sm">{item.design ? "Draft is waiting for owner approval." : "No measured design is attached to this experiment."}</p>}
        <button className="secondary justify-self-start text-xs" disabled={historyBusy === item.id} onClick={() => void toggleHistory(item.id)}>{historyBusy === item.id ? "Loading history…" : history[item.id] ? "Hide history and evaluation" : "View history and evaluation"}</button>
        {history[item.id] && <ExperimentHistoryPanel history={history[item.id]} />}
        {!item.can_approve && item.design && item.status === "draft" && <p className="muted text-xs">Only the workspace owner who created this experiment can approve its simulation dispatch.</p>}
      </article>)}
    </section>
  </div>;
}
