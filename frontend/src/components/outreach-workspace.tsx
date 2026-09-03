"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type Score = {
  score: number;
  disposition: string;
  evaluations: { criterion?: string; label?: string; key?: string; outcome: string }[];
  intent_score: number;
  intent_level: string;
  intent_reasons: string[];
};
type Lead = {
  id: string;
  person_name: string | null;
  company_name: string | null;
  title: string | null;
  email: string | null;
  linkedin_url: string | null;
  status: string;
  suppressed: boolean;
  score: Score | null;
  outreach_status: string;
  latest_draft_status: string | null;
};
type Evidence = { id: string; title: string; source_url: string; publisher: string | null; excerpt: string | null };
type Message = {
  id: string;
  status: string;
  subject: string | null;
  body: string;
  provider: string;
  model: string | null;
  generated_at: string;
  updated_at: string;
  evidence_refs: string[];
  grounding_status: string;
  grounding_warnings: string[];
};
type Detail = { lead: Lead; score: Score | null; suppressed: boolean; status: string; latest_message: Message | null; evidence: Evidence[] };

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function OutreachWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const request = useCallback(async (path: string, init?: RequestInit) => {
    if (!supabase) throw new Error("Supabase is not configured");
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) throw new Error("Authentication required");
    const response = await fetch(apiUrl + path, {
      ...init,
      headers: { Authorization: "Bearer " + token, "Content-Type": "application/json", ...init?.headers },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "Outreach request failed");
    return payload;
  }, [supabase]);

  const loadDetail = useCallback(async (leadId: string) => {
    if (!leadId) return;
    const payload = await request("/outreach/" + leadId) as Detail;
    setDetail(payload);
    setSubject(payload.latest_message?.subject || "");
    setBody(payload.latest_message?.body || "");
  }, [request]);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const payload = await request("/outreach") as Lead[];
      setLeads(payload);
      const nextId = selectedId || payload[0]?.id || "";
      setSelectedId(nextId);
      if (nextId) await loadDetail(nextId); else setDetail(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load outreach leads");
    } finally { setLoading(false); }
  }, [loadDetail, request, selectedId]);

  useEffect(() => {
    const task = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(task);
  }, [load]);

  async function choose(leadId: string) {
    setSelectedId(leadId); setError(""); setNotice("");
    try { await loadDetail(leadId); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to load outreach"); }
  }

  async function action(kind: "generate" | "regenerate" | "save") {
    if (!selectedId) return;
    setBusy(kind); setError(""); setNotice("");
    try {
      if (kind === "generate") {
        await request("/outreach/generate", { method: "POST", body: JSON.stringify({ lead_id: selectedId, channel: "email" }) });
      } else if (kind === "regenerate") {
        await request(`/outreach/${selectedId}/regenerate`, { method: "POST", body: "{}" });
      } else {
        await request(`/outreach/${selectedId}/save`, { method: "POST", body: JSON.stringify({ subject, body }) });
      }
      setNotice(kind === "save" ? "Draft edits saved. Nothing was sent." : kind === "regenerate" ? "Draft regenerated and recorded." : "Draft generated and saved for review.");
      await loadDetail(selectedId);
      const refreshed = await request("/outreach") as Lead[];
      setLeads(refreshed);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Outreach action failed");
    } finally { setBusy(""); }
  }

  const message = detail?.latest_message;
  const score = detail?.score;
  const matched = (score?.evaluations || []).filter((item) => item.outcome === "matched");
  const usedEvidence = (detail?.evidence || []).filter((item) => message?.evidence_refs.includes(item.id));
  const blocked = Boolean(detail?.suppressed);
  const editable = message?.status === "draft" && !blocked;

  return <section className="space-y-6">
    <header className="rounded-3xl bg-slate-950 p-7 text-white">
      <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Evidence-grounded preparation</p>
      <h1 className="mt-3 text-3xl font-bold">Outreach</h1>
      <p className="mt-3 max-w-3xl text-sm text-slate-300">Generate, inspect, and edit drafts for approved leads. This page never sends email or automates LinkedIn.</p>
    </header>
    {error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
    {notice && <p role="status" className="rounded-xl bg-teal-50 p-4 text-sm text-teal-800">{notice}</p>}
    <div className="grid gap-6 xl:grid-cols-[22rem_1fr]">
      <aside className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 p-5"><h2 className="font-bold text-slate-950">Eligible leads</h2><p className="mt-1 text-xs text-slate-500">Sales-approved and accessible to you</p></div>
        {loading ? <p className="p-5 text-sm text-slate-500">Loading…</p> : leads.length === 0 ? <p className="p-5 text-sm text-slate-500">No eligible leads.</p> : <div className="max-h-[44rem] overflow-y-auto">{leads.map((lead) => <button type="button" key={lead.id} onClick={() => void choose(lead.id)} className={"block w-full border-b border-slate-100 p-4 text-left hover:bg-slate-50 " + (lead.id === selectedId ? "bg-teal-50" : "bg-white")}><div className="flex items-start justify-between gap-2"><span className="font-bold text-slate-900">{lead.person_name || "Name unknown"}</span><span className={"rounded-full px-2 py-1 text-[10px] font-bold uppercase " + (lead.suppressed ? "bg-red-50 text-red-700" : "bg-slate-100 text-slate-600")}>{lead.suppressed ? "Suppressed" : lead.latest_draft_status || "No draft"}</span></div><p className="mt-1 text-xs text-slate-500">{lead.company_name || "Company unknown"} · {lead.title || "Title unknown"}</p><p className="mt-2 text-xs font-semibold text-teal-700">ICP {lead.score?.score ?? "—"} · Intent {lead.score?.intent_score ?? "—"}</p></button>)}</div>}
      </aside>
      {!detail ? <div className="rounded-3xl border border-slate-200 bg-white p-10 text-center text-sm text-slate-500">Select an eligible lead to review outreach.</div> : <div className="space-y-5">
        {blocked && <div className="rounded-2xl border border-red-200 bg-red-50 p-4"><p className="font-bold text-red-900">Suppressed</p><p className="mt-1 text-sm text-red-800">Generation and draft preparation are blocked for this email address.</p></div>}
        <div className="grid gap-5 lg:grid-cols-2">
          <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="font-bold text-slate-950">Lead context</h2><dl className="mt-4 grid grid-cols-2 gap-4 text-sm"><div><dt className="text-slate-500">Person</dt><dd className="font-semibold">{detail.lead.person_name || "Unknown"}</dd></div><div><dt className="text-slate-500">Company</dt><dd className="font-semibold">{detail.lead.company_name || "Unknown"}</dd></div><div><dt className="text-slate-500">Title</dt><dd className="font-semibold">{detail.lead.title || "Unknown"}</dd></div><div><dt className="text-slate-500">Email</dt><dd className="font-semibold">{detail.lead.email || "Unknown"}</dd></div></dl>{detail.lead.linkedin_url && <a href={detail.lead.linkedin_url} target="_blank" rel="noreferrer" className="mt-4 inline-block text-sm font-bold text-teal-700">LinkedIn profile ↗</a>}</article>
          <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="font-bold text-slate-950">Intelligence</h2><div className="mt-4 flex gap-8"><div><p className="text-3xl font-black">{score?.score ?? "—"}</p><p className="text-xs text-slate-500">ICP · {score?.disposition || "Not scored"}</p></div><div><p className="text-3xl font-black">{score?.intent_score ?? "—"}</p><p className="text-xs capitalize text-slate-500">Intent · {score?.intent_level || "unknown"}</p></div></div><div className="mt-4 text-sm text-slate-600">{matched.slice(0, 3).map((item, index) => <p key={index}>✓ {item.label || item.criterion || item.key}</p>)}{(score?.intent_reasons || []).slice(0, 3).map((reason) => <p key={reason}>• {reason}</p>)}</div></article>
        </div>
        <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-bold text-slate-950">Message</h2><p className="mt-1 text-xs text-slate-500">Status: <span className="font-bold uppercase">{message?.status || "not generated"}</span>{message ? ` · ${message.provider}${message.model ? ` / ${message.model}` : ""}` : ""}</p></div><div className="flex gap-2">{!message && <button type="button" disabled={blocked || Boolean(busy)} onClick={() => void action("generate")} className="rounded-xl bg-teal-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-40">Generate</button>}{message && <button type="button" disabled={!editable || Boolean(busy)} onClick={() => void action("regenerate")} className="rounded-xl border border-teal-300 px-4 py-2 text-sm font-bold text-teal-800 disabled:opacity-40">Regenerate</button>}<button type="button" disabled={!editable || Boolean(busy) || !body.trim()} onClick={() => void action("save")} className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-bold text-white disabled:opacity-40">Save draft</button></div></div>
          {message ? <><label className="mt-5 block text-sm font-bold text-slate-700">Subject<input value={subject} readOnly={!editable} onChange={(event) => setSubject(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 font-normal read-only:bg-slate-50" /></label><label className="mt-4 block text-sm font-bold text-slate-700">Email body<textarea rows={11} value={body} readOnly={!editable} onChange={(event) => setBody(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-300 p-3 font-normal leading-6 read-only:bg-slate-50" /></label><p className="mt-3 text-xs text-slate-500">Grounding: <span className="font-bold">{message.grounding_status}</span></p>{message.grounding_warnings.map((warning) => <p key={warning} className="mt-1 text-xs text-amber-800">{warning}</p>)}</> : <p className="mt-5 text-sm text-slate-500">No current draft. Generate a draft to begin review.</p>}
        </article>
        <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="font-bold text-slate-950">Evidence used for personalization</h2>{usedEvidence.length === 0 ? <p className="mt-3 text-sm text-slate-500">No external evidence was used. Any draft is intentionally generic.</p> : <div className="mt-4 grid gap-3">{usedEvidence.map((item) => <div key={item.id} className="rounded-2xl bg-slate-50 p-4"><a href={item.source_url} target="_blank" rel="noreferrer" className="font-bold text-teal-700">{item.title} ↗</a><p className="mt-1 text-xs font-semibold text-slate-500">{item.publisher || "Publisher unknown"}</p><p className="mt-2 text-sm leading-6 text-slate-600">{item.excerpt || "No excerpt stored."}</p></div>)}</div>}</article>
      </div>}
    </div>
  </section>;
}
