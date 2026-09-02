"use client";

import { useCallback, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type Lead = {
  id: string;
  person_name: string | null;
  company_name: string | null;
  title: string | null;
  email: string | null;
  linkedin_url: string | null;
  status: string;
  created_at: string;
};

const statusColors: Record<string, string> = {
  review: "bg-amber-50 text-amber-800",
  qualified: "bg-teal-50 text-teal-800",
  disqualified: "bg-red-50 text-red-800",
  new: "bg-slate-100 text-slate-700",
};

export function ReviewWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!supabase) return;
    setLoading(true);
    const { data, error: queryError } = await supabase
      .from("leads")
      .select("id,person_name,company_name,title,email,linkedin_url,status,created_at")
      .in("status", ["review", "qualified", "new"]) 
      .order("created_at", { ascending: false })
      .limit(100);

    if (queryError) {
      setError(queryError.message);
    } else {
      setLeads((data ?? []) as Lead[]);
      setError("");
    }
    setLoading(false);
  }, [supabase]);

  const approve = useCallback(
    async (leadId: string) => {
      if (!supabase) return;
      setMessage("");
      const { error: approveError } = await supabase.rpc("approve_lead_for_sales", { target_id: leadId });
      if (approveError) {
        setError(approveError.message);
        return;
      }
      setMessage("Lead approved to sales.");
      await load();
    },
    [load, supabase],
  );

  const refresh = useCallback(() => {
    void load();
  }, [load]);

  return (
    <section className="space-y-6">
      <header className="rounded-3xl bg-slate-950 p-7 text-white">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Review queue</p>
        <h1 className="mt-3 text-3xl font-bold">Approval and outreach review</h1>
        <p className="mt-3 text-sm text-slate-300">
          Qualified leads surface here for evidence review and sales approval before any handoff.
        </p>
      </header>

      {error && <p className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      {message && <p className="rounded-xl bg-teal-50 p-4 text-sm text-teal-800">{message}</p>}

      <div className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-lg font-bold text-slate-950">Lead review list</h2>
          <button
            type="button"
            onClick={refresh}
            className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700"
          >
            Refresh
          </button>
        </div>

        {loading ? (
          <p className="p-4 text-sm text-slate-500">Loading review queue...</p>
        ) : leads.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">No review-ready leads yet.</p>
        ) : (
          <div className="space-y-3">
            {leads.map((lead) => (
              <article key={lead.id} className="rounded-2xl border border-slate-200 p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <p className="text-lg font-bold text-slate-950">{lead.person_name || "Research pending"}</p>
                    <p className="text-sm text-slate-600">{lead.company_name || "Company unknown"} · {lead.title || "Title unknown"}</p>
                  </div>
                  <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-bold capitalize ${statusColors[lead.status] || "bg-slate-100 text-slate-700"}`}>
                    {lead.status}
                  </span>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
                  {lead.email && <span>{lead.email}</span>}
                  {lead.linkedin_url && (
                    <a href={lead.linkedin_url} target="_blank" rel="noreferrer" className="font-bold text-teal-700">
                      LinkedIn profile ↗
                    </a>
                  )}
                </div>

                <div className="mt-4 flex justify-end">
                  <button
                    type="button"
                    onClick={() => void approve(lead.id)}
                    className="rounded-xl bg-teal-600 px-4 py-2 text-sm font-bold text-white"
                  >
                    Approve to sales
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
