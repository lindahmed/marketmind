"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Dashboard, DataQuality, DataSourceView } from "@/lib/types";

export function DataSourcesWorkspace({ workspaceId }: { workspaceId: string }) {
  const [data, setData] = useState<DataQuality | null>(null);
  const [csvOverlapDates, setCsvOverlapDates] = useState<string[]>([]);
  const [name, setName] = useState("Google Sheets");
  const [identifier, setIdentifier] = useState("");
  const [newSource, setNewSource] = useState<DataSourceView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    const [quality, dashboard] = await Promise.all([
      api<DataQuality>("/data-sources/quality", {}, workspaceId), api<Dashboard>("/dashboard", {}, workspaceId),
    ]);
    setData(quality); setCsvOverlapDates(dashboard.source_metrics?.csv_overlap_dates ?? []);
  }, [workspaceId]);
  useEffect(() => { void refresh().catch(reason => setError(reason instanceof Error ? reason.message : "Could not load data quality")); }, [refresh]);

  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setBusy(true);
    try {
      const created = await api<DataSourceView>("/data-sources", { method: "POST", body: JSON.stringify({ name, provider: "google_sheets", source_identifier: identifier.trim() }) }, workspaceId);
      setNewSource(created); setIdentifier(""); await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not create data source"); }
    finally { setBusy(false); }
  }

  async function revoke(sourceId: string) {
    setError("");
    try { await api(`/data-sources/${sourceId}/revoke`, { method: "POST" }, workspaceId); await refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not revoke source token"); }
  }

  async function rotate(source: DataSourceView) {
    setError("");
    try {
      const replacement = await api<DataSourceView>(`/data-sources/${source.id}/rotate-token`, { method: "POST" }, workspaceId);
      setNewSource(replacement); await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not rotate source token"); }
  }

  async function resolveConflict(eventId: string, decision: "accept_incoming" | "retain_existing" | "mark_duplicate") {
    setError(""); setBusy(true);
    try {
      await api(`/data-sources/conflicts/${eventId}/resolve`,
        { method: "POST", body: JSON.stringify({ decision, note: "Reviewed in Data Sources & Data Quality" }) }, workspaceId);
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not resolve conflict"); }
    finally { setBusy(false); }
  }

  return <div className="grid gap-6">
    <section className="card"><p className="eyebrow text-[#087f69]">Trusted data integration</p><h2 className="mt-2 text-lg font-semibold">Connect Google Sheets through your n8n Cloud workflow</h2><p className="muted mt-2 text-sm">Create a source here, then add its one-time bearer token to an n8n credential. The token is stored as a digest and cannot be viewed again.</p>
      <form className="mt-5 grid gap-4 sm:grid-cols-2" onSubmit={create}><label className="label">Source name<input className="input mt-1" value={name} onChange={event => setName(event.target.value)} minLength={2} maxLength={120} required /></label><label className="label">Google Sheet ID<input className="input mt-1" value={identifier} onChange={event => setIdentifier(event.target.value)} maxLength={200} required /></label><div className="sm:col-span-2"><button className="primary" disabled={busy}>{busy ? "Creating…" : "Create source and token"}</button></div></form>
      {newSource?.ingestion_token && <div role="alert" className="mt-5 rounded-lg border border-amber-300 bg-amber-50 p-4"><p className="text-sm font-semibold text-amber-950">Copy this token into n8n now. It is shown only once.</p><code className="mt-3 block break-all rounded bg-white p-3 text-xs">{newSource.ingestion_token}</code><p className="muted mt-2 text-xs">Use `Authorization: Bearer {newSource.ingestion_token}` as the HTTP Request authentication header. Don’t put this token in a sheet cell or workflow output.</p><button className="secondary mt-3" onClick={() => setNewSource(null)}>I saved the credential</button></div>}
      {error && <p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}
    </section>
    <section className="card"><h2 className="font-semibold">Connected sources</h2><div className="mt-4 grid gap-3">{data?.sources.length ? data.sources.map(source => <article key={source.id} className="rounded-lg border border-[#dfe7e7] p-4"><div className="flex flex-wrap justify-between gap-2"><strong>{source.name}</strong><span className="text-xs">{source.status} · {source.sync_status}</span></div><p className="muted mt-1 break-all text-xs">Google Sheets · {source.source_identifier}</p><div className="mt-2 flex flex-wrap items-center justify-between gap-3"><p className="muted text-xs">Last sync: {source.last_sync_at ? new Date(source.last_sync_at).toLocaleString() : "Never"}</p><div className="flex gap-3"><button className="text-xs text-[#087f69] underline" onClick={() => void rotate(source)}>Rotate token</button>{source.status === "active" && <button className="text-xs text-red-700 underline" onClick={() => void revoke(source.id)}>Revoke ingestion token</button>}</div></div></article>) : <p className="muted text-sm">No sources connected yet.</p>}</div></section>
    <section className="card"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold">Reconciliation overview</h2><p className="muted mt-1 text-xs">Only accepted, reconciled events contribute to event-based financial summaries. Duplicates and conflicts are retained for review.</p></div><button className="secondary" onClick={() => void refresh()}>Refresh</button></div>
      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[["Accepted", data?.reconciliation.accepted_events], ["Duplicates", data?.reconciliation.duplicate_events], ["Conflicts", data?.reconciliation.conflicting_events], ["Missing required fields", data?.reconciliation.records_missing_required_fields]].map(([label, value]) => <div key={label} className="rounded-lg bg-[#f4f7f7] p-4"><p className="muted text-xs">{label}</p><p className="mt-2 text-2xl font-semibold">{value ?? "—"}</p></div>)}</div>
      {csvOverlapDates.length > 0 && <p role="status" className="mt-4 rounded-lg bg-amber-50 p-3 text-xs text-amber-950">CSV totals are retained for overlapping event dates pending comparison: {csvOverlapDates.join(", ")}</p>}
      {data && <><p className="muted mt-5 text-xs">Event types not yet observed: {data.event_coverage.missing_event_types.length ? data.event_coverage.missing_event_types.join(", ") : "none"}</p><div className="mt-4 rounded-lg bg-[#f4f7f7] p-4"><h3 className="text-sm font-semibold">Recorded payments by campaign ID</h3>{Object.keys(data.recorded_campaign_payments).length ? <ul className="mt-2 grid gap-1 text-sm">{Object.entries(data.recorded_campaign_payments).map(([campaign, total]) => <li key={campaign}>{campaign}: {total.toFixed(2)}</li>)}</ul> : <p className="muted mt-2 text-xs">No captured payments have a campaign ID.</p>}<p className="muted mt-2 text-xs">Unmatched captured payments: {data.payments_without_campaign_id.toFixed(2)} · {data.campaign_note}</p></div></>}
    </section>
    <section className="card"><h2 className="font-semibold">Recent syncs</h2><div className="mt-4 grid gap-2">{data?.imports.length ? data.imports.map(run => <article key={run.id} className="grid gap-1 rounded-lg border border-[#dfe7e7] p-3 text-sm sm:grid-cols-[1fr_auto]"><div><strong>{run.status}</strong><p className="muted mt-1 text-xs">{run.request_id} · {new Date(run.started_at).toLocaleString()}</p></div><p className="text-xs">{run.received_count} received · {run.accepted_count} accepted · {run.duplicate_count} duplicates · {run.conflict_count} conflicts · {run.missing_count} incomplete · {run.deleted_count} deleted</p></article>) : <p className="muted text-sm">No imports received yet.</p>}</div></section>
    <section className="card"><h2 className="font-semibold">Records requiring review</h2><div className="mt-4 grid gap-3">{data?.conflicts.length ? data.conflicts.map(row => <article key={row.id} className="rounded-lg border border-amber-200 bg-amber-50 p-4"><div className="flex justify-between gap-2"><strong className="capitalize">{row.status.replaceAll("_", " ")}</strong><span className="text-xs">{row.event_type}</span></div><p className="mt-1 text-sm">Record {row.source_event_id}{row.entity_id ? ` · business ID ${row.entity_id}` : ""}</p><p className="muted mt-1 text-xs">{row.note} · {new Date(row.occurred_at).toLocaleString()}</p>{row.amount !== null && <p className="mt-2 text-xs">Incoming amount: {row.amount.toFixed(2)} {row.currency ?? ""}{row.status_value ? ` · ${row.status_value}` : ""}{row.campaign_id ? ` · campaign ${row.campaign_id}` : ""}</p>}{row.existing_record && <p className="mt-1 text-xs">Existing record: {row.existing_record.amount?.toFixed(2) ?? "no amount"} {row.existing_record.currency ?? ""}{row.existing_record.status_value ? ` · ${row.existing_record.status_value}` : ""}</p>}{row.matched_event_id && <p className="muted mt-1 break-all text-xs">Related record: {row.matched_event_id}</p>}<p className="muted mt-2 text-xs">Source row: {String(row.provenance.record_locator ?? "not provided")}</p>{row.status === "conflict" && row.matched_event_id && <div className="mt-3 flex flex-wrap gap-2"><button className="secondary" disabled={busy} onClick={() => void resolveConflict(row.id, "accept_incoming")}>Accept incoming</button><button className="secondary" disabled={busy} onClick={() => void resolveConflict(row.id, "retain_existing")}>Keep existing</button><button className="secondary" disabled={busy} onClick={() => void resolveConflict(row.id, "mark_duplicate")}>Mark duplicate</button></div>}</article>) : <p className="muted text-sm">No conflicts or incomplete records need review.</p>}</div></section>
    {data?.decisions.length ? <section className="card"><h2 className="font-semibold">Conflict decision history</h2><div className="mt-3 grid gap-2">{data.decisions.map(item => <article key={item.id} className="rounded-lg border border-[#dfe7e7] p-3 text-sm"><strong className="capitalize">{item.decision.replaceAll("_", " ")}</strong><p className="muted mt-1 text-xs">{item.note || "No note provided"} · {new Date(item.created_at).toLocaleString()}</p><p className="muted mt-1 break-all text-xs">Conflict {item.conflict_event_id} · selected record {item.selected_event_id}</p></article>)}</div></section> : null}
    <p className="muted text-xs">Campaign IDs and channels are recorded only when supplied. Unmatched sales are not attributed to advertising.</p>
  </div>;
}
