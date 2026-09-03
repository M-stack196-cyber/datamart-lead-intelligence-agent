"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type Role = "admin" | "manager" | "sales";
type Evaluation = {
  rule_key: string;
  label: string;
  outcome: "matched" | "failed" | "unknown";
  points_awarded: number;
  points_available: number;
  explanation: string;
};
type Score = {
  score: number;
  disposition: string;
  tier: string;
  persona: string | null;
  hard_stops: string[];
  review_reasons: string[];
  evaluations: Evaluation[];
  intent_score: number;
  intent_level: string;
  intent_reasons: string[];
  scored_at: string;
};
type Evidence = {
  id: string;
  title: string;
  source_url: string;
  publisher: string | null;
  excerpt: string | null;
  supports_fields: string[];
};
type Lead = {
  id: string;
  person_name: string | null;
  company_name: string | null;
  title: string | null;
  email: string | null;
  country: string | null;
  industry: string | null;
  status: string;
  sales_approved_at: string | null;
  lead_scores: Score[];
  evidence: Evidence[];
};

const eligibleDispositions = new Set([
  "Strong Fit",
  "Good Fit",
  "Opportunistic / Manual Review",
]);
const latestScore = (lead: Lead) =>
  [...lead.lead_scores].sort((a, b) => b.scored_at.localeCompare(a.scored_at))[0];

