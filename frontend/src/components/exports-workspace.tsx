"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type Lead = { person_name: string | null; company_name: string | null; title: string | null; email: string | null; country: string | null; linkedin_url: string | null; sales_approved_at: string | null; status: string };
type Role = "admin" | "manager" | "sales";
const esc = (value: string | null) => `"${(value ?? "").replaceAll('"', '""')}"`;

export function ExportsWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [role, setRole] = useState<Role | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    if (!supabase) return;
    const { data: user } = await supabase.auth.getUser();
    if (!user.user) return;
    const [{ data: profile }, { data, error: queryError }] = await Promise.all([
      supabase.from("profiles").select("role").eq("id", user.user.id).single(),
      supabase.from("leads").select("person_name,company_name,title,email,country,linkedin_url,sales_approved_at,status").not("sales_approved_at", "is", null).neq("status", "disqualified").order("sales_approved_at", { ascending: false }),
    ]);
    setRole((profile?.role as Role | undefined) ?? null);
    if (queryError) setError(queryError.message); else setLeads((data ?? []) as Lead[]);
  }, [supabase]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- load() is intentionally invoked on mount to hydrate the authenticated user's export state.
  useEffect(() => { void load(); }, [load]);
  function download() {
    const header = "Person,Company,Title,Email,Country,LinkedIn URL,Approved at";
    const rows = leads.map((lead) => [lead.person_name, lead.company_name, lead.title, lead.email, lead.country, lead.linkedin_url, lead.sales_approved_at].map(esc).join(","));
    const url = URL.createObjectURL(new Blob([[header, ...rows].join("\n")], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = "datamart-approved-leads.csv"; link.click(); URL.revokeObjectURL(url);
  }
  if (role !== "admin") return <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm"><h1 className="text-2xl font-bold">Exports</h1><p className="mt-3 text-sm text-slate-600">Only an administrator can export approved sales leads.</p></section>;
  return <section className="space-y-6"><header className="rounded-3xl bg-slate-950 p-7 text-white"><p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Sales handoff</p><h1 className="mt-3 text-3xl font-bold">Approved lead export</h1><p className="mt-3 text-sm text-slate-300">Only explicitly approved, non-disqualified leads are included.</p></header>{error && <p className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}<div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"><p className="text-4xl font-bold">{leads.length}</p><p className="mt-1 text-sm text-slate-500">Sales-ready leads</p><button type="button" disabled={!leads.length} onClick={download} className="mt-5 rounded-xl bg-teal-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">Download CSV</button></div></section>;
}
