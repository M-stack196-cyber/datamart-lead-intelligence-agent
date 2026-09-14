"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";
import { CollectionSearchBar } from "@/components/collection-search-bar";
import { OutreachDraftPanel, type OutreachDraft } from "@/components/outreach-draft-panel";

type Role = "admin" | "manager" | "sales";

type Score = {
  score: number;
  disposition: string;
  tier: string | null;
  persona: string | null;
  hard_stops: string[];
  review_reasons: string[];
  evaluations: Array<{
    rule_key?: string;
    label?: string;
    outcome?: string;
    points_awarded?: number;
    points_available?: number;
    explanation?: string;
  }>;
  intent_score: number;
  intent_level: string;
  intent_reasons: string[];
  scored_at: string;
};

type DraftGroups = {
  email: Record<"step_1" | "step_2" | "step_3" | "step_4", OutreachDraft | null>;
  linkedin: Record<"step_1" | "step_2" | "step_3" | "step_4", OutreachDraft | null>;
};

type Lead = {
  id: string;
  person_name: string | null;
  title: string | null;
  company_name: string | null;
  email: string | null;
  phone: string | null;
  linkedin_url: string | null;
  company_url: string | null;
  country: string | null;
  industry: string | null;
  employee_count: number | null;
  lead_source: string;
  source_id: string | null;
  status: string;
  created_at: string | null;
  source_captured_at: string | null;
  latest_score: Score | null;
  has_replies: boolean;
  outreach_drafts: DraftGroups;
};

const stepKeys = ["step_1", "step_2", "step_3", "step_4"] as const;

function apiBase() {
  return process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === "production" ? "/api" : "http://localhost:8000");
}

function draftList(groups: DraftGroups): OutreachDraft[] {
  return stepKeys
    .flatMap((step) => [groups.email[step], groups.linkedin[step]])
    .filter(Boolean) as OutreachDraft[];
}

function firstDomain(url: string | null) {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0] || url;
  }
}

function latestDraftForChannel(drafts: OutreachDraft[], channel: "email" | "linkedin") {
  return drafts
    .filter((draft) => draft.channel === channel)
    .sort((first, second) => second.sequence_step - first.sequence_step)[0];
}

function followupMessage(lead: Lead, drafts: OutreachDraft[], channel: "email" | "linkedin") {
  if (lead.has_replies) return "Lead replied - follow-up stopped";
  const latest = latestDraftForChannel(drafts, channel);
  if (!latest) return "Create the primary draft before follow-ups";
  if (latest.sequence_step >= 4 && latest.status === "approved") return "Sequence complete";
  if (latest.status !== "approved") return "Review and send previous step before creating next follow-up";
  return `Create next ${channel} follow-up draft`;
}

