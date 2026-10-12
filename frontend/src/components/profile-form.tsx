"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Profile } from "@/lib/types";

export function ProfileForm({ profile, onSaved }: { profile: Profile; onSaved: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage(""); setFailed(false);
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const lines = (value: FormDataEntryValue) => String(value).split("\n").map(line => line.trim()).filter(Boolean);
    try {
      await api("/business", { method: "PUT", body: JSON.stringify({ ...values, goals: lines(values.goals), constraints: lines(values.constraints) }) }, profile.id);
      await onSaved(); setMessage("Business profile saved.");
    } catch (error) { setFailed(true); setMessage(error instanceof Error ? error.message : "Save failed"); }
    finally { setBusy(false); }
  }
  return <form className="card grid max-w-3xl gap-6" onSubmit={submit}>
    <div><h2 className="text-xl font-semibold">Business context</h2><p className="muted mt-2 text-sm">Your goals and boundaries will guide the shared intelligence agents.</p></div>
    <div className="grid gap-5 sm:grid-cols-2">
      <label className="label">Business name<input name="name" className="input" defaultValue={profile.name} minLength={2} maxLength={120} required /></label>
      <label className="label">Currency (3-letter code)<input name="currency" className="input" defaultValue={profile.currency} pattern="[A-Z]{3}" maxLength={3} required /></label>
      <label className="label">Monthly marketing budget<input name="monthly_budget" type="number" className="input" defaultValue={profile.monthly_budget} min="0" max="1000000000" step="0.01" required /></label>
      <label className="label">Industry pack<input className="input" value={profile.industry === "ecommerce" ? "E-commerce" : "Appointment-based"} readOnly /></label>
    </div>
    <label className="label">About your business<textarea name="description" className="input" rows={3} maxLength={2000} defaultValue={profile.description} /></label>
    <label className="label">Goals · one per line<textarea name="goals" className="input" rows={3} defaultValue={profile.goals.join("\n")} placeholder="Increase repeat purchases" /></label>
    <label className="label">Constraints · one per line<textarea name="constraints" className="input" rows={3} defaultValue={profile.constraints.join("\n")} placeholder="Keep discounts below 15%" /></label>
    <p className="muted text-xs">Currency is locked after the first data import. Historical data is never converted automatically.</p>
    {message && <p role={failed ? "alert" : "status"} className={failed ? "text-sm text-red-700" : "text-sm text-[#087f69]"}>{message}</p>}
    <div><button className="primary" disabled={busy}>{busy ? "Saving…" : "Save business profile"}</button></div>
  </form>;
}
