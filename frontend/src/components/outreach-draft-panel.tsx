"use client";

import { useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";
import { authenticatedFetch } from "@/lib/api";

export type OutreachDraft = {
  id: string;
  channel: "email" | "linkedin";
  subject: string | null;
  body: string;
  status: "draft" | "needs_edit" | "approved" | "rejected" | "archived" | "cancelled" | "manual_sent" | "system_sent" | "sent";
  sequence_step: number;
  evidence_ids: string[];
  created_by: string | null;
  reviewed_by: string | null;
  created_at?: string;
  reviewed_at: string | null;
  review_notes: string | null;
  updated_at: string;
  sent_at?: string | null;
  manual_sent_at?: string | null;
  reply_wait_days?: number | null;
  next_followup_decision_at?: string | null;
  followup_stopped_at?: string | null;
  followup_stop_reason?: string | null;
};

type EvidenceLink = { id: string; title: string; source_url: string };
type Props = {
  leadId: string;
  role: "admin" | "manager" | "sales" | null;
  drafts: OutreachDraft[];
  evidence: EvidenceLink[];
  recipient: string | null;
  salesApproved: boolean;
  onChanged: () => Promise<void>;
  allowGenerate?: boolean;
  allowSendActions?: boolean;
  allowManualSend?: boolean;
};

const sortedDrafts = (drafts: OutreachDraft[]) =>
  [...drafts].sort((first, second) => {
    if (first.sequence_step !== second.sequence_step) return first.sequence_step - second.sequence_step;
    return first.channel.localeCompare(second.channel);
  });

type ReplyWaitState = { preset: "" | "2" | "4" | "7" | "custom"; customDateTime: string };

function formatDateTime(value: string | null | undefined) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function draftSentTime(draft: OutreachDraft) {
  return draft.manual_sent_at || draft.sent_at || null;
}

function manualSendReplyWaitPayload(wait: ReplyWaitState | undefined) {
  if (!wait || !wait.preset) throw new Error("Choose when to check for a reply before marking sent.");
  if (wait.preset === "custom") {
    if (!wait.customDateTime) throw new Error("Choose a custom reply-check date and time.");
    return { next_followup_decision_at: new Date(wait.customDateTime).toISOString() };
  }
  return { reply_wait_days: Number(wait.preset) };
}

export function OutreachDraftPanel({ leadId, role, drafts, evidence, recipient, salesApproved, onChanged, allowGenerate = true, allowSendActions = true, allowManualSend = false }: Props) {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [edits, setEdits] = useState<Record<string, { subject: string; body: string }>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [replyWaits, setReplyWaits] = useState<Record<string, ReplyWaitState>>({});
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [gmailConfigured, setGmailConfigured] = useState<boolean | null>(null);
  const [confirmingDraft, setConfirmingDraft] = useState("");
  const canReview = role === "admin" || role === "manager";
  const canMarkManualSend = role === "admin" || role === "manager" || role === "sales";

  useEffect(() => {
    let active = true;
    fetch((process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === "production" ? "/api" : "http://localhost:8000")) + "/health")
      .then((response) => response.json())
      .then((payload) => {
        if (active) setGmailConfigured(Boolean(payload.integrations_configured?.gmail));
      })
      .catch(() => {
        if (active) setGmailConfigured(false);
      });
    return () => { active = false; };
  }, []);

  async function callBackend(path: string, body: object, method = "POST") {
    if (!supabase) throw new Error("Supabase is not configured");
    const response = await authenticatedFetch(supabase, path, {
      method,
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "Outreach action failed");
    return payload;
  }

  async function generate(channel: "email" | "linkedin") {
    setBusy("generate-" + channel);
    setError("");
    try {
      await callBackend("/outreach/drafts/generate", { lead_id: leadId, channel });
      setMessage(channel === "email" ? "Email draft generated for review." : "LinkedIn draft generated for review.");
      await onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to generate draft");
    } finally {
      setBusy("");
    }
  }

  async function save(draft: OutreachDraft) {
    if (!supabase || !canReview) return;
    const edit = edits[draft.id] || { subject: draft.subject || "", body: draft.body };
    setBusy(draft.id);
    setError("");
    const { error: actionError } = await supabase.rpc("update_outreach_draft", {
      target_draft_id: draft.id,
      next_subject: edit.subject,
      next_body: edit.body,
    });
    setBusy("");
    if (actionError) setError(actionError.message);
    else {
      setMessage("Draft edits saved and audited.");
      await onChanged();
    }
  }

  async function review(draft: OutreachDraft, action: "approve" | "reject" | "needs_edit") {
    const reviewNotes = notes[draft.id]?.trim();
    if (!reviewNotes) {
      setError("Review notes are required.");
      return;
    }
    setBusy(draft.id);
    setError("");
    try {
      await callBackend("/outreach-drafts/" + draft.id + "/review", {
        action,
        review_notes: reviewNotes,
      }, "PATCH");
      setMessage(action === "approve" ? "Draft approved." : action === "reject" ? "Draft rejected with review notes." : "Draft marked as needing edits.");
      await onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to review draft");
    } finally {
      setBusy("");
    }
  }

  async function markManuallySent(draft: OutreachDraft) {
    setBusy(draft.id);
    setError("");
    try {
      const waitPayload = manualSendReplyWaitPayload(replyWaits[draft.id]);
      await callBackend("/outreach-drafts/" + draft.id + "/manual-send", {
        review_notes: notes[draft.id]?.trim() || "Marked as manually sent outside the system.",
        ...waitPayload,
      }, "PATCH");
      setMessage("Draft marked as manually sent. No provider send was triggered.");
      await onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to mark draft as manually sent");
    } finally {
      setBusy("");
    }
  }

  async function copyLinkedIn(draft: OutreachDraft) {
    if (draft.status !== "approved" || draft.channel !== "linkedin") return;
    await navigator.clipboard.writeText(draft.body);
    setMessage("Approved LinkedIn message copied. Sending remains manual.");
  }

  async function sendEmail(draft: OutreachDraft) {
    if (draft.status !== "approved" || draft.channel !== "email") return;
    setBusy(draft.id);
    setError("");
    try {
      const result = await callBackend("/outreach/drafts/" + draft.id + "/send-email", { confirm: true });
      setMessage("Email sent with Gmail. Provider message ID: " + result.provider_message_id);
      setConfirmingDraft("");
      await onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to send email");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="mt-6 border-t border-slate-200 pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h3 className="font-bold text-slate-950">Outreach drafts</h3><p className="mt-1 text-xs text-slate-500">LinkedIn remains copy-only and manual.</p></div>
        {canReview && allowGenerate && <div className="flex gap-2"><button type="button" disabled={Boolean(busy)} onClick={() => void generate("email")} className="rounded-lg border border-teal-300 px-3 py-2 text-xs font-bold text-teal-800 disabled:opacity-40">Generate email</button><button type="button" disabled={Boolean(busy)} onClick={() => void generate("linkedin")} className="rounded-lg border border-teal-300 px-3 py-2 text-xs font-bold text-teal-800 disabled:opacity-40">Generate LinkedIn</button></div>}
      </div>
      {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-800">{error}</p>}
      {message && <p role="status" className="mt-3 rounded-lg bg-teal-50 p-3 text-xs text-teal-800">{message}</p>}
      <div className="mt-4 space-y-4">
        {drafts.length === 0 ? (
          <p className="text-sm text-slate-500">No outreach draft has been generated.</p>
        ) : sortedDrafts(drafts).map((draft) => {
          const edit = edits[draft.id] || { subject: draft.subject || "", body: draft.body };
          const usedEvidence = evidence.filter((item) => draft.evidence_ids.includes(item.id));
          const emailEnabled = draft.status === "approved" && draft.channel === "email" && gmailConfigured === true && salesApproved && Boolean(recipient);
          const sentTime = formatDateTime(draftSentTime(draft));
          const decisionTime = formatDateTime(draft.next_followup_decision_at);
          const wait = replyWaits[draft.id] ?? { preset: "", customDateTime: "" };
          const canManualSendDraft = allowManualSend && canMarkManualSend && !["rejected", "archived", "cancelled"].includes(draft.status);

          return (
            <article key={draft.id} className="rounded-2xl border border-slate-200 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-bold capitalize">{draft.channel} · step {draft.sequence_step}</p>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold capitalize text-slate-700">{draft.status}</span>
              </div>
              {sentTime && <p className="mt-2 text-xs font-semibold text-slate-500">Sent: {sentTime}</p>}
              {decisionTime && <p className="mt-1 text-xs font-semibold text-slate-500">Next follow-up decision: {decisionTime}</p>}
              {draft.channel === "email" && (
                <input
                  aria-label="Email subject"
                  value={edit.subject}
                  readOnly={!canReview || draft.status !== "draft"}
                  onChange={(event) => setEdits((current) => ({ ...current, [draft.id]: { ...edit, subject: event.target.value } }))}
                  className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm read-only:bg-slate-50"
                />
              )}
              <textarea
                aria-label={draft.channel + " draft body"}
                rows={9}
                value={edit.body}
                readOnly={!canReview || draft.status !== "draft"}
                onChange={(event) => setEdits((current) => ({ ...current, [draft.id]: { ...edit, body: event.target.value } }))}
                className="mt-3 w-full rounded-lg border border-slate-300 p-3 text-sm leading-6 read-only:bg-slate-50"
              />
              <div className="mt-3">
                <p className="text-xs font-bold uppercase text-slate-500">Evidence used</p>
                {usedEvidence.map((item) => (
                  <a key={item.id} href={item.source_url} target="_blank" rel="noreferrer" className="mt-1 block text-xs font-bold text-teal-700">{item.title} ↗</a>
                ))}
              </div>
              {draft.review_notes && <p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">Review notes: {draft.review_notes}</p>}
              {canReview && draft.status === "draft" && (
                <>
                  <input
                    aria-label="Draft review notes"
                    value={notes[draft.id] || ""}
                    onChange={(event) => setNotes((current) => ({ ...current, [draft.id]: event.target.value }))}
                    placeholder="Review notes required"
                    className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button type="button" disabled={busy === draft.id} onClick={() => void save(draft)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold">Save edits</button>
                    {role === "admin" && <button type="button" disabled={busy === draft.id} onClick={() => void review(draft, "approve")} className="rounded-lg bg-teal-600 px-3 py-2 text-xs font-bold text-white">Approve</button>}
                    <button type="button" disabled={busy === draft.id} onClick={() => void review(draft, "needs_edit")} className="rounded-lg border border-amber-300 px-3 py-2 text-xs font-bold text-amber-900">Needs edit</button>
                    <button type="button" disabled={busy === draft.id} onClick={() => void review(draft, "reject")} className="rounded-lg border border-red-300 px-3 py-2 text-xs font-bold text-red-800">Reject</button>
                  </div>
                </>
              )}
              {canManualSendDraft && (
                <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div className="grid gap-2 sm:grid-cols-[minmax(10rem,0.6fr)_1fr_auto]">
                    <select
                      aria-label="Reply wait period"
                      value={wait.preset}
                      onChange={(event) => setReplyWaits((current) => ({
                        ...current,
                        [draft.id]: { ...wait, preset: event.target.value as ReplyWaitState["preset"] },
                      }))}
                      className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800"
                    >
                      <option value="">Reply wait</option>
                      <option value="2">Check after 2 days</option>
                      <option value="4">Check after 4 days</option>
                      <option value="7">Check after 7 days</option>
                      <option value="custom">Custom date/time</option>
                    </select>
                    {wait.preset === "custom" && (
                      <input
                        aria-label="Custom reply wait date and time"
                        type="datetime-local"
                        value={wait.customDateTime}
                        onChange={(event) => setReplyWaits((current) => ({
                          ...current,
                          [draft.id]: { ...wait, customDateTime: event.target.value },
                        }))}
                        className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-800"
                      />
                    )}
                    <button type="button" disabled={busy === draft.id} onClick={() => void markManuallySent(draft)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold text-slate-800 disabled:opacity-40">Mark manually sent</button>
                  </div>
                </div>
              )}
              {allowSendActions && draft.status === "approved" && draft.channel === "linkedin" && <button type="button" onClick={() => void copyLinkedIn(draft)} className="mt-3 rounded-lg bg-slate-950 px-3 py-2 text-xs font-bold text-white">Copy LinkedIn message</button>}
              {allowSendActions && draft.status === "approved" && draft.channel === "email" && (
                <div className="mt-3">
                  {gmailConfigured === false && <p className="mb-2 text-xs font-semibold text-amber-800">Gmail sending is disabled because credentials are not configured.</p>}
                  {!salesApproved && <p className="mb-2 text-xs font-semibold text-amber-800">Lead sales approval is required before sending.</p>}
                  {!recipient && <p className="mb-2 text-xs font-semibold text-amber-800">A valid lead email is required before sending.</p>}
                  {confirmingDraft !== draft.id ? (
                    <button type="button" disabled={!emailEnabled || Boolean(busy)} onClick={() => setConfirmingDraft(draft.id)} className="rounded-lg bg-teal-700 px-3 py-2 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-40">Review email send</button>
                  ) : (
                    <div className="rounded-xl border border-red-200 bg-red-50 p-3">
                      <p className="text-xs font-bold text-red-900">Final confirmation: send this exact approved draft to {recipient}?</p>
                      <div className="mt-2 flex gap-2">
                        <button type="button" disabled={busy === draft.id} onClick={() => void sendEmail(draft)} className="rounded-lg bg-red-700 px-3 py-2 text-xs font-bold text-white disabled:opacity-40">Confirm send email</button>
                        <button type="button" onClick={() => setConfirmingDraft("")} className="rounded-lg border border-red-300 px-3 py-2 text-xs font-bold text-red-800">Cancel</button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
