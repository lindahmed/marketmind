"use client";

import { useCallback, useEffect, useState } from "react";
import { AuthForm } from "@/components/auth-form";
import { DashboardView } from "@/components/dashboard";
import { EvidenceWorkspace } from "@/components/evidence-workspace";
import { ExperimentsWorkspace } from "@/components/experiments-workspace";
import { ImportPanel } from "@/components/import-panel";
import { ProfileForm } from "@/components/profile-form";
import { WorkflowJobsPanel } from "@/components/workflow-jobs-panel";
import { DataSourcesWorkspace } from "@/components/data-sources-workspace";
import { api, ApiError } from "@/lib/api";
import type { Dashboard, Profile, Session } from "@/lib/types";

type View = "overview" | "profile" | "imports" | "data-sources" | "knowledge" | "experiments";
const titles: Record<View, string> = { overview: "Business overview", profile: "Business profile", imports: "Data imports", "data-sources": "Data Sources & Data Quality", knowledge: "Private knowledge", experiments: "Experiments" };

export default function Home() {
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("overview");

  const loadSession = useCallback(async () => {
    try { setSession(await api<Session>("/auth/me")); setError(""); }
    catch (error) {
      if (error instanceof ApiError && error.status === 401) setSession(null);
      else setError(error instanceof Error ? error.message : "Could not load session");
    } finally { setLoading(false); }
  }, []);

  const workspaceId = session?.workspaces[0]?.id;
  const refresh = useCallback(async () => {
    if (!workspaceId) return;
    const [business, overview] = await Promise.all([
      api<Profile>("/business", {}, workspaceId), api<Dashboard>("/dashboard", {}, workspaceId),
    ]);
    setProfile(business); setDashboard(overview); setError("");
  }, [workspaceId]);

  const loadReportingPeriod = useCallback(async (startDate: string, endDate: string) => {
    if (!workspaceId) return;
    const period = new URLSearchParams({ start_date: startDate, end_date: endDate });
    setDashboard(await api<Dashboard>(`/dashboard?${period}`, {}, workspaceId));
  }, [workspaceId]);

  useEffect(() => { void loadSession(); }, [loadSession]);
  useEffect(() => {
    if (!session) return;
    void refresh().catch(error => {
      if (error instanceof ApiError && error.status === 401) { setSession(null); setProfile(null); setDashboard(null); }
      else setError(error instanceof Error ? error.message : "Could not load business data");
    });
  }, [refresh, session]);

  async function logout() {
    try { await api("/auth/logout", { method: "POST" }); setSession(null); setProfile(null); setDashboard(null); setView("overview"); }
    catch (error) { setError(error instanceof Error ? error.message : "Sign-out failed"); }
  }

  if (loading) return <div role="status" className="flex min-h-screen items-center justify-center muted">Opening MarketMind…</div>;
  if (!session && error) return <main className="mx-auto mt-24 max-w-lg card"><h1 className="text-xl font-semibold">Backend connection required</h1><p role="alert" className="muted my-5">{error}</p><button className="primary" onClick={() => void loadSession()}>Retry connection</button></main>;
  if (!session) return <AuthForm onAuthenticated={loadSession} />;

  return <div className="min-h-screen lg:grid lg:grid-cols-[240px_1fr]">
    <aside className="flex flex-col bg-[#15353d] p-6 text-white lg:min-h-screen">
      <div className="mb-8 text-xl font-bold tracking-tight">marketmind<span className="text-[#91e7c9]"> / AI</span></div>
      <div className="mb-7 rounded-xl border border-[#3c5960] p-4"><p className="eyebrow text-[#91e7c9]">Workspace</p><p className="mt-2 truncate text-sm font-semibold">{profile?.name ?? session.workspaces[0]?.name}</p><p className="mt-1 text-xs text-[#b8cbce]">{profile?.industry === "appointments" ? "Appointment-based" : "E-commerce"}</p></div>
      <nav aria-label="Workspace navigation" className="grid gap-2 sm:grid-cols-3 lg:grid-cols-1">{(["overview", "profile", "imports", "data-sources", "knowledge", "experiments"] as View[]).map(item => <button key={item} onClick={() => setView(item)} className={`nav-item ${view === item ? "active" : ""}`} aria-current={view === item ? "page" : undefined}>{item === "overview" ? "◫  Overview" : item === "profile" ? "◎  Business profile" : item === "imports" ? "↥  Data imports" : item === "data-sources" ? "⇄  Data sources" : item === "knowledge" ? "◈  Private knowledge" : "◉  Experiments"}</button>)}</nav>
      <div className="mt-8 lg:mt-auto"><p className="truncate text-xs text-[#b8cbce]">{session.email}</p><button className="mt-3 text-sm text-[#b8cbce] hover:text-white" onClick={() => void logout()}>Sign out ↗</button></div>
    </aside>
    <main className="min-w-0">
      <header className="flex items-center justify-between gap-4 border-b border-[#dfe7e7] bg-white px-6 py-5 lg:px-10"><span className="muted text-sm">Workspace / <span className="text-[#172b36]">{titles[view]}</span></span><span className="rounded-full border border-[#dfe7e7] px-3 py-1 text-xs text-[#087f69]">V1 · simulations only</span></header>
      <div className="mx-auto max-w-7xl p-6 lg:p-10">
        <div className="mb-8"><p className="eyebrow muted mb-3">Measure. Understand. Improve.</p><h1 className="text-3xl font-semibold tracking-tight">{titles[view]}</h1><p className="muted mt-3 text-sm">{view === "overview" ? "A clear view of performance, with profit at the center." : view === "profile" ? "Define the context for every business decision." : view === "knowledge" ? "Keep business documents private. See which evidence supports each review." : view === "experiments" ? "Review evidence-backed recommendations, approve measured simulations, and track their dispatch." : view === "data-sources" ? "Connect private business records and review reconciliation before they inform decisions." : "Turn daily business data into useful evidence."}</p></div>
        {profile && <WorkflowJobsPanel workspaceId={profile.id} />}
        {error && <div role="alert" className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error} <button className="underline" onClick={() => void refresh().catch(error => setError(error.message))}>Retry</button></div>}
        {!profile || !dashboard ? <p role="status" className="muted">Loading your business…</p> : view === "overview" ? <DashboardView data={dashboard} onImport={() => setView("imports")} onReportingPeriod={loadReportingPeriod} /> : view === "profile" ? <ProfileForm profile={profile} onSaved={refresh} /> : view === "imports" ? <ImportPanel industry={dashboard.industry} workspaceId={profile.id} onImported={refresh} /> : view === "data-sources" ? <DataSourcesWorkspace workspaceId={profile.id} /> : view === "knowledge" ? <EvidenceWorkspace workspaceId={profile.id} /> : <ExperimentsWorkspace workspaceId={profile.id} />}
      </div>
    </main>
  </div>;
}
