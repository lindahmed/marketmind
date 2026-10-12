"use client";

import { useState } from "react";
import { api } from "@/lib/api";

export function AuthForm({ onAuthenticated }: { onAuthenticated: () => Promise<void> }) {
  const [register, setRegister] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      await api(`/auth/${register ? "register" : "login"}`, {
        method: "POST", body: JSON.stringify(Object.fromEntries(data)),
      });
      await onAuthenticated();
    } catch (error) { setError(error instanceof Error ? error.message : "Sign-in failed"); }
    finally { setBusy(false); }
  }

  return <main className="grid min-h-screen lg:grid-cols-2">
    <section className="flex flex-col justify-between bg-[#15353d] p-8 text-white lg:p-16">
      <div className="text-xl font-bold tracking-tight">marketmind<span className="text-[#91e7c9]"> / AI</span></div>
      <div className="max-w-lg py-16">
        <p className="eyebrow mb-6 text-[#91e7c9]">Clarity before the next campaign</p>
        <h1 className="text-4xl leading-tight font-semibold lg:text-5xl">Understand what grows your business.</h1>
        <p className="mt-6 text-lg leading-relaxed text-[#b8cbce]">Connect your daily performance to better decisions. Track profit, uncover signals, and build the context for your next experiment.</p>
        <div className="mt-10 grid grid-cols-3 gap-4 border-t border-[#3c5960] pt-6 text-sm text-[#b8cbce]">
          <span>Private workspace</span><span>Industry context</span><span>Profit first</span>
        </div>
      </div>
      <p className="text-xs text-[#b8cbce]">MarketMind AI · Foundation preview</p>
    </section>
    <section className="flex items-center justify-center p-8">
      <div className="w-full max-w-md">
        <p className="eyebrow muted mb-3">Your business, in focus</p>
        <h2 className="text-3xl font-semibold">{register ? "Create your workspace" : "Welcome back"}</h2>
        <p className="muted mt-3 mb-8 text-sm">{register ? "Start with your business profile. Import data when you’re ready." : "Sign in to your private business workspace."}</p>
        <form onSubmit={submit} className="grid gap-5">
          {register && <><label className="label">Business name<input name="business_name" className="input" required minLength={2} maxLength={120} autoComplete="organization" /></label>
            <label className="label">Business type<select name="industry" className="input"><option value="ecommerce">E-commerce</option><option value="appointments">Appointment-based</option></select></label></>}
          <label className="label">Email<input name="email" type="email" className="input" required autoComplete="email" maxLength={254} /></label>
          <label className="label">Password<input name="password" type="password" className="input" required minLength={10} maxLength={128} autoComplete={register ? "new-password" : "current-password"} />{register && <span className="muted text-xs font-normal">At least 10 characters.</span>}</label>
          {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
          <button className="primary" disabled={busy}>{busy ? "Please wait…" : register ? "Create workspace →" : "Sign in →"}</button>
        </form>
        <button className="mt-6 text-sm text-[#087f69]" onClick={() => { setRegister(!register); setError(""); }}>{register ? "Already have an account? Sign in" : "New to MarketMind? Create a workspace"}</button>
      </div>
    </section>
  </main>;
}
