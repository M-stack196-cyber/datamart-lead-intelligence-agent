"use client";

import { useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

export type OutreachDraft = {
  id: string;
  channel: "email" | "linkedin";
  subject: string | null;
  body: string;
  status: "draft" | "approved" | "rejected";
  evidence_ids: string[];
  created_by: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_notes: string | null;
  updated_at: string;
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
};

export function OutreachDraftPanel({ leadId, role, drafts, evidence, recipient, salesApproved, onChanged }: Props) {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [edits, setEdits] = useState<Record<string, { subject: string; body: string }>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [gmailConfigured, setGmailConfigured] = useState<boolean | null>(null);
  const [confirmingDraft, setConfirmingDraft] = useState("");
  const canReview = role === "admin" || role === "manager";

  useEffect(() => {
    let active = true;
    fetch((process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000") + "/health")
      .then((response) => response.json())
      .then((payload) => {
        if (active) setGmailConfigured(Boolean(payload.integrations_configured?.gmail));
      })
      .catch(() => {
        if (active) setGmailConfigured(false);
      });
    return () => { active = false; };
  }, []);

  async function callBackend(path: string, body: object) {
    if (!supabase) throw new Error("Supabase is not configured");
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) throw new Error("Authentication required");
    const response = await fetch((process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000") + path, {
      method: "POST",
      headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
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

  async function review(draft: OutreachDraft, action: "approved" | "rejected") {
    const reviewNotes = notes[draft.id]?.trim();
    if (!reviewNotes) {
      setError("Review notes are required.");
      return;
    }
    setBusy(draft.id);
    setError("");
    try {
      await callBackend("/outreach/drafts/" + draft.id + "/review", {
        action,
        review_notes: reviewNotes,
      });
      setMessage(action === "approved" ? "Draft approved by an administrator." : "Draft rejected with review notes.");
      await onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to review draft");
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
        {canReview && <div className="flex gap-2"><button type="button" disabled={Boolean(busy)} onClick={() => void generate("email")} className="rounded-lg border border-teal-300 px-3 py-2 text-xs font-bold text-teal-800 disabled:opacity-40">Generate email</button><button type="button" disabled={Boolean(busy)} onClick={() => void generate("linkedin")} className="rounded-lg border border-teal-300 px-3 py-2 text-xs font-bold text-teal-800 disabled:opacity-40">Generate LinkedIn</button></div>}
      </div>
      {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-800">{error}</p>}
      {message && <p role="status" className="mt-3 rounded-lg bg-teal-50 p-3 text-xs text-teal-800">{message}</p>}
      <div className="mt-4 space-y-4">
        {drafts.length === 0 ? <p className="text-sm text-slate-500">No outreach draft has been generated.</p> : drafts.map((draft) => {
          const edit = edits[draft.id] || { subject: draft.subject || "", body: draft.body };
          const usedEvidence = evidence.filter((item) => draft.evidence_ids.includes(item.id));
          const emailEnabled = draft.status === "approved" && draft.channel === "email" && gmailConfigured === true && salesApproved && Boolean(recipient);
          return <article key={draft.id} className="rounded-2xl border border-slate-200 p-4"><div className="flex items-center justify-between gap-3"><p className="text-sm font-bold capitalize">{draft.channel} · step 1</p><span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold capitalize text-slate-700">{draft.status}</span></div>{draft.channel === "email" && <input aria-label="Email subject" value={edit.subject} readOnly={!canReview || draft.status !== "draft"} onChange={(event) => setEdits((current) => ({ ...current, [draft.id]: { ...edit, subject: event.target.value } }))} className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm read-only:bg-slate-50" />}<textarea aria-label={draft.channel + " draft body"} rows={9} value={edit.body} readOnly={!canReview || draft.status !== "draft"} onChange={(event) => setEdits((current) => ({ ...current, [draft.id]: { ...edit, body: event.target.value } }))} className="mt-3 w-full rounded-lg border border-slate-300 p-3 text-sm leading-6 read-only:bg-slate-50" /><div className="mt-3"><p className="text-xs font-bold uppercase text-slate-500">Evidence used</p>{usedEvidence.map((item) => <a key={item.id} href={item.source_url} target="_blank" rel="noreferrer" className="mt-1 block text-xs font-bold text-teal-700">{item.title} ↗</a>)}</div>{draft.review_notes && <p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">Review notes: {draft.review_notes}</p>}{canReview && draft.status === "draft" && <><input aria-label="Draft review notes" value={notes[draft.id] || ""} onChange={(event) => setNotes((current) => ({ ...current, [draft.id]: event.target.value }))} placeholder="Review notes required" className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" /><div className="mt-3 flex flex-wrap gap-2"><button type="button" disabled={busy === draft.id} onClick={() => void save(draft)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold">Save edits</button>{role === "admin" && <button type="button" disabled={busy === draft.id} onClick={() => void review(draft, "approved")} className="rounded-lg bg-teal-600 px-3 py-2 text-xs font-bold text-white">Approve draft</button>}<button type="button" disabled={busy === draft.id} onClick={() => void review(draft, "rejected")} className="rounded-lg border border-red-300 px-3 py-2 text-xs font-bold text-red-800">Reject draft</button></div></>}{draft.status === "approved" && draft.channel === "linkedin" && <button type="button" onClick={() => void copyLinkedIn(draft)} className="mt-3 rounded-lg bg-slate-950 px-3 py-2 text-xs font-bold text-white">Copy LinkedIn message</button>}{draft.status === "approved" && draft.channel === "email" && <div className="mt-3">{gmailConfigured === false && <p className="mb-2 text-xs font-semibold text-amber-800">Gmail sending is disabled because credentials are not configured.</p>}{!salesApproved && <p className="mb-2 text-xs font-semibold text-amber-800">Lead sales approval is required before sending.</p>}{!recipient && <p className="mb-2 text-xs font-semibold text-amber-800">A valid lead email is required before sending.</p>}{confirmingDraft !== draft.id ? <button type="button" disabled={!emailEnabled || Boolean(busy)} onClick={() => setConfirmingDraft(draft.id)} className="rounded-lg bg-teal-700 px-3 py-2 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-40">Review email send</button> : <div className="rounded-xl border border-red-200 bg-red-50 p-3"><p className="text-xs font-bold text-red-900">Final confirmation: send this exact approved draft to {recipient}?</p><div className="mt-2 flex gap-2"><button type="button" disabled={busy === draft.id} onClick={() => void sendEmail(draft)} className="rounded-lg bg-red-700 px-3 py-2 text-xs font-bold text-white disabled:opacity-40">Confirm send email</button><button type="button" onClick={() => setConfirmingDraft("")} className="rounded-lg border border-red-300 px-3 py-2 text-xs font-bold text-red-800">Cancel</button></div></div>}</div>}</article>;
        })}
      </div>
    </div>
  );
}
