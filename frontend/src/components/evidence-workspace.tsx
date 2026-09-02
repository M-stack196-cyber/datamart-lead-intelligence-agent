"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type Evidence = { id: string; title: string; source_url: string; publisher: string | null; excerpt: string | null; supports_fields: string[]; captured_at: string; leads: { person_name: string | null; company_name: string | null } | null };

export function EvidenceWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []); const [items, setItems] = useState<Evidence[]>([]); const [error, setError] = useState("");
  const load = useCallback(async () => { if (!supabase) return; const result = await supabase.from("evidence").select("id,title,source_url,publisher,excerpt,supports_fields,captured_at,leads(person_name,company_name)").order("captured_at", { ascending: false }).limit(100); if (result.error) setError(result.error.message); else setItems((result.data ?? []) as unknown as Evidence[]); }, [supabase]);
  useEffect(() => { const task = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(task); }, [load]);
  return <section className="space-y-6"><header className="rounded-3xl bg-slate-950 p-7 text-white"><p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Source-grounded records</p><h1 className="mt-3 text-3xl font-bold">Evidence</h1><p className="mt-3 text-sm text-slate-300">Provider results are saved with their source links before any later scoring decision.</p></header>{error && <p className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}<div className="space-y-3">{items.length ? items.map((item) => <article key={item.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-bold uppercase tracking-wide text-teal-700">{item.leads?.person_name || item.leads?.company_name || "Lead"}</p><a href={item.source_url} target="_blank" rel="noreferrer" className="mt-2 block font-bold text-slate-950 hover:text-teal-700">{item.title} ↗</a><p className="mt-1 text-xs text-slate-500">{item.publisher || "Source unknown"} · {new Date(item.captured_at).toLocaleString()}</p>{item.excerpt && <p className="mt-3 text-sm text-slate-600">{item.excerpt}</p>}{item.supports_fields.length > 0 && <p className="mt-3 text-xs text-slate-500">Supports: {item.supports_fields.join(", ")}</p>}</article>) : <p className="rounded-2xl bg-white p-8 text-center text-sm text-slate-500">No evidence has been captured yet.</p>}</div></section>;
}
