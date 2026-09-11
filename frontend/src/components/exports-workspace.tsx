"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type ExportLead = {
  lead_id: string;
  person_name: string | null;
  company_name: string | null;
  title: string | null;
  email: string | null;
  country: string | null;
  linkedin_url: string | null;
  score: number;
  disposition: string;
  intent_score: number;
  intent_level: string;
  sales_approved_at: string;
  assigned_sales_name: string;
  assigned_sales_email: string;
};
type Role = "admin" | "manager" | "sales";
type BackupLead = {
  lead_id: string;
  lead_source: string;
  source_id: string;
  status: string;
  person_name: string;
  title: string;
  company_name: string;
  email: string;
  phone: string;
  linkedin_url: string;
  company_url: string;
  country: string;
  industry: string;
  employee_count: string;
  created_at: string;
  source_captured_at: string;
  icp_score: string;
  disposition: string;
  tier: string;
  persona: string;
  review_reasons: string[];
  hard_stops: string[];
  intent_score: string;
  intent_level: string;
  total_drafts: number;
  email_draft_count: number;
  linkedin_draft_count: number;
  approved_count: number;
  rejected_count: number;
  draft_count: number;
  manually_sent_count: number;
  system_sent_count: number;
  lead_replied: boolean;
  latest_reply_at: string;
  email_step_1_status: string;
  email_step_2_status: string;
  email_step_3_status: string;
  email_step_4_status: string;
  linkedin_step_1_status: string;
  linkedin_step_2_status: string;
  linkedin_step_3_status: string;
  linkedin_step_4_status: string;
};
type BackupPreview = {
  source: string;
  status: string;
  limit: number;
  total: number;
  generated_at: string;
  leads: BackupLead[];
};
const esc = (value: string | number | null) => '"' + String(value ?? "").replaceAll('"', '""') + '"';
const apiBase = () => process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === "production" ? "/api" : "http://localhost:8000");

