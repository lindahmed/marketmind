"use client";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Industry } from "@/lib/types";

export function ImportPanel({ industry, workspaceId, onImported }: { industry: Industry; workspaceId: string; onImported: () => Promise<void> }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setMessage("");
    const file = input.current?.files?.[0];
    if (!file) { setError("Choose a CSV file first."); return; }
    if (file.size > 2 * 1024 * 1024) { setError("CSV limit is 2 MB."); return; }
    setBusy(true);
    const data = new FormData(); data.append("file", file);
    try {
      const result = await api<{ imported_rows: number }>("/data/import", { method: "POST", body: data }, workspaceId);
      await onImported(); setMessage(`${result.imported_rows} daily rows saved. Your dashboard is updated.`);
      if (input.current) input.current.value = "";
    } catch (error) { setError(error instanceof Error ? error.message : "Import failed"); }
    finally { setBusy(false); }
  }
  const example = industry.code === "ecommerce"
    ? "2026-01-01,1200.00,45.00,20,16,2,1,200.00,500.00,60.00,40.00,20.00,250.00"
    : "2026-01-01,1200.00,30.00,20,16,2,200.00,400.00,15.00,250.00";
  const template = `${industry.detailed_csv_columns.join(",")}\n${example}\n`;
  return <section className="card max-w-3xl">
    <h2 className="text-xl font-semibold">Bring your daily data</h2>
    <p className="muted mt-3 text-sm leading-relaxed">Upload daily totals for your {industry.name.toLowerCase()} business. Use one row per date, ISO dates (YYYY-MM-DD), and nonnegative amounts in your workspace currency. This detailed template records refunds, variable and fixed costs, and order or appointment outcomes. Allocate fixed costs across dates once; do not repeat a monthly amount on every daily row. Earlier CSV templates are also accepted.</p>
    <p className="muted mt-2 text-sm">{industry.code === "ecommerce" ? "Outcomes refer to the same order cohort as total orders. Fulfilled and cancelled orders are exclusive. Delayed orders may also be fulfilled, but cannot be cancelled." : "Completed and cancelled appointments are exclusive outcomes of the same booking cohort."}</p>
    <div className="my-6 overflow-x-auto rounded-lg bg-[#f4f7f7] p-4"><pre className="text-xs leading-6">{template}</pre></div>
    <a className="text-sm font-semibold text-[#087f69]" href={`data:text/csv;charset=utf-8,${encodeURIComponent(template)}`} download={`${industry.code}-template.csv`}>Download example CSV ↓</a>
    <form onSubmit={submit} className="mt-6 grid gap-5 border-t border-[#dfe7e7] pt-6">
      <label className="label">CSV file<input ref={input} type="file" accept=".csv,text/csv" className="input" required /></label>
      <p className="muted text-xs">Up to 2 MB and 10,000 rows. Reimporting a date replaces that day’s totals; it does not add to them.</p>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {message && <p role="status" className="text-sm text-[#087f69]">{message}</p>}
      <div><button disabled={busy} className="primary">{busy ? "Importing…" : "Import daily totals →"}</button></div>
    </form>
  </section>;
}
