"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type Score = {
  score: number;
  disposition: string;
  evaluations: {
    criterion?: string;
    label?: string;
    key?: string;
    outcome: string;
  }[];
  intent_score: number;
  intent_level: string;
  intent_reasons: string[];
};

type Lead = {
  id: string;
  person_name: string | null;
  company_name: string | null;
  title: string | null;
  email: string | null;
  linkedin_url: string | null;
  status: string;
  suppressed: boolean;
  score: Score | null;
  outreach_status: string;
  latest_draft_status: string | null;
};

type Evidence = {
  id: string;
  title: string;
  source_url: string;
  publisher: string | null;
  excerpt: string | null;
};

type Message = {
  id: string;
  status: string;
  subject: string | null;
  body: string;
  provider: string;
  model: string | null;
  generated_at: string;
  updated_at: string;
  evidence_refs: string[];
  grounding_status: string;
  grounding_warnings: string[];
  approved_at?: string | null;
  approved_by?: string | null;
  provider_message_id?: string | null;
  sent_at?: string | null;
};

type Detail = {
  lead: Lead;
  score: Score | null;
  suppressed: boolean;
  status: string;
  latest_message: Message | null;
  evidence: Evidence[];
};

type SequenceMessage = {
  id: string;
  step_number: number | null;
  status: string;
  subject: string | null;
  scheduled_at: string | null;
  sent_at: string | null;
  provider_message_id: string | null;
  error_message: string | null;
};

type SequenceState = {
  lead_id: string;
  sequence_id: string;
  status: string;
  current_step_number: number;
  next_run_at: string | null;
  paused_reason: string | null;
  last_error: string | null;
  total_steps: number;
  messages: SequenceMessage[];
};

type InboundReply = {
  id: string;
  lead_id: string;
  lead_outreach_id: string;
  outreach_message_id: string | null;
  provider_name: string;
  provider_message_id: string | null;
  thread_id: string | null;
  dedupe_key: string;
  from_email: string;
  to_email: string;
  subject: string;
  body: string;
  classification: string;
  classification_reason: string | null;
  is_unsubscribe: boolean;
  received_at: string;
  created_at: string;
};


type Role = "admin" | "manager" | "sales";

