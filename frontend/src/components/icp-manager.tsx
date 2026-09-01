"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type AppRole = "admin" | "manager" | "sales";
type IcpVersion = {
  id: string;
  external_id: string;
  name: string;
  version: number;
  status: "draft" | "active" | "archived";
  definition: Record<string, unknown>;
  source: string;
  effective_date: string;
};

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
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [role, setRole] = useState<AppRole>("sales");
  const [versions, setVersions] = useState<IcpVersion[]>([]);
  const [actionMessage, setActionMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const totalWeight = useMemo(() => scoringRules.reduce((sum, rule) => sum + rule[1], 0), []);
  const activeVersion = versions.find((version) => version.status === "active");

  const loadControlData = useCallback(async () => {
    if (!supabase) return;
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;
    const [profileResult, versionsResult] = await Promise.all([
      supabase.from("profiles").select("role").eq("id", user.id).single(),
      supabase.from("icp_versions").select("id, external_id, name, version, status, definition, source, effective_date").order("version", { ascending: false }),
    ]);
    if (profileResult.data?.role) setRole(profileResult.data.role as AppRole);
    if (versionsResult.data) setVersions(versionsResult.data as IcpVersion[]);
  }, [supabase]);

  useEffect(() => {
    const task = window.setTimeout(() => void loadControlData(), 0);
    return () => window.clearTimeout(task);
  }, [loadControlData]);

  async function createDraft() {
    if (!supabase || !activeVersion || !["admin", "manager"].includes(role)) return;
    setBusy(true);
    setActionMessage("");
    const { data: { user } } = await supabase.auth.getUser();
    const nextVersion = Math.max(...versions.map((version) => version.version), 0) + 1;
    const { error } = await supabase.from("icp_versions").insert({
      external_id: `datamart-icp-v${nextVersion}`,
      name: activeVersion.name,
      version: nextVersion,
      status: "draft",
      definition: activeVersion.definition,
      source: `${activeVersion.source} (drafted from v${activeVersion.version})`,
      effective_date: new Date().toISOString().slice(0, 10),
      created_by: user?.id,
    });
    setBusy(false);
    setActionMessage(error ? error.message : `Draft v${nextVersion} created. The active version is unchanged.`);
    if (!error) { setView("versions"); await loadControlData(); }
  }

  async function publishVersion(versionId: string) {
    if (!supabase || role !== "admin") return;
    setBusy(true);
    const { error } = await supabase.rpc("publish_icp_version", { target_id: versionId });
    setBusy(false);
    setActionMessage(error ? error.message : "Draft published. New scoring uses this version; prior scores retain their original version.");
    if (!error) await loadControlData();
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-4 rounded-3xl bg-slate-950 p-6 text-white shadow-sm sm:flex-row sm:items-end sm:justify-between sm:p-8">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Qualification control center</p>
          <h1 className="mt-3 text-3xl font-bold tracking-tight">ICP & Persona Management</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
            Datamart Playbook v{activeVersion?.version ?? 1} is the active scoring source. Changes become drafts, then publish as new versions without rewriting application code.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="rounded-full bg-emerald-400/15 px-3 py-1.5 text-xs font-bold text-emerald-300">Active · v{activeVersion?.version ?? 1}</span>
          <button type="button" onClick={createDraft} disabled={busy || !activeVersion || !["admin", "manager"].includes(role)} title={role === "sales" ? "Manager or admin role required" : undefined} className="rounded-xl bg-white/10 px-4 py-2 text-sm font-bold text-white disabled:cursor-not-allowed disabled:text-slate-500">
            {busy ? "Working..." : "Create draft"}
          </button>
        </div>
      </div>

      {actionMessage && <p role="status" className="rounded-xl border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900">{actionMessage}</p>}

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

        {view === "versions" && <div className="space-y-3 p-5 lg:p-6">{versions.length === 0 ? <p className="rounded-2xl bg-slate-100 p-5 text-sm text-slate-600">Run the Phase 5 migration and safe ICP seed to load version controls.</p> : versions.map((version) => <div key={version.id} className={`rounded-2xl border p-5 ${version.status === "active" ? "border-emerald-200 bg-emerald-50" : "border-slate-200"}`}><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-bold text-slate-950">{version.name} · Version {version.version}</p><p className="mt-1 text-sm text-slate-600">Effective {version.effective_date} · {version.source}</p></div><div className="flex items-center gap-2"><span className="rounded-full bg-slate-700 px-3 py-1 text-xs font-bold capitalize text-white">{version.status}</span>{version.status === "draft" && role === "admin" && <button type="button" disabled={busy} onClick={() => publishVersion(version.id)} className="rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-bold text-white disabled:opacity-60">Publish</button>}</div></div></div>)}</div>}
      </div>
    </section>
  );
}
