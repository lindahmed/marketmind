"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { GrowthWorkspace } from "@/components/growth-workspace";
import type { InvestigationReport, InvestigationSummary, KnowledgeDocument, WorkflowJob } from "@/lib/types";

export function EvidenceWorkspace({ workspaceId }: { workspaceId: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [retrieval, setRetrieval] = useState<{ external_processing: boolean; retrieval_mode: string; embedding_model: string | null; investigation_model: string | null; strategy_model: string | null } | null>(null);
  const [runs, setRuns] = useState<InvestigationSummary[]>([]);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<InvestigationReport["result"]["findings"]>([]);
  const [report, setReport] = useState<InvestigationReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeJob, setActiveJob] = useState<WorkflowJob | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    const [nextDocuments, nextRuns, configuration, jobs] = await Promise.all([
      api<KnowledgeDocument[]>("/knowledge/documents", {}, workspaceId),
      api<InvestigationSummary[]>("/investigations", {}, workspaceId),
      api<{ external_processing: boolean; retrieval_mode: string; embedding_model: string | null; investigation_model: string | null; strategy_model: string | null }>("/knowledge/retrieval", {}, workspaceId),
      api<WorkflowJob[]>("/workflow-jobs", {}, workspaceId),
    ]);
    setDocuments(nextDocuments); setRuns(nextRuns); setRetrieval(configuration);
    setActiveJob(current => current ?? jobs.find(job => job.kind === "investigation" && ["queued", "running"].includes(job.status)) ?? null);
  }, [workspaceId]);
  useEffect(() => { void refresh().catch(e => setError(e.message)); }, [refresh]);

  useEffect(() => {
    if (!activeJob || !["queued", "running"].includes(activeJob.status)) return;
    let timer = 0;
    const poll = async () => {
      try {
        const latest = await api<WorkflowJob>(`/workflow-jobs/${activeJob.id}`, {}, workspaceId);
        setActiveJob(latest);
        if (latest.status === "completed") {
          if (latest.result?.report) setReport(latest.result.report);
          setMessage("Investigation completed and saved to this workspace.");
          await refresh();
          window.clearInterval(timer);
        } else if (["failed", "cancelled"].includes(latest.status)) {
          setError(latest.status === "cancelled" ? "Investigation cancelled." : `Investigation failed (${latest.error_code ?? "workflow_step_failed"}).`);
          window.clearInterval(timer);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not refresh investigation status");
        window.clearInterval(timer);
      }
    };
    timer = window.setInterval(() => void poll(), 1200);
    void poll();
    return () => window.clearInterval(timer);
  }, [activeJob?.id, activeJob?.status, workspaceId, refresh]);

  async function upload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setMessage("");
    const file = input.current?.files?.[0];
    if (!file) { setError("Choose a text or Markdown file."); return; }
    if (file.size > 200 * 1024) { setError("Document limit is 200 KB."); return; }
    setBusy(true);
    const data = new FormData(); data.append("file", file);
    try {
      const added = await api<KnowledgeDocument>("/knowledge/documents", { method: "POST", body: data }, workspaceId);
      await refresh(); setMessage(`${added.name} is available as private workspace evidence.`);
      if (input.current) input.current.value = "";
    } catch (e) { setError(e instanceof Error ? e.message : "Upload failed"); }
    finally { setBusy(false); }
  }

  async function search(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setBusy(true);
    try {
      const found = await api<{ results: { chunk_id: string; document_id: string; source: string; excerpt: string; score: number; retrieval_methods: string[] }[] }>(
        "/knowledge/search", { method: "POST", body: JSON.stringify({ query, limit: 8 }) }, workspaceId,
      );
      setSearchResults(found.results.map(row => ({ kind: "private_document", title: row.source,
        evidence: row.excerpt, source_id: row.chunk_id, retrieval_methods: row.retrieval_methods })));
    } catch (e) { setError(e instanceof Error ? e.message : "Search failed"); }
    finally { setBusy(false); }
  }

  async function investigate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setMessage(""); setBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      const job = await api<WorkflowJob>("/workflow-jobs", {
        method: "POST", body: JSON.stringify({ kind: "investigation", payload: { question: form.get("question") },
          idempotency_key: crypto.randomUUID() }),
      }, workspaceId);
      setActiveJob(job); setMessage("Investigation queued. You can keep working while the evidence review runs.");
    } catch (e) { setError(e instanceof Error ? e.message : "Investigation failed"); }
    finally { setBusy(false); }
  }

  async function openRun(id: string) {
    setError(""); setBusy(true);
    try { setReport(await api<InvestigationReport>(`/investigations/${id}`, {}, workspaceId)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load investigation"); }
    finally { setBusy(false); }
  }

  async function removeDocument(document: KnowledgeDocument) {
    if (!window.confirm(`Remove “${document.name}” and its searchable chunks from this workspace?`)) return;
    setError(""); setMessage("");
    try { await api(`/knowledge/documents/${document.id}`, { method: "DELETE" }, workspaceId); await refresh(); setMessage("Document removed from private workspace knowledge."); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not remove document"); }
  }

  async function cancelInvestigation() {
    if (!activeJob) return;
    try {
      setActiveJob(await api<WorkflowJob>(`/workflow-jobs/${activeJob.id}/cancel`, { method: "POST" }, workspaceId));
    } catch (e) { setError(e instanceof Error ? e.message : "Could not cancel investigation"); }
  }

  return <div className="grid max-w-5xl gap-6">
    {error && <p role="alert" className="rounded-lg bg-red-50 p-4 text-sm text-red-700">{error}</p>}
    {message && <p role="status" className="rounded-lg bg-[#eaf7f1] p-4 text-sm text-[#087f69]">{message}</p>}
    <section className="card">
      <p className="eyebrow text-[#087f69]">Private business knowledge</p><h2 className="mt-2 text-xl font-semibold">Documents for your workspace</h2>
      <p className="muted mt-2 max-w-2xl text-sm leading-6">Upload brand guidelines, customer research, and campaign notes. {retrieval ? retrieval.external_processing ? `OpenAI processes data for enabled features${retrieval.embedding_model ? `, including new chunks with ${retrieval.embedding_model} embeddings` : ""}${retrieval.investigation_model ? ` and investigation analysis with ${retrieval.investigation_model}` : ""}. Data and results are stored privately in your workspace.` : "Documents stay in your workspace; text search and evidence review do not call an external AI service." : "Checking document processing configuration…"}</p>
      <form onSubmit={upload} className="mt-6 grid gap-4 border-t border-[#dfe7e7] pt-6">
        <label className="label">Add a text document<input ref={input} type="file" accept=".txt,.md,text/plain,text/markdown" className="input" required /></label>
        <p className="muted text-xs">UTF-8 text or Markdown · max 200 KB · up to 100 overlapping chunks · duplicate content is rejected.</p>
        <div><button className="primary" disabled={busy || !retrieval}>{busy ? "Working…" : "Add private document"}</button></div>
      </form>
      <div className="mt-6 grid gap-2">{documents.length ? documents.map(document => <article key={document.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[#f4f7f7] p-4"><div><h3 className="text-sm font-semibold">{document.name}</h3><p className="muted mt-1 text-xs">{document.character_count.toLocaleString()} characters · {new Date(document.created_at).toLocaleDateString()}</p></div><button onClick={() => void removeDocument(document)} className="secondary text-xs">Remove</button></article>) : <p className="muted rounded-lg bg-[#f4f7f7] p-4 text-sm">No private documents yet.</p>}</div>
    </section>
    <section className="card">
      <h2 className="text-xl font-semibold">Search workspace evidence</h2><p className="muted mt-2 text-sm">{retrieval?.retrieval_mode === "hybrid" ? "Keyword and semantic matches are combined. Your query is sent to OpenAI when compatible workspace vectors exist." : "Ranked text matches from your uploaded documents."} Similarity does not establish a cause.</p>
      <form onSubmit={search} className="mt-5 flex flex-wrap gap-3"><label className="sr-only" htmlFor="evidence-query">Search documents</label><input id="evidence-query" className="input min-w-52 flex-1" value={query} onChange={e => setQuery(e.target.value)} maxLength={500} placeholder="e.g. return reasons, repeat customers" required /><button className="primary" disabled={busy || !query.trim() || !retrieval}>Search evidence</button></form>
      <div className="mt-5 grid gap-3">{searchResults.length ? searchResults.map((row, index) => <article key={`${row.source_id}-${index}`} className="rounded-xl border border-[#dfe7e7] p-4"><span className="eyebrow text-[#087f69]">{row.title}</span><p className="muted mt-1 text-xs">{row.retrieval_methods?.map(method => method === "vector" ? "Semantic match" : "Keyword match").join(" · ")}</p><p className="muted mt-2 text-sm leading-6">{row.evidence}</p></article>) : null}</div>
    </section>
    <section className="card grid gap-6 lg:grid-cols-[1fr_1fr]">
      <div><h2 className="text-xl font-semibold">Review evidence for a question</h2><p className="muted mt-2 text-sm leading-6">Combine your imported business metrics and matching workspace documents. {retrieval?.investigation_model ? `Analysis uses ${retrieval.investigation_model}; cited claims are checked against evidence from this workspace.` : "Without a configured model, this saves evidence only and does not infer causes."}</p>
        <form onSubmit={investigate} className="mt-5 grid gap-4"><label className="label">What would you like to understand?<textarea name="question" className="input" rows={4} minLength={3} maxLength={1000} placeholder="Why has profit fallen this month?" required /></label><div><button className="primary" disabled={busy || Boolean(activeJob && ["queued", "running"].includes(activeJob.status))}>{busy ? "Queueing…" : "Collect evidence +"}</button></div></form>
        {activeJob && <div role="status" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[#f4f7f7] p-4 text-sm"><span>Investigation: {activeJob.status}{activeJob.current_step ? ` · ${activeJob.current_step.replaceAll("_", " ")}` : ""} · attempt {activeJob.attempts}</span>{["queued", "running"].includes(activeJob.status) && <button className="secondary text-xs" onClick={() => void cancelInvestigation()}>Cancel</button>}</div>}
        <h3 className="mt-8 text-sm font-semibold">Saved evidence reviews</h3><div className="mt-3 grid max-h-72 gap-2 overflow-auto">{runs.length ? runs.map(run => <button key={run.id} className="secondary text-left" onClick={() => void openRun(run.id)}><span className="block truncate text-sm font-semibold">{run.question}</span><span className="muted mt-1 block text-xs">{run.evidence_count} evidence items · {new Date(run.created_at).toLocaleDateString()}</span></button>) : <p className="muted text-sm">No saved reviews yet.</p>}</div>
      </div>
      <div>{report ? <article className="rounded-xl border border-[#c9e6dc] bg-[#f5fbf8] p-5"><span className="eyebrow text-[#087f69]">{report.status === "analyzed" ? `AI investigation · ${report.model}` : "Evidence review"}</span><h3 className="mt-3 font-semibold">{report.question}</h3><p className="muted mt-2 text-sm">{report.result.interpretation}</p>{report.status === "analyzed" && <p className="muted mt-1 text-xs">Assessment evidence IDs: {report.result.assessment_source_ids?.join(", ") || "No supporting evidence found"}</p>}{report.result.analysis_findings?.length ? <div className="mt-4 grid gap-3">{report.result.analysis_findings.map((finding, index) => <div key={`${finding.title}-${index}`} className="rounded-lg border border-[#c9e6dc] bg-white p-4"><h4 className="text-sm font-semibold">{finding.title}</h4><p className="muted mt-2 text-xs leading-5">{finding.evidence}</p><p className="muted mt-2 text-xs">Evidence IDs: {finding.source_ids.join(", ")}</p></div>)}<p className="muted text-xs">Confidence {Math.round((report.confidence ?? 0) * 100)}% · {report.result.confidence_note}</p>{report.estimated_cost_usd !== null && <p className="muted text-xs">Estimated model cost: ${report.estimated_cost_usd.toFixed(8)} · rate schedule {report.cost_schedule}</p>}</div> : null}<h4 className="mt-5 text-sm font-semibold">Collected evidence</h4><div className="mt-3 grid gap-3">{report.result.findings.length ? report.result.findings.map((finding, index) => <div key={`${finding.source_id ?? finding.title}-${index}`} className="rounded-lg border border-[#dfe7e7] bg-white p-4"><span className="eyebrow text-[#647780]">{finding.kind.replace("_", " ")}</span><h4 className="mt-2 text-sm font-semibold">{finding.title}</h4><p className="muted mt-2 text-xs leading-5">{finding.evidence}</p><p className="muted mt-1 text-xs">Evidence ID: {finding.source_id ?? finding.title}</p></div>) : <p className="muted rounded-lg bg-white p-4 text-sm">No matching documents or diagnostic rules yet. Import daily metrics and add relevant notes.</p>}</div></article> : <div className="flex min-h-64 items-center justify-center rounded-xl bg-[#f4f7f7] p-6 text-center"><p className="muted max-w-sm text-sm leading-6">Saved reviews show the specific evidence they found. Keyword matches and diagnostic flags are not causal explanations.</p></div>}</div>
    </section>
    {report && retrieval && <GrowthWorkspace key={`${workspaceId}:${report.id}`} workspaceId={workspaceId} report={report} strategyModel={retrieval.strategy_model} />}
  </div>;
}
