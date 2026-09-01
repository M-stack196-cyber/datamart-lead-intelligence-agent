"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type ImportRow = { id: string; file_name: string; source: string; status: string; total_rows: number; accepted_rows: number; rejected_rows: number; error_summary: { errors?: { row: number; reason: string }[] }; created_at: string };

export function ImportsWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [imports, setImports] = useState<ImportRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => { if (!supabase) return; const response = await supabase.from("imports").select("id,file_name,source,status,total_rows,accepted_rows,rejected_rows,error_summary,created_at").order("created_at", { ascending: false }).limit(100); if (response.error) setError(response.error.message); else setImports((response.data ?? []) as ImportRow[]); setLoading(false); }, [supabase]);
  useEffect(() => { const task = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(task); }, [load]);
  return <section className="space-y-6"><header className="flex flex-col gap-4 rounded-3xl bg-slate-950 p-7 text-white sm:flex-row sm:items-end sm:justify-between"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Intake history</p><h1 className="mt-3 text-3xl font-bold">Imports</h1><p className="mt-3 text-sm text-slate-300">Every batch preserves accepted, rejected, and duplicate-row evidence.</p></div><Link href="/add-leads" className="rounded-xl bg-teal-400 px-4 py-2 text-center text-sm font-bold text-slate-950">New import</Link></header>{error && <p className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}<div className="space-y-3">{loading ? <p className="rounded-2xl bg-white p-6 text-sm text-slate-500">Loading imports...</p> : imports.length === 0 ? <p className="rounded-2xl bg-white p-8 text-center text-sm text-slate-500">No import history yet.</p> : imports.map((item) => <article key={item.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="font-bold text-slate-950">{item.file_name}</p><p className="mt-1 text-xs uppercase tracking-wide text-slate-500">{item.source.replaceAll("_", " ")} · {new Date(item.created_at).toLocaleString()}</p></div><span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold capitalize text-emerald-800">{item.status}</span></div><div className="mt-4 flex flex-wrap gap-4 text-sm"><span>Total <b>{item.total_rows}</b></span><span className="text-emerald-700">Accepted <b>{item.accepted_rows}</b></span><span className="text-red-700">Rejected <b>{item.rejected_rows}</b></span></div>{item.error_summary.errors?.length ? <details className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-800"><summary className="cursor-pointer font-bold">View rejected rows</summary><ul className="mt-2 space-y-1">{item.error_summary.errors.map((row) => <li key={`${row.row}-${row.reason}`}>Row {row.row}: {row.reason}</li>)}</ul></details> : null}</article>)}</div></section>;
}
