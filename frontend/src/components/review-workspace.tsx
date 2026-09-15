"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";
import { authenticatedFetch } from "@/lib/api";
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
  archived?: OutreachDraft[];
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
const activeDraftStatuses = new Set(["draft", "needs_edit", "approved", "manual_sent", "system_sent", "sent"]);
const sentLikeDraftStatuses = new Set(["approved", "manual_sent", "system_sent", "sent"]);
type DraftChannelRequest = "email" | "linkedin" | "both";
type DraftCreationResult = { reason?: string };

function draftList(groups: DraftGroups): OutreachDraft[] {
  return stepKeys
    .flatMap((step) => [groups.email[step], groups.linkedin[step]])
    .filter(Boolean) as OutreachDraft[];
}

function archivedDraftList(groups: DraftGroups): OutreachDraft[] {
  return groups.archived ?? [];
}

function firstDomain(url: string | null) {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0] || url;
  }
}

function isActiveDraft(draft: OutreachDraft) {
  return activeDraftStatuses.has(draft.status);
}

function isSentLikeDraft(draft: OutreachDraft) {
  return sentLikeDraftStatuses.has(draft.status);
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function latestActiveDraftForChannel(drafts: OutreachDraft[], channel: "email" | "linkedin") {
  return drafts
    .filter((draft) => draft.channel === channel && isActiveDraft(draft))
    .sort((first, second) => second.sequence_step - first.sequence_step)[0];
}

function followupMessage(lead: Lead, drafts: OutreachDraft[], channel: "email" | "linkedin") {
  if (lead.has_replies) return "Lead replied — follow-up stopped";
  const latest = latestActiveDraftForChannel(drafts, channel);
  if (!latest) return `No ${channel} draft exists yet.`;
  if (latest.sequence_step >= 4 && isSentLikeDraft(latest)) return "Sequence complete";
  if (!isSentLikeDraft(latest)) return `Review/send Step ${latest.sequence_step} before creating next follow-up`;
  if (latest.followup_stopped_at) return "Follow-up stopped";
  const decisionAt = latest.next_followup_decision_at ? new Date(latest.next_followup_decision_at) : null;
  if (!decisionAt || Number.isNaN(decisionAt.getTime())) return "Reply wait period not set";
  if (decisionAt.getTime() > Date.now()) return `Waiting for reply until ${formatDateTime(latest.next_followup_decision_at)}`;
  return "No reply yet — team decision needed";
}

function canCreateNextFollowup(lead: Lead, drafts: OutreachDraft[], channel: "email" | "linkedin") {
  const latest = latestActiveDraftForChannel(drafts, channel);
  if (!latest || !isSentLikeDraft(latest) || latest.sequence_step >= 4 || lead.has_replies || latest.followup_stopped_at) {
    return false;
  }
  const decisionAt = latest.next_followup_decision_at ? new Date(latest.next_followup_decision_at) : null;
  return Boolean(decisionAt && !Number.isNaN(decisionAt.getTime()) && decisionAt.getTime() <= Date.now());
}

function isDraftCreationResult(value: DraftCreationResult | undefined): value is DraftCreationResult {
  return Boolean(value);
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
  const [replyTrackingConnected, setReplyTrackingConnected] = useState<boolean | null>(null);

  const totals = useMemo(() => {
    const activeDraftCount = leads.reduce((count, lead) => count + draftList(lead.outreach_drafts).length, 0);
    const archivedDraftCount = leads.reduce((count, lead) => count + archivedDraftList(lead.outreach_drafts).length, 0);
    const reviewDrafts = leads.reduce(
      (count, lead) =>
        count + draftList(lead.outreach_drafts).filter((draft) => draft.status === "draft").length,
      0,
    );
    return { activeDraftCount, archivedDraftCount, reviewDrafts };
  }, [leads]);

  const visibleLeads = useMemo(() => {
    const search = searchTerm.trim().toLocaleLowerCase();
    if (!search) return leads;
    return leads.filter((lead) => {
      const score = lead.latest_score;
      const drafts = [...draftList(lead.outreach_drafts), ...archivedDraftList(lead.outreach_drafts)];
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

  useEffect(() => {
    let active = true;
    fetch((process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === "production" ? "/api" : "http://localhost:8000")) + "/health")
      .then((response) => response.json())
      .then((payload) => {
        if (active) setReplyTrackingConnected(Boolean(payload.integrations_configured?.reply_tracking));
      })
      .catch(() => {
        if (active) setReplyTrackingConnected(false);
      });
    return () => { active = false; };
  }, []);

  const load = useCallback(async () => {
    if (!supabase) return;
    setLoading(true);
    setError("");
    try {
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
      const response = await authenticatedFetch(supabase, `/leads/review-workspace?${params.toString()}`);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Unable to load review workspace");
      setLeads((payload.leads ?? []) as Lead[]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load review workspace");
    } finally {
      setLoading(false);
    }
  }, [limit, source, status, supabase]);

  const createPrimaryDraft = useCallback(async (leadId: string, channel: DraftChannelRequest) => {
    if (!supabase) return;
    setError("");
    setMessage("");
    try {
      const response = await authenticatedFetch(supabase, `/leads/${leadId}/outreach/primary-draft`, {
        method: "POST",
        body: JSON.stringify({ channel, source }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Unable to create primary outreach draft");
      const results = Object.values(payload.results ?? {}) as Array<{ reason?: string }>;
      if (results.some((result) => result.reason === "reactivated_existing_terminal_draft")) {
        setMessage("Primary draft reactivated for review.");
      } else if (results.every((result) => result.reason === "existing_draft")) {
        setMessage("The requested primary draft already exists.");
      } else {
        setMessage("Primary draft created for review.");
      }
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create primary outreach draft");
    }
  }, [load, source, supabase]);

  const createNextFollowup = useCallback(async (leadId: string, channel: DraftChannelRequest) => {
    if (!supabase) return;
    setError("");
    setMessage("");
    try {
      const response = await authenticatedFetch(supabase, `/leads/${leadId}/outreach/next-followup-draft`, {
        method: "POST",
        body: JSON.stringify({ channel, source }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Unable to create next follow-up draft");
      const results = channel === "both"
        ? Object.values(payload.results ?? {}) as Array<{ reason?: string }>
        : ([payload.results?.[channel] as DraftCreationResult | undefined]).filter(isDraftCreationResult);
      if (results.some((result) => result.reason === "lead_replied")) {
        setMessage("Lead replied - follow-up stopped.");
      } else if (results.some((result) => result.reason === "previous_step_not_sent_or_approved")) {
        setMessage("Review and send previous step before creating next follow-up.");
      } else if (results.every((result) => result.reason === "existing_draft")) {
        setMessage("The next follow-up draft already exists.");
      } else if (results.some((result) => result.reason === "reactivated_existing_terminal_draft")) {
        setMessage("Next follow-up draft reactivated for review.");
      } else if (results.every((result) => result.reason === "sequence_complete")) {
        setMessage("Sequence complete.");
      } else {
        setMessage("Next follow-up draft created for review.");
      }
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create next follow-up draft");
    }
  }, [load, source, supabase]);

  const waitMoreDays = useCallback(async (draftId: string, days: number) => {
    if (!supabase) return;
    setError("");
    setMessage("");
    try {
      const response = await authenticatedFetch(supabase, `/outreach-drafts/${draftId}/reply-wait`, {
        method: "PATCH",
        body: JSON.stringify({ reply_wait_days: days }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Unable to update reply wait");
      setMessage(`Reply wait extended by ${days} days.`);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to update reply wait");
    }
  }, [load, supabase]);

  const stopFollowup = useCallback(async (draftId: string) => {
    if (!supabase) return;
    setError("");
    setMessage("");
    try {
      const response = await authenticatedFetch(supabase, `/outreach-drafts/${draftId}/stop-followup`, {
        method: "PATCH",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Unable to stop follow-up");
      setMessage("Follow-up stopped for this draft.");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to stop follow-up");
    }
  }, [load, supabase]);

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
      {replyTrackingConnected === false && (
        <p role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm font-semibold text-amber-900">
          Reply tracking integration not connected.
        </p>
      )}

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
          <p className="rounded-xl bg-slate-50 p-3"><span className="font-bold">{totals.activeDraftCount}</span> active drafts</p>
          <p className="rounded-xl bg-slate-50 p-3"><span className="font-bold">{totals.archivedDraftCount}</span> archived drafts</p>
          <p className="rounded-xl bg-slate-50 p-3"><span className="font-bold">{totals.reviewDrafts}</span> pending review</p>
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
            const archivedDrafts = archivedDraftList(lead.outreach_drafts);
            const hasEmailPrimary = Boolean(lead.outreach_drafts.email.step_1);
            const hasLinkedinPrimary = Boolean(lead.outreach_drafts.linkedin.step_1);
            const emailFollowupReady = canCreateNextFollowup(lead, drafts, "email");
            const linkedinFollowupReady = canCreateNextFollowup(lead, drafts, "linkedin");
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
                      <p className="mt-1 text-2xl font-black text-slate-950">{drafts.length}</p>
                      <p className="mt-1 text-xs text-slate-500">{archivedDrafts.length} archived</p>
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

                {(!hasEmailPrimary || !hasLinkedinPrimary) && (
                  <div className="mt-5 rounded-2xl border border-teal-100 bg-teal-50 p-4">
                    <p className="text-sm font-bold text-teal-950">
                      {!hasEmailPrimary && !hasLinkedinPrimary
                        ? "No outreach draft exists yet. Create a draft only when the team is ready."
                        : "Create the missing primary draft only when the team is ready."}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {!hasEmailPrimary && (
                        <button type="button" onClick={() => void createPrimaryDraft(lead.id, "email")} className="rounded-lg border border-teal-300 bg-white px-3 py-2 text-xs font-bold text-teal-800">
                          Create Email draft
                        </button>
                      )}
                      {!hasLinkedinPrimary && (
                        <button type="button" onClick={() => void createPrimaryDraft(lead.id, "linkedin")} className="rounded-lg border border-teal-300 bg-white px-3 py-2 text-xs font-bold text-teal-800">
                          Create LinkedIn draft
                        </button>
                      )}
                      {!hasEmailPrimary && !hasLinkedinPrimary && (
                        <button type="button" onClick={() => void createPrimaryDraft(lead.id, "both")} className="rounded-lg bg-teal-700 px-3 py-2 text-xs font-bold text-white">
                          Create both drafts
                        </button>
                      )}
                    </div>
                  </div>
                )}

                <div className="mt-5 grid gap-3 md:grid-cols-2">
                  {(["email", "linkedin"] as const).map((channel) => {
                    const latest = latestActiveDraftForChannel(drafts, channel);
                    const canCreate = canCreateNextFollowup(lead, drafts, channel);
                    return (
                      <div key={channel} className="rounded-2xl border border-slate-200 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <p className="text-xs font-bold uppercase text-slate-500">{channel}</p>
                            <p className="mt-2 text-sm text-slate-700">{followupMessage(lead, drafts, channel)}</p>
                          </div>
                          {canCreate && (
                            <div className="flex flex-wrap gap-2">
                              <button
                                type="button"
                                onClick={() => void createNextFollowup(lead.id, channel)}
                                className="rounded-lg border border-teal-300 px-3 py-2 text-xs font-bold text-teal-800"
                              >
                                Create next {channel === "email" ? "Email" : "LinkedIn"} follow-up draft
                              </button>
                              {latest && (
                                <>
                                  <button
                                    type="button"
                                    onClick={() => void waitMoreDays(latest.id, 4)}
                                    className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold text-slate-800"
                                  >
                                    Wait more days
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => void stopFollowup(latest.id)}
                                    className="rounded-lg border border-red-200 px-3 py-2 text-xs font-bold text-red-800"
                                  >
                                    Stop follow-up
                                  </button>
                                </>
                              )}
                            </div>
                          )}
                        </div>
                        {latest && (
                          <div className="mt-2 space-y-1 text-xs text-slate-500">
                            <p>Latest active: step {latest.sequence_step}, {latest.status}</p>
                            {(latest.manual_sent_at || latest.sent_at) && <p>Sent: {formatDateTime(latest.manual_sent_at || latest.sent_at)}</p>}
                            {latest.next_followup_decision_at && <p>Decision time: {formatDateTime(latest.next_followup_decision_at)}</p>}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {emailFollowupReady && linkedinFollowupReady && (
                  <button
                    type="button"
                    onClick={() => void createNextFollowup(lead.id, "both")}
                    className="mt-3 rounded-lg bg-slate-950 px-3 py-2 text-xs font-bold text-white"
                  >
                    Create both next follow-up drafts
                  </button>
                )}

                <button
                  type="button"
                  onClick={() => setExpanded((current) => ({ ...current, [lead.id]: !current[lead.id] }))}
                  className="mt-5 rounded-xl border border-slate-300 px-4 py-2 text-sm font-bold text-slate-800"
                >
                  {expanded[lead.id] ? "Hide draft sequence" : "Review draft sequence"}
                </button>

                {expanded[lead.id] && (
                  <>
                    <p className="mt-4 rounded-xl bg-slate-50 p-3 text-xs font-semibold text-slate-600">
                      Only active drafts are shown here. Archived/rejected drafts are kept for history.
                    </p>
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
                    {archivedDrafts.length > 0 && (
                      <details className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                        <summary className="cursor-pointer text-sm font-bold text-slate-800">
                          Archived / inactive drafts ({archivedDrafts.length})
                        </summary>
                        <div className="mt-4 space-y-3">
                          {archivedDrafts
                            .slice()
                            .sort((first, second) => first.sequence_step - second.sequence_step || first.channel.localeCompare(second.channel))
                            .map((draft) => (
                              <article key={draft.id} className="rounded-xl border border-slate-200 bg-white p-4">
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                  <p className="text-sm font-bold capitalize text-slate-900">{draft.channel} · step {draft.sequence_step}</p>
                                  <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold capitalize text-slate-600">{draft.status}</span>
                                </div>
                                {draft.subject && <p className="mt-3 text-sm font-semibold text-slate-800">{draft.subject}</p>}
                                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">{draft.body}</p>
                                {draft.review_notes && (
                                  <p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">Review notes: {draft.review_notes}</p>
                                )}
                              </article>
                            ))}
                        </div>
                      </details>
                    )}
                  </>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