export function ReviewWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [role, setRole] = useState<Role | null>(null);
  const [source, setSource] = useState("apollo_csv");
  const [status, setStatus] = useState("review");
  const [limit, setLimit] = useState(50);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const totals = useMemo(() => {
    const draftCount = leads.reduce((count, lead) => count + draftList(lead.outreach_drafts).length, 0);
    const reviewDrafts = leads.reduce(
      (count, lead) =>
        count + draftList(lead.outreach_drafts).filter((draft) => draft.status === "draft").length,
      0,
    );
    return { draftCount, reviewDrafts };
  }, [leads]);

  const visibleLeads = useMemo(() => {
    const search = searchTerm.trim().toLocaleLowerCase();
    if (!search) return leads;
    return leads.filter((lead) => {
      const score = lead.latest_score;
      const drafts = draftList(lead.outreach_drafts);
      return [
        lead.person_name,
        lead.title,
        lead.company_name,
        lead.email,
        lead.phone,
        lead.linkedin_url,
        lead.company_url,
        lead.country,
        lead.industry,
        lead.lead_source,
        lead.source_id,
        lead.status,
        score?.disposition,
        score?.tier,
        score?.persona,
        score?.intent_level,
        ...(score?.review_reasons ?? []),
        ...(score?.hard_stops ?? []),
        ...drafts.flatMap((draft) => [
          draft.channel,
          draft.status,
          draft.subject,
          draft.body,
          draft.review_notes,
          String(draft.sequence_step),
        ]),
      ].some((value) => String(value ?? "").toLocaleLowerCase().includes(search));
    });
  }, [leads, searchTerm]);

  const load = useCallback(async () => {
    if (!supabase) return;
    setLoading(true);
    setError("");
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const token = sessionData.session?.access_token;
      if (!token) throw new Error("Authentication required");

      const { data: userData } = await supabase.auth.getUser();
      if (userData.user) {
        const profile = await supabase.from("profiles").select("role").eq("id", userData.user.id).single();
        setRole((profile.data?.role as Role | undefined) ?? null);
      }

      const params = new URLSearchParams({
        source,
        status,
        limit: String(limit),
        include_drafts: "true",
      });
      const response = await fetch(`${apiBase()}/leads/review-workspace?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Unable to load review workspace");
      setLeads((payload.leads ?? []) as Lead[]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load review workspace");
    } finally {
      setLoading(false);
    }
  }, [limit, source, status, supabase]);

  const createNextFollowup = useCallback(async (leadId: string, channel: "email" | "linkedin") => {
    if (!supabase) return;
    setError("");
    setMessage("");
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const token = sessionData.session?.access_token;
      if (!token) throw new Error("Authentication required");
      const response = await fetch(`${apiBase()}/leads/${leadId}/outreach/next-followup-draft`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ channel, source }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Unable to create next follow-up draft");
      const result = payload.results?.[channel];
      if (result?.reason === "lead_replied") {
        setMessage("Lead replied - follow-up stopped.");
      } else if (result?.reason === "previous_step_not_sent_or_approved") {
        setMessage("Review and send previous step before creating next follow-up.");
      } else if (result?.reason === "existing_draft") {
        setMessage("The next follow-up draft already exists.");
      } else if (result?.reason === "sequence_complete") {
        setMessage("Sequence complete.");
      } else {
        setMessage("Next follow-up draft created for review.");
      }
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create next follow-up draft");
    }
  }, [load, source, supabase]);

  useEffect(() => {
    const task = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(task);
  }, [load]);

  return (
    <section className="space-y-6">
      <header className="rounded-3xl bg-slate-950 p-7 text-white">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Lead review</p>
        <h1 className="mt-3 text-3xl font-bold">Imported leads and draft sequence</h1>
        <p className="mt-3 max-w-3xl text-sm text-slate-300">
          Review generic lead-source imports, ICP context, and draft-only email and LinkedIn sequence steps before any sales action.
        </p>
        <p className="mt-3 text-xs font-bold uppercase tracking-wide text-slate-400">Role: {role ?? "loading"}</p>
      </header>

      {error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      {message && <p role="status" className="rounded-xl bg-teal-50 p-4 text-sm text-teal-800">{message}</p>}

      <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid gap-4 lg:grid-cols-[minmax(12rem,1fr)_minmax(10rem,0.5fr)_minmax(8rem,0.35fr)_auto]">
          <label className="text-sm font-bold text-slate-700">
            Source
            <input
              value={source}
              onChange={(event) => setSource(event.target.value)}
              className="mt-1.5 w-full rounded-xl border border-slate-300 px-3 py-2 font-normal text-slate-950"
            />
          </label>
          <label className="text-sm font-bold text-slate-700">
            Status
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              className="mt-1.5 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 font-normal text-slate-950"
            >
              <option value="review">review</option>
              <option value="qualified">qualified</option>
              <option value="disqualified">disqualified</option>
              <option value="nurture">nurture</option>
            </select>
          </label>
          <label className="text-sm font-bold text-slate-700">
            Limit
            <input
              type="number"
              min={1}
              max={200}
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value))}
              className="mt-1.5 w-full rounded-xl border border-slate-300 px-3 py-2 font-normal text-slate-950"
            />
          </label>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="self-end rounded-xl bg-teal-600 px-4 py-2 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            Refresh
          </button>
        </div>
        <div className="mt-4 grid gap-3 text-sm md:grid-cols-3">
          <p className="rounded-xl bg-slate-50 p-3"><span className="font-bold">{leads.length}</span> leads loaded</p>
          <p className="rounded-xl bg-slate-50 p-3"><span className="font-bold">{totals.draftCount}</span> stored drafts</p>
          <p className="rounded-xl bg-slate-50 p-3"><span className="font-bold">{totals.reviewDrafts}</span> drafts pending review</p>
        </div>
      </div>
      {!loading && leads.length > 0 && (
        <CollectionSearchBar
          label="Search review leads"
          placeholder="Search by person, company, email, source, ICP reason, draft text, or step status"
          value={searchTerm}
          onChange={setSearchTerm}
          shownCount={visibleLeads.length}
          totalCount={leads.length}
          noun="review leads"
        />
      )}

      {loading ? (
        <p className="rounded-3xl bg-white p-8 text-sm text-slate-500">Loading review workspace...</p>
      ) : leads.length === 0 ? (
        <p className="rounded-3xl bg-white p-8 text-sm text-slate-500">No matching leads found.</p>
      ) : visibleLeads.length === 0 ? (
        <p className="rounded-3xl bg-white p-8 text-sm text-slate-500">No review leads match the current search.</p>
      ) : (
        <div className="space-y-5">
          {visibleLeads.map((lead) => {
            const score = lead.latest_score;
            const drafts = draftList(lead.outreach_drafts);
            const reasons = score?.review_reasons?.length
              ? score.review_reasons
              : score?.hard_stops?.length
                ? score.hard_stops
                : ["No review reason recorded."];
            const domain = firstDomain(lead.company_url);

            return (
              <article key={lead.id} className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wide text-teal-700">
                      {lead.lead_source} | {lead.status}
                    </p>
                    <h2 className="mt-2 text-2xl font-bold text-slate-950">{lead.person_name || "Contact unknown"}</h2>
                    <p className="mt-1 text-sm text-slate-600">
                      {lead.title || "Title unknown"} | {lead.company_name || "Company unknown"}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500">
                      {lead.email && <span>{lead.email}</span>}
                      {lead.phone && <span>{lead.phone}</span>}
                      {lead.linkedin_url && <a className="font-bold text-teal-700" href={lead.linkedin_url} target="_blank" rel="noreferrer">LinkedIn</a>}
                      {domain && <a className="font-bold text-teal-700" href={lead.company_url ?? "#"} target="_blank" rel="noreferrer">{domain}</a>}
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-right sm:min-w-72">
                    <div className="rounded-2xl bg-slate-50 p-4">
                      <p className="text-xs font-bold uppercase text-slate-500">ICP</p>
                      <p className="mt-1 text-2xl font-black text-slate-950">{score ? `${score.score}/100` : "Unknown"}</p>
                    </div>
                    <div className="rounded-2xl bg-slate-50 p-4">
                      <p className="text-xs font-bold uppercase text-slate-500">Drafts</p>
                      <p className="mt-1 text-2xl font-black text-slate-950">{drafts.length}/8</p>
                    </div>
                  </div>
                </div>

                <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_1fr_1fr]">
                  <div className="rounded-2xl bg-slate-50 p-4">
                    <p className="text-xs font-bold uppercase text-slate-500">Company</p>
                    <p className="mt-2 text-sm leading-6 text-slate-700">
                      {lead.industry || "Industry unknown"} | {lead.country || "Country unknown"} | {lead.employee_count ?? "Unknown"} employees
                    </p>
                  </div>
                  <div className="rounded-2xl bg-slate-50 p-4">
                    <p className="text-xs font-bold uppercase text-slate-500">Score context</p>
                    <p className="mt-2 text-sm leading-6 text-slate-700">
                      {score?.disposition || "No disposition"} | {score?.tier || "No tier"} | {score?.persona || "No persona"}
                    </p>
                  </div>
                  <div className="rounded-2xl bg-amber-50 p-4">
                    <p className="text-xs font-bold uppercase text-amber-800">Review reasons</p>
                    <ul className="mt-2 space-y-1 text-sm leading-6 text-amber-950">
                      {reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}
                    </ul>
                  </div>
                </div>

                <div className="mt-5 grid gap-3 md:grid-cols-2">
                  {(["email", "linkedin"] as const).map((channel) => {
                    const latest = latestDraftForChannel(drafts, channel);
                    const canCreate = Boolean(latest && latest.status === "approved" && latest.sequence_step < 4 && !lead.has_replies);
                    return (
                      <div key={channel} className="rounded-2xl border border-slate-200 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <p className="text-xs font-bold uppercase text-slate-500">{channel}</p>
                            <p className="mt-2 text-sm text-slate-700">{followupMessage(lead, drafts, channel)}</p>
                          </div>
                          {canCreate && (
                            <button
                              type="button"
                              onClick={() => void createNextFollowup(lead.id, channel)}
                              className="rounded-lg border border-teal-300 px-3 py-2 text-xs font-bold text-teal-800"
                            >
                              Create next follow-up draft
                            </button>
                          )}
                        </div>
                        {latest && (
                          <p className="mt-2 text-xs text-slate-500">
                            Latest: step {latest.sequence_step}, {latest.status}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>

                <button
                  type="button"
                  onClick={() => setExpanded((current) => ({ ...current, [lead.id]: !current[lead.id] }))}
                  className="mt-5 rounded-xl border border-slate-300 px-4 py-2 text-sm font-bold text-slate-800"
                >
                  {expanded[lead.id] ? "Hide draft sequence" : "Review draft sequence"}
                </button>

                {expanded[lead.id] && (
                  <OutreachDraftPanel
                    leadId={lead.id}
                    role={role}
                    drafts={drafts}
                    evidence={[]}
                    recipient={lead.email}
                    salesApproved={false}
                    onChanged={async () => {
                      setMessage("Draft status updated.");
                      await load();
                    }}
                    allowGenerate={false}
                    allowSendActions={false}
                    allowManualSend
                  />
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