export function ReviewWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [role, setRole] = useState<Role | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    if (!supabase) return;
    setLoading(true);
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) return;
    const [profileResult, leadResult] = await Promise.all([
      supabase.from("profiles").select("role").eq("id", userData.user.id).single(),
      supabase
        .from("leads")
        .select("id,person_name,company_name,title,email,country,industry,status,sales_approved_at,lead_scores(score,disposition,tier,persona,hard_stops,review_reasons,evaluations,intent_score,intent_level,intent_reasons,scored_at),evidence(id,title,source_url,publisher,excerpt,supports_fields)")
        .order("updated_at", { ascending: false })
        .limit(100),
    ]);
    setRole((profileResult.data?.role as Role | undefined) ?? null);
    if (leadResult.error) setError(leadResult.error.message);
    else {
      setLeads((leadResult.data ?? []) as unknown as Lead[]);
      setError("");
    }
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    const task = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(task);
  }, [load]);

  async function approve(leadId: string) {
    if (!supabase || role !== "admin") return;
    setBusyId(leadId);
    setError("");
    setMessage("");
    const { error: actionError } = await supabase.rpc("approve_lead_for_sales", {
      target_id: leadId,
    });
    setBusyId("");
    if (actionError) setError(actionError.message);
    else {
      setMessage("Lead approved for sales. The approval was added to the audit log.");
      await load();
    }
  }

  async function setOutcome(leadId: string, outcome: "disqualified" | "nurture") {
    if (!supabase || role !== "admin") return;
    const reason = reasons[leadId]?.trim();
    if (!reason) {
      setError("Enter a review reason before rejecting or moving a lead to nurture.");
      return;
    }
    setBusyId(leadId);
    setError("");
    setMessage("");
    const { error: actionError } = await supabase.rpc("set_lead_review_outcome", {
      target_id: leadId,
      outcome,
      reason,
    });
    setBusyId("");
    if (actionError) setError(actionError.message);
    else {
      setMessage(
        outcome === "disqualified"
          ? "Lead disqualified with an audited reason."
          : "Lead moved to nurture with an audited reason.",
      );
      await load();
    }
  }

  return (
    <section className="space-y-6">
      <header className="rounded-3xl bg-slate-950 p-7 text-white">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Review queue</p>
        <h1 className="mt-3 text-3xl font-bold">Evidence-backed lead review</h1>
        <p className="mt-3 max-w-3xl text-sm text-slate-300">
          Review the latest deterministic score, intent signals, and direct evidence before an administrator records a sales decision.
        </p>
        <p className="mt-3 text-xs font-bold uppercase tracking-wide text-slate-400">Role: {role ?? "loading"}</p>
      </header>

      {error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      {message && <p role="status" className="rounded-xl bg-teal-50 p-4 text-sm text-teal-800">{message}</p>}
      {role === "manager" && (
        <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          Managers can inspect review evidence and assign already-approved leads, but only an administrator can approve, reject, or move a lead to nurture.
        </p>
      )}

      {loading ? (
        <p className="rounded-3xl bg-white p-8 text-sm text-slate-500">Loading review records...</p>
      ) : leads.length === 0 ? (
        <p className="rounded-3xl bg-white p-8 text-sm text-slate-500">No leads are currently visible to your role.</p>
      ) : (
        <div className="space-y-5">
          {leads.map((lead) => {
            const score = latestScore(lead);
            const canApprove = Boolean(
              score &&
                !score.hard_stops.length &&
                eligibleDispositions.has(score.disposition) &&
                lead.status !== "disqualified",
            );
            const exactReason =
              score?.hard_stops[0] ||
              score?.review_reasons[0] ||
              "No disqualification or opportunistic reason recorded.";
            return (
              <article key={lead.id} className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wide text-teal-700">{lead.status}</p>
                    <h2 className="mt-2 text-2xl font-bold text-slate-950">{lead.person_name || "Contact unknown"}</h2>
                    <p className="mt-1 text-sm text-slate-600">
                      {lead.company_name || "Company unknown"} · {lead.title || "Title unknown"} · {lead.country || "Country unknown"}
                    </p>
                    {lead.email && <p className="mt-1 text-sm text-slate-500">{lead.email}</p>}
                  </div>
                  <span className={"rounded-full px-3 py-1.5 text-xs font-bold " + (lead.sales_approved_at ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-700")}>
                    {lead.sales_approved_at ? "Sales approved" : "Awaiting decision"}
                  </span>
                </div>

                <div className="mt-5 grid gap-4 md:grid-cols-3">
                  <div className="rounded-2xl bg-slate-50 p-4">
                    <p className="text-xs font-bold uppercase text-slate-500">ICP</p>
                    <p className="mt-2 text-2xl font-black">{score ? score.score + "/100" : "Unknown"}</p>
                    <p className="mt-1 text-sm text-slate-600">{score?.disposition || "Not scored"}</p>
                  </div>
                  <div className="rounded-2xl bg-slate-50 p-4">
                    <p className="text-xs font-bold uppercase text-slate-500">Intent</p>
                    <p className="mt-2 text-2xl font-black capitalize">{score?.intent_level || "Unknown"}</p>
                    <p className="mt-1 text-sm text-slate-600">{score ? score.intent_score + "/100" : "No score"}</p>
                  </div>
                  <div className="rounded-2xl bg-amber-50 p-4">
                    <p className="text-xs font-bold uppercase text-amber-800">Exact decision reason</p>
                    <p className="mt-2 text-sm leading-6 text-amber-950">{exactReason}</p>
                  </div>
                </div>

                {score && (
                  <div className="mt-5 grid gap-5 lg:grid-cols-2">
                    <div>
                      <h3 className="font-bold text-slate-950">Criteria</h3>
                      <div className="mt-3 space-y-2">
                        {score.evaluations.map((item) => (
                          <div key={item.rule_key} className="rounded-xl border border-slate-200 p-3">
                            <div className="flex justify-between gap-3">
                              <p className="text-sm font-bold">{item.label}</p>
                              <span className="text-xs font-bold capitalize text-slate-500">
                                {item.outcome} · {item.points_awarded}/{item.points_available}
                              </span>
                            </div>
                            <p className="mt-1 text-xs leading-5 text-slate-600">{item.explanation}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <h3 className="font-bold text-slate-950">Intent reasons</h3>
                      <ul className="mt-3 space-y-2 text-sm text-slate-600">
                        {score.intent_reasons.map((reason) => <li key={reason} className="rounded-xl bg-slate-50 p-3">{reason}</li>)}
                      </ul>
                    </div>
                  </div>
                )}

                <div className="mt-5">
                  <h3 className="font-bold text-slate-950">Stored evidence ({lead.evidence.length})</h3>
                  {lead.evidence.length ? (
                    <div className="mt-3 grid gap-3 lg:grid-cols-2">
                      {lead.evidence.map((item) => (
                        <div key={item.id} className="rounded-xl border border-slate-200 p-4">
                          <a href={item.source_url} target="_blank" rel="noreferrer" className="font-bold text-teal-700">{item.title} ↗</a>
                          <p className="mt-1 text-xs text-slate-500">{item.publisher || "Publisher unknown"}</p>
                          {item.excerpt && <p className="mt-2 text-sm leading-6 text-slate-600">{item.excerpt}</p>}
                          <p className="mt-2 text-xs text-slate-500">
                            Supports: {item.supports_fields.length ? item.supports_fields.join(", ") : "No fields declared"}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-2 text-sm text-slate-500">No provider-returned evidence is stored for this lead.</p>
                  )}
                </div>

                {role === "admin" && (
                  <div className="mt-6 border-t border-slate-200 pt-5">
                    <label className="block text-sm font-bold text-slate-700">
                      Review note
                      <input
                        value={reasons[lead.id] ?? ""}
                        onChange={(event) => setReasons((current) => ({ ...current, [lead.id]: event.target.value }))}
                        placeholder="Required for reject or nurture"
                        className="mt-1.5 w-full rounded-xl border border-slate-300 px-3 py-2 font-normal"
                      />
                    </label>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button type="button" disabled={!canApprove || busyId === lead.id} onClick={() => void approve(lead.id)} className="rounded-xl bg-teal-600 px-4 py-2 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-40">Approve for sales</button>
                      <button type="button" disabled={busyId === lead.id} onClick={() => void setOutcome(lead.id, "nurture")} className="rounded-xl border border-amber-300 px-4 py-2 text-sm font-bold text-amber-900 disabled:opacity-40">Move to nurture</button>
                      <button type="button" disabled={busyId === lead.id} onClick={() => void setOutcome(lead.id, "disqualified")} className="rounded-xl border border-red-300 px-4 py-2 text-sm font-bold text-red-800 disabled:opacity-40">Reject / disqualify</button>
                    </div>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
