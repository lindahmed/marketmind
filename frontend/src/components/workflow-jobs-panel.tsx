"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { WorkflowJob } from "@/lib/types";

const labels: Record<WorkflowJob["kind"], string> = {
  investigation: "Evidence investigation",
  growth_strategy: "Growth strategy",
  experiment_evaluation: "Experiment evaluation",
};

export function WorkflowJobsPanel({ workspaceId }: { workspaceId: string }) {
  const [jobs, setJobs] = useState<WorkflowJob[]>([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const rows = await api<WorkflowJob[]>("/workflow-jobs", {}, workspaceId);
    setJobs(rows.slice(0, 8)); setError("");
  }, [workspaceId]);

  useEffect(() => {
    void refresh().catch(e => setError(e instanceof Error ? e.message : "Could not load workflow status"));
    const timer = window.setInterval(() => void refresh().catch(() => undefined), 1800);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function cancel(job: WorkflowJob) {
    try { await api<WorkflowJob>(`/workflow-jobs/${job.id}/cancel`, { method: "POST" }, workspaceId); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not cancel workflow"); }
  }

  if (!jobs.length && !error) return null;
  return <section className="card mb-6 grid gap-3" aria-label="Background workflow status">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="eyebrow text-[#087f69]">Background work</p><h2 className="mt-1 font-semibold">Workflow status</h2></div><button className="secondary text-xs" onClick={() => void refresh()}>Refresh</button></div>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {jobs.map(job => <article key={job.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[#f4f7f7] p-3 text-sm">
      <div><p className="font-medium">{labels[job.kind]} · {job.status.replaceAll("_", " ")}</p><p className="muted mt-1 text-xs">{job.current_step ? `${job.current_step.replaceAll("_", " ")} · ` : ""}Attempt {job.attempts}{job.error_code ? ` · ${job.error_code}` : ""}</p></div>
      {["queued", "running"].includes(job.status) && <button className="secondary text-xs" onClick={() => void cancel(job)}>Cancel</button>}
    </article>)}
  </section>;
}
