import { useState } from "react";
import type { Dashboard } from "@/lib/types";

function number(value: number | null | undefined, currency?: string) {
  if (value == null) return "—";
  try {
    return new Intl.NumberFormat("en", currency ? { style: "currency", currency, maximumFractionDigits: 0 } : { maximumFractionDigits: 1 }).format(value);
  } catch { return `${currency ?? ""} ${value.toFixed(0)}`; }
}

export function DashboardView({ data, onImport, onReportingPeriod }: { data: Dashboard; onImport: () => void; onReportingPeriod: (start: string, end: string) => Promise<void> }) {
  const appointment = data.industry.code === "appointments";
  const [startDate, setStartDate] = useState(data.reporting_period.start ?? "");
  const [endDate, setEndDate] = useState(data.reporting_period.end ?? "");
  const cards = [
    { title: "Net revenue", value: number(data.kpis.net_revenue, data.currency), note: "Gross revenue after refunds" },
    { title: "Estimated profit", value: number(data.kpis.estimated_profit, data.currency), note: "After variable costs and ad spend" },
    { title: "Estimated operating profit", value: number(data.kpis.estimated_operating_profit, data.currency), note: "After reported fixed costs too" },
    { title: "Ad spend", value: number(data.kpis.ad_spend, data.currency), note: "Marketing investment" },
    ...(appointment ? [{ title: "Scheduled appointments", value: number(data.kpis.scheduled_appointments), note: "Counted on scheduled date where supplied" }] : []),
    { title: appointment ? "Completed appointments" : "Orders", value: number(data.kpis[appointment ? "completed" : "orders"]), note: appointment ? `${number(data.kpis.completion_rate)}% completion rate` : `${number(data.kpis.average_order_value, data.currency)} average order value` },
  ];
  const recent = data.series.slice(-30);
  const max = Math.max(...recent.map(row => row.revenue), 1);
  const min = Math.min(...recent.map(row => row.revenue), 0);
  const chartY = (value: number) => 200 - (value - min) / (max - min) * 180;
  return <div className="grid gap-6">
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-[#c9e6dc] bg-[#eaf7f1] px-5 py-4">
      <div><p className="text-sm font-semibold text-[#096c55]">Your private intelligence workspace</p><p className="mt-1 text-xs text-[#49766a]">{data.industry.name} pack · {data.row_count} imported days · {data.period_start ? `${data.period_start} to ${data.period_end}` : "Ready for your first import"}</p></div>
      <button className="primary" onClick={onImport}>Import data +</button>
    </div>
    <form className="card flex flex-wrap items-end gap-4" onSubmit={event => { event.preventDefault(); void onReportingPeriod(startDate, endDate); }}>
      <label className="label">From<input className="input mt-1" type="date" value={startDate} onChange={event => setStartDate(event.target.value)} required /></label>
      <label className="label">Through<input className="input mt-1" type="date" value={endDate} onChange={event => setEndDate(event.target.value)} required /></label>
      <button className="secondary">Apply reporting period</button>
      <p className="muted text-xs">{data.reporting_period.complete ? "Every calendar day in this range has data." : `${data.reporting_period.missing_days} calendar days have no imported row; missing days are excluded, not treated as zero.`}</p>
    </form>
    {data.data_quality.legacy_rows > 0 && <p role="note" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{data.data_quality.legacy_rows} legacy data row(s) do not include reported refunds or fulfillment costs. Upload detailed records when those amounts are available.</p>}
    {data.data_quality.fixed_cost_unknown_rows > 0 && <p role="note" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Fixed costs are not reported for {data.data_quality.fixed_cost_unknown_rows} row(s); estimated operating profit may be overstated. Use the latest detailed CSV template to include fixed costs.</p>}
    {(data.data_quality.source_overlap_days ?? 0) > 0 && <p role="note" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{data.data_quality.source_overlap_days} day(s) have both CSV summaries and reconciled events. Existing CSV values are retained for those days until the sources can be safely compared. Review Data Sources &amp; Data Quality.</p>}
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{cards.map((card, index) => <section className="card" key={card.title}>
      <p className="muted text-sm">{card.title}</p><p className={`mt-4 text-3xl font-semibold tracking-tight ${index === 1 && (data.kpis.estimated_profit ?? 0) < 0 ? "text-red-700" : ""}`}>{data.row_count ? card.value : "—"}</p><p className="muted mt-3 text-xs">{card.note}</p>
    </section>)}</div>
    <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
      <section className="card">
        <div className="flex justify-between gap-4"><div><h2 className="font-semibold">Net revenue over time</h2><p className="muted mt-1 text-xs">Last {Math.min(data.row_count, 30)} imported days · {data.currency}</p></div><span className="eyebrow muted">Daily totals</span></div>
        {recent.length ? <>
          <svg viewBox="0 0 600 230" className="mt-6 w-full" role="img" aria-label="Daily net revenue bar chart">
            <title>Daily net revenue for the last {recent.length} imported days</title>
            {[0, 1, 2, 3].map(i => <g key={i}><line x1="44" x2="590" y1={20 + i * 60} y2={20 + i * 60} stroke="#e5eeee" /><text x="36" y={24 + i * 60} textAnchor="end" fill="#647780" fontSize="10">{number(max - (max - min) * i / 3)}</text></g>)}
            <line x1="44" x2="590" y1={chartY(0)} y2={chartY(0)} stroke="#9aabaa" />
            {recent.map((row, i) => <rect key={row.date} x={48 + i * 540 / recent.length} y={Math.min(chartY(row.revenue), chartY(0))} width={Math.max(3, 540 / recent.length - 6)} height={Math.abs(chartY(row.revenue) - chartY(0))} fill={row.revenue < 0 ? "#b91c1c" : "#279b83"} rx="3"><title>{row.date}: {number(row.revenue, data.currency)}</title></rect>)}
            <text x="48" y="224" fontSize="11" fill="#647780">{recent[0].date}</text><text x="590" y="224" textAnchor="end" fontSize="11" fill="#647780">{recent[recent.length - 1].date}</text>
          </svg>
          <details className="mt-4 text-xs"><summary className="cursor-pointer text-[#087f69]">View chart data</summary><div className="mt-3 max-h-48 overflow-auto"><table className="w-full text-left"><thead><tr><th>Date</th><th>Net revenue</th><th>Refunds</th><th>Variable costs</th><th>Fixed costs</th><th>Ad spend</th></tr></thead><tbody>{recent.map(row => <tr key={row.date}><td className="py-2">{row.date}</td><td>{number(row.revenue, data.currency)}</td><td>{number(row.refunds, data.currency)}</td><td>{number(row.variable_costs, data.currency)}</td><td>{number(row.fixed_costs, data.currency)}</td><td>{number(row.ad_spend, data.currency)}</td></tr>)}</tbody></table></div></details>
        </> : <div className="flex min-h-64 flex-col items-center justify-center text-center"><span className="mb-4 text-4xl text-[#80a99f]" aria-hidden="true">▥</span><h3 className="font-semibold">Your performance starts here</h3><p className="muted mt-2 max-w-xs text-sm">Import a CSV to see revenue, costs, and profitability over time.</p></div>}
      </section>
      <section className="card"><div className="flex justify-between"><h2 className="font-semibold">Signals to investigate</h2><span className="rounded-full bg-[#eef4f3] px-2 py-1 text-xs">{data.findings.length}</span></div><p className="muted mt-1 text-xs">Industry rules · evidence from your data</p>
        <div className="mt-6 grid gap-4">{data.findings.length ? data.findings.map(finding => <article key={finding.code} className="rounded-xl border border-[#eadfc9] bg-[#fffcf5] p-4"><span className="eyebrow text-[#92682b]">{finding.severity} priority</span><h3 className="mt-2 text-sm font-semibold">{finding.title}</h3><p className="muted mt-2 text-xs leading-5">{finding.evidence}</p></article>) : <div className="rounded-xl bg-[#f4f7f7] p-5"><h3 className="text-sm font-semibold">{data.row_count ? "No rule thresholds triggered" : "Waiting for evidence"}</h3><p className="muted mt-2 text-sm leading-6">{data.row_count ? "Keep importing daily data. These checks highlight symptoms; a root-cause investigation comes in the next milestone." : "Your first import will activate the diagnostics for your industry."}</p></div>}</div>
      </section>
    </div>
    <section className="card"><div className="flex flex-wrap justify-between gap-3"><div><p className="eyebrow text-[#087f69]">The learning loop</p><h2 className="mt-2 font-semibold">Evidence → decisions → experiments</h2></div><span className="muted text-xs">Open a saved investigation in Private knowledge to review strategy</span></div>
      <div className="mt-6 grid gap-3 md:grid-cols-4">{["01  Collect & measure", "02  Investigate evidence", "03  Approve recommendations & design", "04  Evaluate & learn"].map((step, i) => <div key={step} className={`rounded-lg p-4 text-sm ${i < 3 ? "bg-[#eaf7f1] text-[#087f69]" : "bg-[#f4f7f7] text-[#647780]"}`}>{step}<p className="mt-2 text-xs">{i < 3 ? "Available now" : "Next milestone"}</p></div>)}</div>
    </section>
    <p className="muted px-1 text-xs leading-5">{data.profit_note}</p>
  </div>;
}
