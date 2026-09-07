"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";
import { CollectionSearchBar } from "@/components/collection-search-bar";

type Job = { id: string; job_type: string; status: string; attempts: number; max_attempts: number; error_message: string | null; leads: { person_name: string | null; company_name: string | null } | null };

export function ProcessingWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [jobs, setJobs] = useState<Job[]>([]); const [error, setError] = useState(""); const [searchTerm, setSearchTerm] = useState(""); const [statusFilter, setStatusFilter] = useState("all");
  const visibleJobs = useMemo(() => {
    const search = searchTerm.trim().toLocaleLowerCase();
    return jobs.filter((job) => {
      const matchesSearch = !search || [job.job_type, job.status, job.error_message, job.leads?.person_name, job.leads?.company_name].some((value) => value?.toLocaleLowerCase().includes(search));
      return matchesSearch && (statusFilter === "all" || job.status.toLocaleLowerCase() === statusFilter);
    });
  }, [jobs, searchTerm, statusFilter]);
  const jobStatuses = useMemo(() => [...new Set(jobs.map((job) => job.status.toLocaleLowerCase()))].sort(), [jobs]);
  const load = useCallback(async () => { if (!supabase) return; const result = await supabase.from("processing_jobs").select("id,job_type,status,attempts,max_attempts,error_message,leads(person_name,company_name)").order("created_at", { ascending: false }).limit(100); if (result.error) setError(result.error.message); else setJobs((result.data ?? []) as unknown as Job[]); }, [supabase]);
  useEffect(() => { const task = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(task); }, [load]);
  return <section className="space-y-6"><header className="rounded-3xl bg-slate-950 p-7 text-white"><p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Controlled enrichment</p><h1 className="mt-3 text-3xl font-bold">Processing</h1><p className="mt-3 text-sm text-slate-300">Vibe jobs run only through the explicitly started worker. No LinkedIn scraping or messaging occurs.</p></header>{error && <p className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}{jobs.length > 0 && <CollectionSearchBar label="Search processing jobs" placeholder="Search by lead, company, job type, status, or error" value={searchTerm} onChange={setSearchTerm} shownCount={visibleJobs.length} totalCount={jobs.length} noun="jobs"><label className="text-sm font-bold text-slate-700">Status<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 font-normal text-slate-950"><option value="all">All</option>{jobStatuses.map((status) => <option key={status} value={status}>{status}</option>)}</select></label></CollectionSearchBar>}<div className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="p-4">Lead</th><th className="p-4">Job</th><th className="p-4">Status</th><th className="p-4">Attempts</th><th className="p-4">Details</th></tr></thead><tbody>{jobs.length === 0 ? <tr><td colSpan={5} className="p-8 text-center text-slate-500">No accessible processing jobs.</td></tr> : visibleJobs.length === 0 ? <tr><td colSpan={5} className="p-8 text-center text-slate-500">No processing jobs match the current search and filter.</td></tr> : visibleJobs.map((job) => <tr key={job.id} className="border-t border-slate-100"><td className="p-4 font-bold">{job.leads?.person_name || job.leads?.company_name || "Research pending"}</td><td className="p-4 capitalize">{job.job_type}</td><td className="p-4"><span className="rounded-full bg-teal-50 px-2.5 py-1 text-xs font-bold capitalize text-teal-800">{job.status}</span></td><td className="p-4">{job.attempts}/{job.max_attempts}</td><td className="p-4 text-xs text-red-700">{job.error_message || "—"}</td></tr>)}</tbody></table></div></section>;
}
