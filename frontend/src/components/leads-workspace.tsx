"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type Role = "admin" | "manager" | "sales";
type LeadStatus = "new" | "researching" | "scored" | "qualified" | "review" | "nurture" | "disqualified" | "archived";
type Lead = { id: string; company_name: string | null; person_name: string | null; title: string | null; linkedin_url: string | null; company_url: string | null; email: string | null; country: string | null; industry: string | null; status: LeadStatus; assigned_to: string | null; created_at: string };
type Profile = { id: string; email: string; full_name: string | null; role: Role };

const statuses: LeadStatus[] = ["new", "researching", "scored", "qualified", "review", "nurture", "disqualified", "archived"];
const blankLead = (): Lead => ({ id: "", company_name: "", person_name: "", title: "", linkedin_url: "", company_url: "", email: "", country: "", industry: "", status: "new", assigned_to: null, created_at: "" });

export function LeadsWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [role, setRole] = useState<Role | null>(null);
  const [salesUsers, setSalesUsers] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState<Lead | null>(null);
  const [draft, setDraft] = useState<Lead>(blankLead());
  const [deleteTarget, setDeleteTarget] = useState<Lead | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!supabase) return;
    setLoading(true); setError("");
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) return;
    const [leadResult, profileResult] = await Promise.all([
      supabase.from("leads").select("id,company_name,person_name,title,linkedin_url,company_url,email,country,industry,status,assigned_to,created_at").order("created_at", { ascending: false }).limit(200),
      supabase.from("profiles").select("role").eq("id", userData.user.id).single(),
    ]);
    if (leadResult.error) setError(leadResult.error.message); else setLeads((leadResult.data ?? []) as Lead[]);
    const nextRole = profileResult.data?.role as Role | undefined;
    setRole(nextRole ?? null);
    if (nextRole === "admin" || nextRole === "manager") {
      const { data, error: salesError } = await supabase.from("profiles").select("id,email,full_name,role").eq("role", "sales").eq("is_active", true).order("email");
      if (salesError) setError(salesError.message); else setSalesUsers((data ?? []) as Profile[]);
    } else setSalesUsers([]);
    setLoading(false);
  }, [supabase]);

  useEffect(() => { const task = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(task); }, [load]);

  function startEdit(lead: Lead) { setNotice(""); setError(""); setEditing(lead); setDraft({ ...lead }); }
  function changeDraft(field: keyof Lead, value: string) { setDraft((current) => ({ ...current, [field]: value })); }

  async function saveLead(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supabase || !editing) return;
    setSaving(true); setError(""); setNotice("");
    const { error: rpcError } = await supabase.rpc("update_lead", { target_id: editing.id, next_company_name: draft.company_name, next_person_name: draft.person_name, next_title: draft.title, next_linkedin_url: draft.linkedin_url, next_company_url: draft.company_url, next_email: draft.email, next_country: draft.country, next_industry: draft.industry, next_status: draft.status });
    setSaving(false);
    if (rpcError) { setError(rpcError.message); return; }
    setEditing(null); setNotice("Lead updated."); void load();
  }

  async function assignLead(leadId: string, assigneeId: string) {
    if (!supabase || !assigneeId) return;
    setError(""); setNotice("");
    const { error: rpcError } = await supabase.rpc("assign_lead", { target_id: leadId, assignee_id: assigneeId });
    if (rpcError) { setError(rpcError.message); return; }
    setNotice("Lead assigned to the sales team."); void load();
  }

  async function removeLead() {
    if (!supabase || !deleteTarget) return;
    setSaving(true); setError("");
    const { error: rpcError } = await supabase.rpc("delete_lead", { target_id: deleteTarget.id });
    setSaving(false);
    if (rpcError) { setError(rpcError.message); return; }
    setDeleteTarget(null); setNotice("Lead deleted. Its import history and audit record were retained."); void load();
  }

  const canAssign = role === "admin" || role === "manager";
  const canDelete = role === "admin";

  return <section className="space-y-6">
    <header className="flex flex-col gap-4 rounded-3xl bg-slate-950 p-7 text-white sm:flex-row sm:items-end sm:justify-between"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Qualified pipeline</p><h1 className="mt-3 text-3xl font-bold">Leads</h1><p className="mt-3 text-sm text-slate-300">Edit lead facts safely, assign work to sales, and retain an audit trail for administrative deletion.</p></div><Link href="/add-leads" className="rounded-xl bg-teal-400 px-4 py-2 text-center text-sm font-bold text-slate-950">Add leads</Link></header>
    {error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
    {notice && <p className="rounded-xl bg-teal-50 p-4 text-sm font-medium text-teal-800">{notice}</p>}
    <div className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">{loading ? <p className="p-8 text-sm text-slate-500">Loading leads...</p> : leads.length === 0 ? <div className="p-10 text-center"><p className="text-xl font-bold">No accessible leads yet</p><p className="mt-2 text-sm text-slate-500">Add profile links or import a CSV to begin.</p></div> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="p-4">Lead</th><th className="p-4">Company</th><th className="p-4">Status</th><th className="p-4">Added</th><th className="p-4">Evidence source</th><th className="p-4">Actions</th></tr></thead><tbody>{leads.map((lead) => <tr key={lead.id} className="border-t border-slate-100 align-top"><td className="p-4"><p className="font-bold text-slate-900">{lead.person_name || "Research pending"}</p><p className="mt-1 text-xs text-slate-500">{lead.title || "Title unknown"}</p></td><td className="p-4">{lead.company_name || "Research pending"}</td><td className="p-4"><span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-bold capitalize text-amber-800">{lead.status}</span></td><td className="p-4 text-slate-500">{new Date(lead.created_at).toLocaleDateString()}</td><td className="p-4">{lead.linkedin_url ? <a href={lead.linkedin_url} target="_blank" rel="noreferrer" className="font-bold text-teal-700">LinkedIn ↗</a> : <span className="text-slate-400">No link</span>}</td><td className="p-4"><div className="flex min-w-44 flex-col gap-2"><button type="button" onClick={() => startEdit(lead)} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-50">Edit</button>{canAssign && <select aria-label={`Assign ${lead.person_name || "lead"}`} value={lead.assigned_to ?? ""} onChange={(event) => void assignLead(lead.id, event.target.value)} className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700"><option value="">Assign to sales…</option>{salesUsers.map((person) => <option key={person.id} value={person.id}>{person.full_name || person.email}</option>)}</select>}{canDelete && <button type="button" onClick={() => setDeleteTarget(lead)} className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-bold text-red-700 hover:bg-red-50">Delete</button>}</div></td></tr>)}</tbody></table></div>}</div>
    {editing && <div role="dialog" aria-modal="true" aria-label="Edit lead" className="fixed inset-0 z-50 overflow-y-auto bg-slate-950/50 p-4 sm:p-8"><form onSubmit={saveLead} className="mx-auto max-w-3xl rounded-3xl bg-white p-6 shadow-2xl"><div className="flex items-start justify-between gap-6"><div><p className="text-xs font-bold uppercase tracking-[0.16em] text-teal-700">Lead details</p><h2 className="mt-2 text-2xl font-bold text-slate-950">Edit lead</h2><p className="mt-2 text-sm text-slate-500">At least one of company name, LinkedIn URL, or company URL is required.</p></div><button type="button" onClick={() => setEditing(null)} className="text-sm font-bold text-slate-500 hover:text-slate-900">Close</button></div><div className="mt-6 grid gap-4 sm:grid-cols-2">{([['person_name', 'Person name'], ['title', 'Job title'], ['company_name', 'Company name'], ['industry', 'Industry'], ['email', 'Email'], ['country', 'Country'], ['linkedin_url', 'LinkedIn profile URL'], ['company_url', 'Company website URL']] as const).map(([field, label]) => <label key={field} className="block text-sm font-bold text-slate-700">{label}<input value={(draft[field] as string | null) ?? ""} onChange={(event) => changeDraft(field, event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 px-3 py-2 font-normal outline-none focus:border-teal-500" /></label>)}<label className="block text-sm font-bold text-slate-700">Status<select value={draft.status} onChange={(event) => changeDraft("status", event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 font-normal outline-none focus:border-teal-500">{statuses.map((status) => <option key={status} value={status}>{status}</option>)}</select></label></div><div className="mt-7 flex justify-end gap-3"><button type="button" onClick={() => setEditing(null)} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-bold text-slate-700">Cancel</button><button disabled={saving} className="rounded-xl bg-teal-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-60">{saving ? "Saving…" : "Save changes"}</button></div></form></div>}
    {deleteTarget && <div role="dialog" aria-modal="true" aria-label="Delete lead confirmation" className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4"><div className="max-w-md rounded-3xl bg-white p-6 shadow-2xl"><p className="text-xs font-bold uppercase tracking-[0.16em] text-red-700">Permanent operational deletion</p><h2 className="mt-2 text-2xl font-bold text-slate-950">Delete this lead?</h2><p className="mt-3 text-sm leading-6 text-slate-600">This removes <strong>{deleteTarget.person_name || deleteTarget.company_name || "this lead"}</strong> and related operational records. The original import history and a deletion audit record stay available.</p><div className="mt-6 flex justify-end gap-3"><button type="button" onClick={() => setDeleteTarget(null)} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-bold text-slate-700">Cancel</button><button type="button" disabled={saving} onClick={() => void removeLead()} className="rounded-xl bg-red-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-60">{saving ? "Deleting…" : "Delete lead"}</button></div></div></div>}
  </section>;
}
