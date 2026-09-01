"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type Lead = { id: string; company_name: string | null; person_name: string | null; title: string | null; linkedin_url: string | null; status: string; created_at: string };

export function LeadsWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!supabase) return;
    const response = await supabase.from("leads").select("id,company_name,person_name,title,linkedin_url,status,created_at").order("created_at", { ascending: false }).limit(200);
    if (response.error) setError(response.error.message); else setLeads((response.data ?? []) as Lead[]);
    setLoading(false);
  }, [supabase]);

  useEffect(() => { const task = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(task); }, [load]);

  return <section className="space-y-6"><header className="flex flex-col gap-4 rounded-3xl bg-slate-950 p-7 text-white sm:flex-row sm:items-end sm:justify-between"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Qualified pipeline</p><h1 className="mt-3 text-3xl font-bold">Leads</h1><p className="mt-3 text-sm text-slate-300">RLS shows managers all leads and sales users only their assigned or created leads.</p></div><Link href="/add-leads" className="rounded-xl bg-teal-400 px-4 py-2 text-center text-sm font-bold text-slate-950">Add leads</Link></header>{error && <p className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}<div className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">{loading ? <p className="p-8 text-sm text-slate-500">Loading leads...</p> : leads.length === 0 ? <div className="p-10 text-center"><p className="text-xl font-bold">No accessible leads yet</p><p className="mt-2 text-sm text-slate-500">Add profile links or import a CSV to begin.</p></div> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="p-4">Lead</th><th className="p-4">Company</th><th className="p-4">Status</th><th className="p-4">Added</th><th className="p-4">Evidence source</th></tr></thead><tbody>{leads.map((lead) => <tr key={lead.id} className="border-t border-slate-100"><td className="p-4"><p className="font-bold text-slate-900">{lead.person_name || "Research pending"}</p><p className="mt-1 text-xs text-slate-500">{lead.title || "Title unknown"}</p></td><td className="p-4">{lead.company_name || "Research pending"}</td><td className="p-4"><span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-bold capitalize text-amber-800">{lead.status}</span></td><td className="p-4 text-slate-500">{new Date(lead.created_at).toLocaleDateString()}</td><td className="p-4">{lead.linkedin_url ? <a href={lead.linkedin_url} target="_blank" rel="noreferrer" className="font-bold text-teal-700">LinkedIn ↗</a> : <span className="text-slate-400">No link</span>}</td></tr>)}</tbody></table></div>}</div></section>;
}
