"use client";

import { useMemo, useState } from "react";

const scoringRules = [
  ["Revenue fit", 20, "$500K-$20M"],
  ["Company size", 15, "1-50 employees"],
  ["Priority industry", 15, "Six approved vertical groups"],
  ["Geographic fit", 15, "United States or UAE"],
  ["Growth readiness", 10, "MVP, revenue, or funding"],
  ["Business model", 10, "SaaS, service, product, funded startup"],
  ["Decision authority", 10, "Founder, technical or operations leader"],
  ["Buying readiness", 5, "Retainer or milestone/SOW"],
] as const;

const personas = [
  { name: "Scaling CTO", profile: "10-40 employees · $1M-$10M", trigger: "Hiring delay, sprint loss, customer deadline" },
  { name: "Non-Technical Founder", profile: "1-10 employees · funded or early revenue", trigger: "Funding, failed vendor, no-code ceiling" },
  { name: "Operations Owner", profile: "10-50 employees · established SMB", trigger: "Audit, manual-process failure, client loss" },
] as const;

const hardStops = [
  "Revenue below $500K",
  "Crypto, Web3, NFT, gambling or marketplace model",
  "Headquarters outside US/UAE",
  "No defined software need",
  "Requires 100% on-site delivery",
] as const;

export function IcpManager() {
  const [view, setView] = useState<"rules" | "personas" | "versions">("rules");
  const totalWeight = useMemo(() => scoringRules.reduce((sum, rule) => sum + rule[1], 0), []);

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-4 rounded-3xl bg-slate-950 p-6 text-white shadow-sm sm:flex-row sm:items-end sm:justify-between sm:p-8">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Qualification control center</p>
          <h1 className="mt-3 text-3xl font-bold tracking-tight">ICP & Persona Management</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
            Datamart Playbook v1 is the active scoring source. Future changes become drafts, then publish as new versions without rewriting application code.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="rounded-full bg-emerald-400/15 px-3 py-1.5 text-xs font-bold text-emerald-300">Active · v1</span>
          <button type="button" disabled title="Enabled after Supabase authentication is connected" className="cursor-not-allowed rounded-xl bg-white/10 px-4 py-2 text-sm font-bold text-slate-400">
            Create draft
          </button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {[
          ["100", "Total scoring weight"],
          ["3", "Operational personas"],
          ["5", "Hard-stop rules"],
        ].map(([value, label]) => (
          <article key={label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-3xl font-black text-slate-950">{value}</p>
            <p className="mt-1 text-sm font-medium text-slate-500">{label}</p>
          </article>
        ))}
      </div>

      <div className="rounded-3xl border border-slate-200 bg-white shadow-sm">
        <div className="flex gap-2 overflow-x-auto border-b border-slate-200 p-4">
          {(["rules", "personas", "versions"] as const).map((item) => (
            <button key={item} type="button" onClick={() => setView(item)} className={`rounded-xl px-4 py-2 text-sm font-bold capitalize ${view === item ? "bg-teal-600 text-white" : "bg-slate-100 text-slate-600"}`}>
              {item}
            </button>
          ))}
        </div>

        {view === "rules" && (
          <div className="grid gap-6 p-5 lg:grid-cols-[1.5fr_1fr] lg:p-6">
            <div>
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-lg font-bold text-slate-950">Weighted fit criteria</h2>
                <span className="text-xs font-bold text-teal-700">{totalWeight}/100</span>
              </div>
              <div className="overflow-hidden rounded-2xl border border-slate-200">
                {scoringRules.map(([label, weight, detail]) => (
                  <div key={label} className="grid grid-cols-[1fr_auto] gap-4 border-b border-slate-100 p-4 last:border-0">
                    <div><p className="text-sm font-bold text-slate-800">{label}</p><p className="mt-1 text-xs text-slate-500">{detail}</p></div>
                    <span className="rounded-lg bg-teal-50 px-2.5 py-1 text-xs font-black text-teal-700">{weight} pts</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <h2 className="mb-4 text-lg font-bold text-slate-950">Immediate disqualifiers</h2>
              <div className="space-y-3">
                {hardStops.map((rule) => <div key={rule} className="rounded-xl border border-red-100 bg-red-50 p-3 text-sm font-semibold text-red-800">{rule}</div>)}
              </div>
              <div className="mt-5 rounded-2xl bg-slate-100 p-4 text-xs leading-5 text-slate-600">
                Unknown facts receive zero points and remain visible as missing evidence. The agent never invents a match.
              </div>
            </div>
          </div>
        )}

        {view === "personas" && <div className="grid gap-4 p-5 lg:grid-cols-3 lg:p-6">{personas.map((persona) => <article key={persona.name} className="rounded-2xl border border-slate-200 p-5"><p className="text-xs font-bold uppercase tracking-[0.15em] text-teal-700">Persona</p><h2 className="mt-2 text-xl font-bold">{persona.name}</h2><p className="mt-3 text-sm text-slate-500">{persona.profile}</p><p className="mt-5 text-xs font-bold text-slate-700">Key trigger</p><p className="mt-1 text-sm leading-6 text-slate-600">{persona.trigger}</p></article>)}</div>}

        {view === "versions" && <div className="p-5 lg:p-6"><div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-bold text-emerald-950">Datamart Core ICP · Version 1</p><p className="mt-1 text-sm text-emerald-800">Effective March 1, 2026 · Source: approved ICP & Persona Playbook</p></div><span className="rounded-full bg-emerald-600 px-3 py-1 text-xs font-bold text-white">Active</span></div></div><p className="mt-4 text-sm text-slate-500">Publishing, archiving, and rescoring controls will activate after Supabase authentication and role enforcement are connected.</p></div>}
      </div>
    </section>
  );
}