export function ExportsWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [role, setRole] = useState<Role | null>(null);
  const [leads, setLeads] = useState<ExportLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [backupBusy, setBackupBusy] = useState(false);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [backupSource, setBackupSource] = useState("all");
  const [backupStatus, setBackupStatus] = useState("all");
  const [backupPreview, setBackupPreview] = useState<BackupPreview | null>(null);
  const [handoffUnavailable, setHandoffUnavailable] = useState(false);
  const [error, setError] = useState("");

  const previewTotals = useMemo(() => {
    const rows = backupPreview?.leads ?? [];
    return {
      drafts: rows.reduce((sum, row) => sum + row.total_drafts, 0),
      approved: rows.reduce((sum, row) => sum + row.approved_count, 0),
      rejected: rows.reduce((sum, row) => sum + row.rejected_count, 0),
      replies: rows.filter((row) => row.lead_replied).length,
    };
  }, [backupPreview]);

  const load = useCallback(async () => {
    if (!supabase) return;
    setLoading(true);
    setError("");
    const { data: user } = await supabase.auth.getUser();
    if (!user.user) return;
    const { data: profile, error: profileError } = await supabase
      .from("profiles")
      .select("role")
      .eq("id", user.user.id)
      .single();
    if (profileError) {
      setError(profileError.message);
      setLoading(false);
      return;
    }
    const nextRole = (profile?.role as Role | undefined) ?? null;
    setRole(nextRole);
    if (nextRole !== "admin") {
      setLeads([]);
      setLoading(false);
      return;
    }
    const { data, error: exportError } = await supabase.rpc("export_sales_approved_leads");
    if (exportError) {
      setLeads([]);
      setHandoffUnavailable(true);
    } else {
      setLeads((data ?? []) as ExportLead[]);
      setHandoffUnavailable(false);
      setError("");
    }
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    const task = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(task);
  }, [load]);

  function download() {
    const header = "Person,Company,Title,Email,Country,LinkedIn URL,ICP Score,Disposition,Intent Score,Intent Level,Approved At,Assigned Sales Name,Assigned Sales Email";
    const rows = leads.map((lead) =>
      [
        lead.person_name,
        lead.company_name,
        lead.title,
        lead.email,
        lead.country,
        lead.linkedin_url,
        lead.score,
        lead.disposition,
        lead.intent_score,
        lead.intent_level,
        lead.sales_approved_at,
        lead.assigned_sales_name,
        lead.assigned_sales_email,
      ].map(esc).join(","),
    );
    const url = URL.createObjectURL(
      new Blob([[header, ...rows].join("\n")], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "datamart-approved-leads.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  async function downloadLeadBackup() {
    if (!supabase) return;
    setBackupBusy(true);
    setError("");
    try {
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token;
      if (!token) throw new Error("Authentication required");
      const params = new URLSearchParams({ limit: "1000", format: "csv" });
      if (backupSource !== "all") params.set("source", backupSource);
      if (backupStatus !== "all") params.set("status", backupStatus);
      const response = await fetch(`${apiBase()}/leads/backup-export?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Unable to download lead backup");
      }
      const blob = await response.blob();
      const disposition = response.headers.get("content-disposition") || "";
      const filename = disposition.match(/filename="([^"]+)"/)?.[1] || "datamart-lead-backup.csv";
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to download lead backup");
    } finally {
      setBackupBusy(false);
    }
  }

  async function loadBackupPreview() {
    if (!supabase) return;
    setPreviewBusy(true);
    setError("");
    try {
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token;
      if (!token) throw new Error("Authentication required");
      const params = new URLSearchParams({ limit: "1000" });
      if (backupSource !== "all") params.set("source", backupSource);
      if (backupStatus !== "all") params.set("status", backupStatus);
      const response = await fetch(`${apiBase()}/leads/backup-preview?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Unable to load lead backup preview");
      setBackupPreview(payload as BackupPreview);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load lead backup preview");
    } finally {
      setPreviewBusy(false);
    }
  }

  if (role && role === "sales") {
    return (
      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-2xl font-bold">Exports</h1>
        <p className="mt-3 text-sm text-slate-600">
          Only an administrator or manager can generate lead exports.
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <header className="rounded-3xl bg-slate-950 p-7 text-white">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Sales handoff</p>
        <h1 className="mt-3 text-3xl font-bold">Lead exports</h1>
        <p className="mt-3 text-sm text-slate-300">
          Download approved sales handoff rows or a full backup of lead, score, draft, send, and reply history.
        </p>
      </header>
      {error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-bold text-slate-950">Complete lead backup</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          CSV backup with lead fields, latest score, review reasons, draft sequence content, draft statuses, replies, and inferred send counts.
        </p>
        <div className="mt-5 grid gap-4 md:grid-cols-[1fr_1fr_auto]">
          <label className="text-sm font-bold text-slate-700">
            Source
            <input value={backupSource} onChange={(event) => setBackupSource(event.target.value || "all")} className="mt-1.5 w-full rounded-xl border border-slate-300 px-3 py-2 font-normal text-slate-950" />
          </label>
          <label className="text-sm font-bold text-slate-700">
            Status
            <select value={backupStatus} onChange={(event) => setBackupStatus(event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 font-normal text-slate-950">
              <option value="all">all</option>
              <option value="review">review</option>
              <option value="qualified">qualified</option>
              <option value="disqualified">disqualified</option>
              <option value="nurture">nurture</option>
              <option value="archived">archived</option>
            </select>
          </label>
          <div className="flex flex-wrap gap-2 self-end">
            <button type="button" disabled={previewBusy || loading} onClick={() => void loadBackupPreview()} className="rounded-xl border border-teal-300 px-4 py-2 text-sm font-bold text-teal-800 disabled:opacity-50">
              {previewBusy ? "Loading..." : "Load backup preview"}
            </button>
            <button type="button" disabled={backupBusy || loading} onClick={() => void downloadLeadBackup()} className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">
              {backupBusy ? "Preparing..." : "Download lead backup CSV"}
            </button>
          </div>
        </div>
        {backupPreview && <div className="mt-6 space-y-4">
          <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-5">
            <p className="rounded-xl bg-slate-50 p-3"><span className="font-bold">{backupPreview.total}</span> leads</p>
            <p className="rounded-xl bg-slate-50 p-3"><span className="font-bold">{previewTotals.drafts}</span> drafts</p>
            <p className="rounded-xl bg-slate-50 p-3"><span className="font-bold">{previewTotals.approved}</span> approved</p>
            <p className="rounded-xl bg-slate-50 p-3"><span className="font-bold">{previewTotals.rejected}</span> rejected</p>
            <p className="rounded-xl bg-slate-50 p-3"><span className="font-bold">{previewTotals.replies}</span> replies</p>
          </div>
          <p className="text-xs font-medium text-slate-500">Generated at {backupPreview.generated_at} | Showing {backupPreview.leads.length} of limit {backupPreview.limit}</p>
          <div className="overflow-x-auto rounded-2xl border border-slate-200">
            <table className="w-full min-w-[1100px] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="p-3">Lead</th>
                  <th className="p-3">Company</th>
                  <th className="p-3">Source</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">ICP</th>
                  <th className="p-3">Review reasons</th>
                  <th className="p-3">Drafts</th>
                  <th className="p-3">Approved</th>
                  <th className="p-3">Rejected</th>
                  <th className="p-3">Replied</th>
                  <th className="p-3">Email steps</th>
                  <th className="p-3">LinkedIn steps</th>
                </tr>
              </thead>
              <tbody>
                {backupPreview.leads.map((lead) => (
                  <tr key={lead.lead_id} className="border-t border-slate-100 align-top">
                    <td className="p-3"><p className="font-bold text-slate-900">{lead.person_name || "Unknown"}</p><p className="mt-1 text-xs text-slate-500">{lead.title || "Title unknown"}</p><p className="mt-1 text-xs text-slate-500">{lead.email}</p></td>
                    <td className="p-3"><p className="font-bold text-slate-900">{lead.company_name || "Unknown"}</p><p className="mt-1 text-xs text-slate-500">{lead.industry || "Industry unknown"}</p><p className="mt-1 text-xs text-slate-500">{lead.country}</p></td>
                    <td className="p-3"><p>{lead.lead_source || "unknown"}</p><p className="mt-1 text-xs text-slate-500">{lead.source_id}</p></td>
                    <td className="p-3"><span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold capitalize text-slate-700">{lead.status || "unknown"}</span></td>
                    <td className="p-3"><p className="font-black">{lead.icp_score || "NA"}</p><p className="mt-1 text-xs text-slate-500">{lead.disposition}</p></td>
                    <td className="max-w-xs p-3 text-xs leading-5 text-slate-600">{(lead.review_reasons.length ? lead.review_reasons : lead.hard_stops).slice(0, 2).join("; ") || "None recorded"}</td>
                    <td className="p-3 font-bold">{lead.total_drafts}</td>
                    <td className="p-3 font-bold">{lead.approved_count}</td>
                    <td className="p-3 font-bold">{lead.rejected_count}</td>
                    <td className="p-3">{lead.lead_replied ? <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-800">Yes</span> : <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-600">No</span>}</td>
                    <td className="p-3 text-xs">1: {lead.email_step_1_status || "-"} | 2: {lead.email_step_2_status || "-"} | 3: {lead.email_step_3_status || "-"} | 4: {lead.email_step_4_status || "-"}</td>
                    <td className="p-3 text-xs">1: {lead.linkedin_step_1_status || "-"} | 2: {lead.linkedin_step_2_status || "-"} | 3: {lead.linkedin_step_3_status || "-"} | 4: {lead.linkedin_step_4_status || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>}
      </div>
      {role === "admin" && <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-bold text-slate-950">Approved sales handoff</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Use Complete Lead Backup for full lead, draft, score, reply, and follow-up history.
        </p>
        {handoffUnavailable && (
          <p className="mt-4 rounded-xl bg-amber-50 p-4 text-sm font-medium text-amber-900">
            Approved sales handoff is not configured yet.
          </p>
        )}
        <p className="text-4xl font-bold">{loading ? "…" : leads.length}</p>
        <p className="mt-1 text-sm text-slate-500">Sales-ready leads</p>
        <button type="button" disabled={loading || !leads.length} onClick={download} className="mt-5 rounded-xl bg-teal-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">
          Download CSV
        </button>
      </div>}
    </section>
  );
}