const apiUrl =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function OutreachWorkspace() {
  const supabase = useMemo(
    () => createBrowserSupabaseClient(),
    [],
  );

  const [leads, setLeads] = useState<Lead[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [sequence, setSequence] = useState<SequenceState | null>(null);
  const [replies, setReplies] = useState<InboundReply[]>([]);
  const [role, setRole] = useState<Role | null>(null);

  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const request = useCallback(
    async (
      path: string,
      init?: RequestInit,
    ) => {
      if (!supabase) {
        throw new Error(
          "Supabase is not configured",
        );
      }

      const { data } =
        await supabase.auth.getSession();

      const token =
        data.session?.access_token;

      if (!token) {
        throw new Error(
          "Authentication required",
        );
      }

      const response = await fetch(
        apiUrl + path,
        {
          ...init,
          headers: {
            Authorization:
              "Bearer " + token,
            "Content-Type":
              "application/json",
            ...init?.headers,
          },
        },
      );

      const payload = await response
        .json()
        .catch(() => ({}));

      if (!response.ok) {
        throw new Error(
          payload.detail ||
            "Outreach request failed",
        );
      }

      return payload;
    },
    [supabase],
  );

  const loadDetail = useCallback(
    async (leadId: string) => {
      if (!leadId) {
        return;
      }

      const payload =
        (await request(
          "/outreach/" + leadId,
        )) as Detail;

      setDetail(payload);

      setSubject(
        payload.latest_message?.subject || "",
      );

      setBody(
        payload.latest_message?.body || "",
      );
    },
    [request],
  );

  const refreshLeadList =
    useCallback(async () => {
      const payload =
        (await request(
          "/outreach",
        )) as Lead[];

      setLeads(payload);
    }, [request]);

  const loadSequence = useCallback(
    async (leadId: string) => {
      if (!leadId) {
        setSequence(null);
        return;
      }

      try {
        const payload =
          (await request(
            `/outreach/${leadId}/sequence`,
          )) as SequenceState;

        setSequence(payload);
      } catch {
        setSequence(null);
      }
    },
    [request],
  );

  const loadReplies = useCallback(
    async (leadId: string) => {
      if (!leadId) {
        setReplies([]);
        return;
      }

      try {
        const payload =
          (await request(
            `/outreach/${leadId}/replies`,
          )) as InboundReply[];

        setReplies(payload);
      } catch {
        setReplies([]);
      }
    },
    [request],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const payload =
        (await request(
          "/outreach",
        )) as Lead[];

      setLeads(payload);

      const nextId =
        selectedId ||
        payload[0]?.id ||
        "";

      setSelectedId(nextId);

      if (nextId) {
        await Promise.all([
          loadDetail(nextId),
          loadSequence(nextId),
          loadReplies(nextId),
        ]);
      } else {
        setDetail(null);
        setSequence(null);
        setReplies([]);
      }
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to load outreach leads",
      );
    } finally {
      setLoading(false);
    }
  }, [
    loadDetail,
    loadSequence,
    loadReplies,
    request,
    selectedId,
  ]);

  useEffect(() => {
    const task = window.setTimeout(
      () => void load(),
      0,
    );

    return () =>
      window.clearTimeout(task);
  }, [load]);

  useEffect(() => {
    if (!supabase) {
      return;
    }

    void supabase.auth.getUser().then(
      async ({ data }) => {
        if (!data.user) {
          setRole(null);
          return;
        }

        const { data: profile } =
          await supabase
            .from("profiles")
            .select("role")
            .eq("id", data.user.id)
            .single();

        setRole(
          (profile?.role as Role | undefined) ??
            null,
        );
      },
    );
  }, [supabase]);

  async function choose(
    leadId: string,
  ) {
    setSelectedId(leadId);
    setError("");
    setNotice("");

    try {
      await Promise.all([
        loadDetail(leadId),
        loadSequence(leadId),
        loadReplies(leadId),
      ]);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to load outreach",
      );
    }
  }

  async function action(
    kind:
      | "generate"
      | "regenerate"
      | "save",
  ) {
    if (!selectedId) {
      return;
    }

    setBusy(kind);
    setError("");
    setNotice("");

    try {
      if (kind === "generate") {
        await request(
          "/outreach/generate",
          {
            method: "POST",
            body: JSON.stringify({
              lead_id: selectedId,
              channel: "email",
            }),
          },
        );
      } else if (
        kind === "regenerate"
      ) {
        await request(
          `/outreach/${selectedId}/regenerate`,
          {
            method: "POST",
            body: "{}",
          },
        );
      } else {
        await request(
          `/outreach/${selectedId}/save`,
          {
            method: "POST",
            body: JSON.stringify({
              subject,
              body,
            }),
          },
        );
      }

      if (kind === "save") {
        setNotice(
          "Draft edits saved. Nothing was sent.",
        );
      } else if (
        kind === "regenerate"
      ) {
        setNotice(
          "Draft regenerated and recorded.",
        );
      } else {
        setNotice(
          "Draft generated and saved for review.",
        );
      }

      await loadDetail(selectedId);
      await refreshLeadList();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Outreach action failed",
      );
    } finally {
      setBusy("");
    }
  }

  async function approve() {
    if (!selectedId) {
      return;
    }

    const confirmed =
      window.confirm(
        "Approve this exact outreach draft? After approval, editing and regeneration will be locked.",
      );

    if (!confirmed) {
      return;
    }

    setBusy("approve");
    setError("");
    setNotice("");

    try {
      await request(
        `/outreach/${selectedId}/approve`,
        {
          method: "POST",
          body: "{}",
        },
      );

      setNotice(
        "Outreach draft approved. It is now eligible for sending.",
      );

      await loadDetail(selectedId);
      await refreshLeadList();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to approve outreach",
      );
    } finally {
      setBusy("");
    }
  }

  async function send() {
    if (!selectedId) {
      return;
    }

    const confirmed =
      window.confirm(
        "Send this approved email now? This action will execute outbound delivery.",
      );

    if (!confirmed) {
      return;
    }

    setBusy("send");
    setError("");
    setNotice("");

    try {
      const result =
        (await request(
          `/outreach/${selectedId}/send`,
          {
            method: "POST",
            body: JSON.stringify({
              confirm: true,
            }),
          },
        )) as {
          status: string;
          provider?: string;
          provider_message_id?: string;
          sent_at?: string;
          idempotent?: boolean;
        };

      if (result.idempotent) {
        setNotice(
          "This message was already sent. No duplicate email was created.",
        );
      } else {
        setNotice(
          "Email sent successfully through the outbound provider.",
        );
      }

      await Promise.all([
        loadDetail(selectedId),
        loadSequence(selectedId),
        loadReplies(selectedId),
        refreshLeadList(),
      ]);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to send outreach",
      );
    } finally {
      setBusy("");
    }
  }


  async function pauseSequence() {
    if (!selectedId) {
      return;
    }

    const reason = window.prompt(
      "Why are you pausing this outreach sequence?",
      "Paused for review",
    );

    if (!reason?.trim()) {
      return;
    }

    setBusy("pause-sequence");
    setError("");
    setNotice("");

    try {
      await request(
        `/outreach/${selectedId}/sequence/pause`,
        {
          method: "POST",
          body: JSON.stringify({
            reason: reason.trim(),
          }),
        },
      );

      setNotice(
        "Automated follow-ups paused for this lead.",
      );

      await loadSequence(selectedId);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to pause sequence",
      );
    } finally {
      setBusy("");
    }
  }

  async function resumeSequence() {
    if (!selectedId) {
      return;
    }

    const confirmed = window.confirm(
      "Resume automated follow-ups for this lead?",
    );

    if (!confirmed) {
      return;
    }

    setBusy("resume-sequence");
    setError("");
    setNotice("");

    try {
      await request(
        `/outreach/${selectedId}/sequence/resume`,
        {
          method: "POST",
          body: "{}",
        },
      );

      setNotice(
        "Automated follow-ups resumed.",
      );

      await loadSequence(selectedId);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to resume sequence",
      );
    } finally {
      setBusy("");
    }
  }

  async function runDueFollowups() {
    const confirmed = window.confirm(
      "Run all currently due automated follow-ups now?",
    );

    if (!confirmed) {
      return;
    }

    setBusy("run-due");
    setError("");
    setNotice("");

    try {
      const result =
        (await request(
          "/outreach/sequences/run-due",
          {
            method: "POST",
            body: JSON.stringify({
              limit: 50,
            }),
          },
        )) as {
          processed: number;
        };

      setNotice(
        `${result.processed} due follow-up${
          result.processed === 1 ? "" : "s"
        } processed.`,
      );

      if (selectedId) {
        await Promise.all([
          loadDetail(selectedId),
          loadSequence(selectedId),
          loadReplies(selectedId),
          refreshLeadList(),
        ]);
      }
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to run due follow-ups",
      );
    } finally {
      setBusy("");
    }
  }

  const message =
    detail?.latest_message;

  const score =
    detail?.score;

  const matched = (
    score?.evaluations || []
  ).filter(
    (item) =>
      item.outcome === "matched",
  );

  const usedEvidence = (
    detail?.evidence || []
  ).filter((item) =>
    message?.evidence_refs.includes(
      item.id,
    ),
  );

  const blocked = Boolean(
    detail?.suppressed,
  );

  const status =
    message?.status || "none";

  const editable =
    status === "draft" &&
    !blocked;

  const canApprove =
    status === "draft" &&
    !blocked;

  const canSend =
    status === "approved" &&
    !blocked;

  const finalized =
    status === "approved" ||
    status === "sent" ||
    status === "failed";

  function statusClasses(
    value: string,
  ) {
    if (value === "sent") {
      return "bg-emerald-50 text-emerald-700";
    }

    if (value === "approved") {
      return "bg-blue-50 text-blue-700";
    }

    if (value === "replied") {
      return "bg-teal-50 text-teal-700";
    }

    if (value === "failed") {
      return "bg-red-50 text-red-700";
    }

    if (value === "draft") {
      return "bg-amber-50 text-amber-700";
    }

    return "bg-slate-100 text-slate-600";
  }

  return (
    <section className="space-y-6">
      <header className="rounded-3xl bg-slate-950 p-7 text-white">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">
          Evidence-grounded outreach
        </p>

        <h1 className="mt-3 text-3xl font-bold">
          Outreach
        </h1>

        <p className="mt-3 max-w-3xl text-sm text-slate-300">
          Generate, review, approve, and
          explicitly send email outreach for
          sales-approved leads. Delivery always
          requires human approval and confirmation.
        </p>
      </header>

      {error && (
        <p
          role="alert"
          className="rounded-xl bg-red-50 p-4 text-sm text-red-800"
        >
          {error}
        </p>
      )}

      {notice && (
        <p
          role="status"
          className="rounded-xl bg-teal-50 p-4 text-sm text-teal-800"
        >
          {notice}
        </p>
      )}

      <div className="grid gap-6 xl:grid-cols-[22rem_1fr]">
        <aside className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 p-5">
            <h2 className="font-bold text-slate-950">
              Eligible leads
            </h2>

            <p className="mt-1 text-xs text-slate-500">
              Sales-approved and accessible
              to you
            </p>
          </div>

          {loading ? (
            <p className="p-5 text-sm text-slate-500">
              Loading…
            </p>
          ) : leads.length === 0 ? (
            <p className="p-5 text-sm text-slate-500">
              No eligible leads.
            </p>
          ) : (
            <div className="max-h-[44rem] overflow-y-auto">
              {leads.map((lead) => (
                <button
                  type="button"
                  key={lead.id}
                  onClick={() =>
                    void choose(lead.id)
                  }
                  className={
                    "block w-full border-b border-slate-100 p-4 text-left hover:bg-slate-50 " +
                    (lead.id === selectedId
                      ? "bg-teal-50"
                      : "bg-white")
                  }
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-bold text-slate-900">
                      {lead.person_name ||
                        "Name unknown"}
                    </span>

                    <span
                      className={
                        "rounded-full px-2 py-1 text-[10px] font-bold uppercase " +
                        (lead.suppressed
                          ? "bg-red-50 text-red-700"
                          : statusClasses(
                              lead.latest_draft_status ||
                                "none",
                            ))
                      }
                    >
                      {lead.suppressed
                        ? "Suppressed"
                        : lead.latest_draft_status ||
                          "No draft"}
                    </span>
                  </div>

                  <p className="mt-1 text-xs text-slate-500">
                    {lead.company_name ||
                      "Company unknown"}{" "}
                    ·{" "}
                    {lead.title ||
                      "Title unknown"}
                  </p>

                  <p className="mt-2 text-xs font-semibold text-teal-700">
                    ICP{" "}
                    {lead.score?.score ??
                      "—"}{" "}
                    · Intent{" "}
                    {lead.score
                      ?.intent_score ?? "—"}
                  </p>
                </button>
              ))}
            </div>
          )}
        </aside>

        {!detail ? (
          <div className="rounded-3xl border border-slate-200 bg-white p-10 text-center text-sm text-slate-500">
            Select an eligible lead to
            review outreach.
          </div>
        ) : (
          <div className="space-y-5">
            {blocked && (
              <div className="rounded-2xl border border-red-200 bg-red-50 p-4">
                <p className="font-bold text-red-900">
                  Suppressed
                </p>

                <p className="mt-1 text-sm text-red-800">
                  Generation, approval, and
                  sending are blocked for this
                  email address.
                </p>
              </div>
            )}

            <div className="grid gap-5 lg:grid-cols-2">
              <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
                <h2 className="font-bold text-slate-950">
                  Lead context
                </h2>

                <dl className="mt-4 grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <dt className="text-slate-500">
                      Person
                    </dt>
                    <dd className="font-semibold">
                      {detail.lead
                        .person_name ||
                        "Unknown"}
                    </dd>
                  </div>

                  <div>
                    <dt className="text-slate-500">
                      Company
                    </dt>
                    <dd className="font-semibold">
                      {detail.lead
                        .company_name ||
                        "Unknown"}
                    </dd>
                  </div>

                  <div>
                    <dt className="text-slate-500">
                      Title
                    </dt>
                    <dd className="font-semibold">
                      {detail.lead.title ||
                        "Unknown"}
                    </dd>
                  </div>

                  <div>
                    <dt className="text-slate-500">
                      Email
                    </dt>
                    <dd className="font-semibold">
                      {detail.lead.email ||
                        "Unknown"}
                    </dd>
                  </div>
                </dl>

                {detail.lead
                  .linkedin_url && (
                  <a
                    href={
                      detail.lead
                        .linkedin_url
                    }
                    target="_blank"
                    rel="noreferrer"
                    className="mt-4 inline-block text-sm font-bold text-teal-700"
                  >
                    LinkedIn profile ↗
                  </a>
                )}
              </article>

              <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
                <h2 className="font-bold text-slate-950">
                  Intelligence
                </h2>

                <div className="mt-4 flex gap-8">
                  <div>
                    <p className="text-3xl font-black">
                      {score?.score ??
                        "—"}
                    </p>

                    <p className="text-xs text-slate-500">
                      ICP ·{" "}
                      {score?.disposition ||
                        "Not scored"}
                    </p>
                  </div>

                  <div>
                    <p className="text-3xl font-black">
                      {score?.intent_score ??
                        "—"}
                    </p>

                    <p className="text-xs capitalize text-slate-500">
                      Intent ·{" "}
                      {score?.intent_level ||
                        "unknown"}
                    </p>
                  </div>
                </div>

                <div className="mt-4 text-sm text-slate-600">
                  {matched
                    .slice(0, 3)
                    .map(
                      (
                        item,
                        index,
                      ) => (
                        <p key={index}>
                          ✓{" "}
                          {item.label ||
                            item.criterion ||
                            item.key}
                        </p>
                      ),
                    )}

                  {(
                    score?.intent_reasons ||
                    []
                  )
                    .slice(0, 3)
                    .map((reason) => (
                      <p key={reason}>
                        • {reason}
                      </p>
                    ))}
                </div>
              </article>
            </div>

            <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-bold text-slate-950">
                    Message
                  </h2>

                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span
                      className={
                        "rounded-full px-3 py-1 text-xs font-bold uppercase " +
                        statusClasses(
                          status,
                        )
                      }
                    >
                      {message?.status ||
                        "not generated"}
                    </span>

                    {message && (
                      <span className="text-xs text-slate-500">
                        {message.provider}
                        {message.model
                          ? ` / ${message.model}`
                          : ""}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  {!message && (
                    <button
                      type="button"
                      disabled={
                        blocked ||
                        Boolean(busy)
                      }
                      onClick={() =>
                        void action(
                          "generate",
                        )
                      }
                      className="rounded-xl bg-teal-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-40"
                    >
                      {busy ===
                      "generate"
                        ? "Generating..."
                        : "Generate"}
                    </button>
                  )}

                  {message && (
                    <button
                      type="button"
                      disabled={
                        !editable ||
                        Boolean(busy)
                      }
                      onClick={() =>
                        void action(
                          "regenerate",
                        )
                      }
                      className="rounded-xl border border-teal-300 px-4 py-2 text-sm font-bold text-teal-800 disabled:opacity-40"
                    >
                      {busy ===
                      "regenerate"
                        ? "Regenerating..."
                        : "Regenerate"}
                    </button>
                  )}

                  <button
                    type="button"
                    disabled={
                      !editable ||
                      Boolean(busy) ||
                      !body.trim()
                    }
                    onClick={() =>
                      void action("save")
                    }
                    className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-bold text-white disabled:opacity-40"
                  >
                    {busy === "save"
                      ? "Saving..."
                      : "Save draft"}
                  </button>

                  {message && (
                    <button
                      type="button"
                      disabled={
                        !canApprove ||
                        Boolean(busy)
                      }
                      onClick={() =>
                        void approve()
                      }
                      className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-40"
                    >
                      {busy ===
                      "approve"
                        ? "Approving..."
                        : "Approve"}
                    </button>
                  )}

                  {message && (
                    <button
                      type="button"
                      disabled={
                        !canSend ||
                        Boolean(busy)
                      }
                      onClick={() =>
                        void send()
                      }
                      className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-40"
                    >
                      {busy === "send"
                        ? "Sending..."
                        : status ===
                            "sent"
                          ? "Sent"
                          : "Send email"}
                    </button>
                  )}
                </div>
              </div>

              {finalized && (
                  <div className="mt-5 rounded-2xl bg-slate-50 p-4 text-sm text-slate-600">
                    {status ===
                      "approved" && (
                      <p>
                        This draft is
                        approved. Editing and
                        regeneration are now
                        locked.
                      </p>
                    )}

                    {status ===
                      "sent" && (
                      <>
                        <p className="font-semibold text-emerald-700">
                          Email delivery
                          completed.
                        </p>

                        {message?.sent_at && (
                          <p className="mt-1 text-xs">
                            Sent:{" "}
                            {new Date(
                              message.sent_at,
                            ).toLocaleString()}
                          </p>
                        )}

                        {message
                          ?.provider_message_id && (
                          <p className="mt-1 break-all text-xs">
                            Provider message
                            ID:{" "}
                            {
                              message.provider_message_id
                            }
                          </p>
                        )}
                      </>
                    )}

                    {status ===
                      "failed" && (
                      <p className="font-semibold text-red-700">
                        Delivery failed.
                        Review the error before
                        retrying.
                      </p>
                    )}
                  </div>
                )}

              {message ? (
                <>
                  <label className="mt-5 block text-sm font-bold text-slate-700">
                    Subject

                    <input
                      value={subject}
                      readOnly={!editable}
                      onChange={(event) =>
                        setSubject(
                          event.target.value,
                        )
                      }
                      className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 font-normal read-only:bg-slate-50"
                    />
                  </label>

                  <label className="mt-4 block text-sm font-bold text-slate-700">
                    Email body

                    <textarea
                      rows={11}
                      value={body}
                      readOnly={!editable}
                      onChange={(event) =>
                        setBody(
                          event.target.value,
                        )
                      }
                      className="mt-2 w-full rounded-xl border border-slate-300 p-3 font-normal leading-6 read-only:bg-slate-50"
                    />
                  </label>

                  <p className="mt-3 text-xs text-slate-500">
                    Grounding:{" "}
                    <span className="font-bold">
                      {
                        message.grounding_status
                      }
                    </span>
                  </p>

                  {message.grounding_warnings.map(
                    (warning) => (
                      <p
                        key={warning}
                        className="mt-1 text-xs text-amber-800"
                      >
                        {warning}
                      </p>
                    ),
                  )}
                </>
              ) : (
                <p className="mt-5 text-sm text-slate-500">
                  No current draft.
                  Generate a draft to begin
                  review.
                </p>
              )}
            </article>

            <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-bold text-slate-950">
                    Sequence automation
                  </h2>

                  <p className="mt-1 text-sm text-slate-500">
                    Follow-up timing, progress, and execution history
                    for this lead.
                  </p>
                </div>

                {(role === "admin" ||
                  role === "manager") && (
                  <div className="flex flex-wrap gap-2">
                  {sequence?.status === "scheduled" && (
                    <button
                      type="button"
                      disabled={Boolean(busy)}
                      onClick={() =>
                        void pauseSequence()
                      }
                      className="rounded-xl border border-amber-300 px-4 py-2 text-sm font-bold text-amber-800 disabled:opacity-40"
                    >
                      {busy === "pause-sequence"
                        ? "Pausing..."
                        : "Pause"}
                    </button>
                  )}

                  {sequence?.status === "paused" && (
                    <button
                      type="button"
                      disabled={Boolean(busy)}
                      onClick={() =>
                        void resumeSequence()
                      }
                      className="rounded-xl bg-teal-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-40"
                    >
                      {busy === "resume-sequence"
                        ? "Resuming..."
                        : "Resume"}
                    </button>
                  )}

                  <button
                    type="button"
                    disabled={Boolean(busy)}
                    onClick={() =>
                      void runDueFollowups()
                    }
                    className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-bold text-white disabled:opacity-40"
                  >
                    {busy === "run-due"
                      ? "Running..."
                      : "Run due follow-ups"}
                  </button>
                  </div>
                )}
              </div>

              {!sequence ? (
                <p className="mt-5 text-sm text-slate-500">
                  No active sequence yet. After the first approved
                  email is sent, the next follow-up will be scheduled
                  automatically.
                </p>
              ) : (
                <>
                  <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="rounded-2xl bg-slate-50 p-4">
                      <p className="text-xs font-semibold uppercase text-slate-500">
                        Status
                      </p>

                      <p className="mt-2 font-bold capitalize text-slate-950">
                        {sequence.status}
                      </p>
                    </div>

                    <div className="rounded-2xl bg-slate-50 p-4">
                      <p className="text-xs font-semibold uppercase text-slate-500">
                        Progress
                      </p>

                      <p className="mt-2 font-bold text-slate-950">
                        Step {sequence.current_step_number} of{" "}
                        {sequence.total_steps}
                      </p>
                    </div>

                    <div className="rounded-2xl bg-slate-50 p-4">
                      <p className="text-xs font-semibold uppercase text-slate-500">
                        Next follow-up
                      </p>

                      <p className="mt-2 text-sm font-bold text-slate-950">
                        {sequence.next_run_at
                          ? new Date(
                              sequence.next_run_at,
                            ).toLocaleString()
                          : "None"}
                      </p>
                    </div>

                    <div className="rounded-2xl bg-slate-50 p-4">
                      <p className="text-xs font-semibold uppercase text-slate-500">
                        Messages
                      </p>

                      <p className="mt-2 font-bold text-slate-950">
                        {sequence.messages.length}
                      </p>
                    </div>
                  </div>

                  {sequence.paused_reason && (
                    <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-4">
                      <p className="text-sm font-bold text-amber-900">
                        Sequence paused
                      </p>

                      <p className="mt-1 text-sm text-amber-800">
                        {sequence.paused_reason}
                      </p>
                    </div>
                  )}

                  {sequence.last_error && (
                    <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 p-4">
                      <p className="text-sm font-bold text-red-900">
                        Last execution error
                      </p>

                      <p className="mt-1 text-sm text-red-800">
                        {sequence.last_error}
                      </p>
                    </div>
                  )}

                  <div className="mt-5 overflow-hidden rounded-2xl border border-slate-200">
                    <div className="border-b border-slate-200 bg-slate-50 px-4 py-3">
                      <h3 className="text-sm font-bold text-slate-950">
                        Sequence history
                      </h3>
                    </div>

                    {sequence.messages.length === 0 ? (
                      <p className="p-4 text-sm text-slate-500">
                        No sequence messages recorded.
                      </p>
                    ) : (
                      <div className="divide-y divide-slate-100">
                        {sequence.messages.map(
                          (item) => (
                            <div
                              key={item.id}
                              className="grid gap-3 p-4 md:grid-cols-[5rem_8rem_1fr_auto]"
                            >
                              <div>
                                <p className="text-xs text-slate-500">
                                  Step
                                </p>

                                <p className="font-bold text-slate-950">
                                  {item.step_number ?? "—"}
                                </p>
                              </div>

                              <div>
                                <p className="text-xs text-slate-500">
                                  Status
                                </p>

                                <span
                                  className={
                                    "mt-1 inline-block rounded-full px-2 py-1 text-[10px] font-bold uppercase " +
                                    statusClasses(
                                      item.status,
                                    )
                                  }
                                >
                                  {item.status}
                                </span>
                              </div>

                              <div>
                                <p className="text-xs text-slate-500">
                                  Subject
                                </p>

                                <p className="mt-1 text-sm font-semibold text-slate-900">
                                  {item.subject ||
                                    "No subject"}
                                </p>

                                {item.error_message && (
                                  <p className="mt-1 text-xs text-red-700">
                                    {item.error_message}
                                  </p>
                                )}
                              </div>

                              <div className="text-xs text-slate-500 md:text-right">
                                {item.sent_at ? (
                                  <>
                                    <p>Sent</p>
                                    <p className="mt-1 font-semibold text-slate-700">
                                      {new Date(
                                        item.sent_at,
                                      ).toLocaleString()}
                                    </p>
                                  </>
                                ) : item.scheduled_at ? (
                                  <>
                                    <p>Scheduled</p>
                                    <p className="mt-1 font-semibold text-slate-700">
                                      {new Date(
                                        item.scheduled_at,
                                      ).toLocaleString()}
                                    </p>
                                  </>
                                ) : (
                                  <p>—</p>
                                )}
                              </div>
                            </div>
                          ),
                        )}
                      </div>
                    )}
                  </div>
                </>
              )}
            </article>

            <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-bold text-slate-950">
                    Prospect replies
                  </h2>

                  <p className="mt-1 text-sm text-slate-500">
                    Inbound responses detected for this outreach
                    sequence. Replies automatically stop future
                    follow-ups.
                  </p>
                </div>

                {replies.length > 0 && (
                  <span className="rounded-full bg-teal-50 px-3 py-1 text-xs font-bold text-teal-700">
                    {replies.length} repl{replies.length === 1 ? "y" : "ies"}
                  </span>
                )}
              </div>

              {sequence?.status === "replied" && (
                <div className="mt-4 rounded-2xl border border-teal-200 bg-teal-50 p-4">
                  <p className="font-bold text-teal-900">
                    Reply received
                  </p>

                  <p className="mt-1 text-sm text-teal-800">
                    Automated follow-ups have stopped for this lead.
                  </p>
                </div>
              )}

              {replies.length === 0 ? (
                <p className="mt-5 text-sm text-slate-500">
                  No inbound replies have been recorded yet.
                </p>
              ) : (
                <div className="mt-5 space-y-4">
                  {replies.map((reply) => (
                    <div
                      key={reply.id}
                      className="rounded-2xl border border-slate-200 p-5"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-xs font-semibold uppercase text-slate-500">
                            From
                          </p>

                          <p className="mt-1 font-bold text-slate-950">
                            {reply.from_email}
                          </p>
                        </div>

                        <div className="flex flex-wrap gap-2">
                          <span
                            className={
                              "rounded-full px-3 py-1 text-xs font-bold uppercase " +
                              (reply.classification === "unsubscribe"
                                ? "bg-red-50 text-red-700"
                                : reply.classification === "interested" ||
                                    reply.classification === "meeting_request"
                                  ? "bg-emerald-50 text-emerald-700"
                                  : "bg-slate-100 text-slate-700")
                            }
                          >
                            {reply.classification.replaceAll("_", " ")}
                          </span>

                          {reply.is_unsubscribe && (
                            <span className="rounded-full bg-red-50 px-3 py-1 text-xs font-bold uppercase text-red-700">
                              Suppressed
                            </span>
                          )}
                        </div>
                      </div>

                      {reply.is_unsubscribe && (
                        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3">
                          <p className="text-sm font-bold text-red-900">
                            Unsubscribe request
                          </p>

                          <p className="mt-1 text-sm text-red-800">
                            This address has been suppressed from future outreach.
                          </p>
                        </div>
                      )}

                      <div className="mt-4">
                        <p className="text-xs font-semibold uppercase text-slate-500">
                          Subject
                        </p>

                        <p className="mt-1 text-sm font-semibold text-slate-900">
                          {reply.subject || "No subject"}
                        </p>
                      </div>

                      <div className="mt-4 rounded-xl bg-slate-50 p-4">
                        <p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">
                          {reply.body}
                        </p>
                      </div>

                      {reply.classification_reason && (
                        <p className="mt-3 text-xs text-slate-500">
                          Classified because: {reply.classification_reason}
                        </p>
                      )}

                      <div className="mt-4 flex flex-wrap justify-between gap-2 text-xs text-slate-500">
                        <span>
                          Received{" "}
                          {new Date(
                            reply.received_at,
                          ).toLocaleString()}
                        </span>

                        <span>
                          Provider: {reply.provider_name}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </article>

            <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="font-bold text-slate-950">
                Evidence used for
                personalization
              </h2>

              {usedEvidence.length ===
              0 ? (
                <p className="mt-3 text-sm text-slate-500">
                  No external evidence was
                  used. Any draft is
                  intentionally generic.
                </p>
              ) : (
                <div className="mt-4 grid gap-3">
                  {usedEvidence.map(
                    (item) => (
                      <div
                        key={item.id}
                        className="rounded-2xl bg-slate-50 p-4"
                      >
                        <a
                          href={
                            item.source_url
                          }
                          target="_blank"
                          rel="noreferrer"
                          className="font-bold text-teal-700"
                        >
                          {item.title} ↗
                        </a>

                        <p className="mt-1 text-xs font-semibold text-slate-500">
                          {item.publisher ||
                            "Publisher unknown"}
                        </p>

                        <p className="mt-2 text-sm leading-6 text-slate-600">
                          {item.excerpt ||
                            "No excerpt stored."}
                        </p>
                      </div>
                    ),
                  )}
                </div>
              )}
            </article>
          </div>
        )}
      </div>
    </section>
  );
}
