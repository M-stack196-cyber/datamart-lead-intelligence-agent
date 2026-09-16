"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";
import { authenticatedFetch } from "@/lib/api";

type Role = "admin" | "manager" | "sales";
type AuditLogRow = {
  id: number;
  action: string;
  entity_type: string;
  entity_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
  actor_id: string | null;
};

type Profile = {
  id: string;
  email: string;
  full_name: string | null;
  role: Role;
  is_active: boolean;
};
type SenderAccount = {
  id: string;
  display_name: string;
  email_address: string;
  provider: "manual_only" | "gmail_oauth" | "smtp";
  status: "not_connected" | "connected" | "disabled" | "error";
  is_active: boolean;
  daily_send_limit: number | null;
  sent_today: number;
  reply_tracking_enabled: boolean;
};

const roleLabels: Record<Role, string> = {
  admin: "Admin",
  manager: "Manager",
  sales: "Sales",
};

export function SettingsWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [role, setRole] = useState<Role | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [auditLog, setAuditLog] = useState<AuditLogRow[]>([]);
  const [senderAccounts, setSenderAccounts] = useState<SenderAccount[]>([]);
  const [senderForm, setSenderForm] = useState({
    display_name: "",
    email_address: "",
    provider: "manual_only" as SenderAccount["provider"],
    daily_send_limit: "50",
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    if (!supabase) return;
    setLoading(true);
    setError("");

    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) {
      setLoading(false);
      return;
    }

    const { data: profileData, error: profileError } = await supabase
      .from("profiles")
      .select("id,email,full_name,role,is_active")
      .eq("id", userData.user.id)
      .single();

    if (profileError) {
      setError(profileError.message);
      setLoading(false);
      return;
    }

    const currentRole = (profileData?.role as Role | undefined) ?? null;
    setRole(currentRole);

    if (currentRole === "admin") {
      const [{ data: profilesData, error: profilesError }, { data: auditData, error: auditError }, senderResponse] = await Promise.all([
        supabase.from("profiles").select("id,email,full_name,role,is_active").order("created_at", { ascending: false }),
        supabase.from("audit_log").select("id,action,entity_type,entity_id,details,created_at,actor_id").order("created_at", { ascending: false }).limit(20),
        authenticatedFetch(supabase, "/sender-accounts"),
      ]);

      if (profilesError) {
        setError(profilesError.message);
      } else {
        setProfiles((profilesData ?? []) as Profile[]);
      }

      if (auditError) {
        setError((error || "") + (error ? " | " : "") + auditError.message);
      } else {
        setAuditLog((auditData ?? []) as AuditLogRow[]);
      }

      const senderPayload = await senderResponse.json().catch(() => ({}));
      if (!senderResponse.ok) {
        setError((error || "") + (error ? " | " : "") + (senderPayload.detail || "Unable to load sender accounts"));
      } else {
        setSenderAccounts((senderPayload.sender_accounts ?? []) as SenderAccount[]);
      }
    } else {
      setProfiles([]);
      setAuditLog([]);
      setSenderAccounts([]);
    }

    setLoading(false);
  }, [error, supabase]);

  const addSenderAccount = useCallback(async () => {
    if (!supabase) return;
    setError("");
    setMessage("");
    try {
      const response = await authenticatedFetch(supabase, "/sender-accounts", {
        method: "POST",
        body: JSON.stringify({
          display_name: senderForm.display_name,
          email_address: senderForm.email_address,
          provider: senderForm.provider,
          daily_send_limit: senderForm.daily_send_limit ? Number(senderForm.daily_send_limit) : null,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Unable to add sender account");
      setMessage(payload.message || "Sender account added.");
      setSenderForm({ display_name: "", email_address: "", provider: "manual_only", daily_send_limit: "50" });
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to add sender account");
    }
  }, [load, senderForm, supabase]);

  const setSenderEnabled = useCallback(async (account: SenderAccount, enabled: boolean) => {
    if (!supabase) return;
    setError("");
    setMessage("");
    try {
      const action = enabled ? "enable" : "disable";
      const response = await authenticatedFetch(supabase, `/sender-accounts/${account.id}/${action}`, { method: "PATCH" });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Unable to update sender account");
      setMessage(enabled ? "Sender account enabled." : "Sender account disabled.");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to update sender account");
    }
  }, [load, supabase]);

  const connectGmail = useCallback(async (account: SenderAccount) => {
    if (!supabase) return;
    setError("");
    setMessage("");
    try {
      const response = await authenticatedFetch(supabase, `/sender-accounts/${account.id}/gmail/connect`, { method: "POST" });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Unable to start Gmail connection");
      window.location.href = payload.authorization_url;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to start Gmail connection");
    }
  }, [supabase]);

  const disconnectGmail = useCallback(async (account: SenderAccount) => {
    if (!supabase) return;
    setError("");
    setMessage("");
    try {
      const response = await authenticatedFetch(supabase, `/sender-accounts/${account.id}/gmail/disconnect`, { method: "PATCH" });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Unable to disconnect Gmail");
      setMessage("Gmail disconnected.");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to disconnect Gmail");
    }
  }, [load, supabase]);

  useEffect(() => {
    const task = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(task);
  }, [load]);

  if (loading) {
    return <p className="rounded-2xl bg-slate-100 p-5 text-sm text-slate-600">Loading settings...</p>;
  }

  if (role !== "admin") {
    return (
      <section className="space-y-6">
        <header className="rounded-3xl bg-slate-950 p-7 text-white">
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Security settings</p>
          <h1 className="mt-3 text-3xl font-bold">Admin-only controls</h1>
          <p className="mt-3 text-sm text-slate-300">Only an admin can review role assignments and audit activity.</p>
        </header>
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <header className="rounded-3xl bg-slate-950 p-7 text-white">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Security settings</p>
        <h1 className="mt-3 text-3xl font-bold">Team access and audit controls</h1>
        <p className="mt-3 text-sm text-slate-300">Review access and inspect the recent audit trail for administrative events.</p>
      </header>

      {error && <p className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      {message && <p className="rounded-xl bg-teal-50 p-4 text-sm text-teal-800">{message}</p>}

      <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h2 className="text-lg font-bold text-slate-950">Sender accounts</h2>
            <p className="mt-1 text-sm text-slate-500">Gmail OAuth is available for system sending. SMTP secret storage is not enabled yet.</p>
          </div>
        </div>
        <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_1fr_12rem_8rem_auto]">
          <input
            aria-label="Sender display name"
            value={senderForm.display_name}
            onChange={(event) => setSenderForm((current) => ({ ...current, display_name: event.target.value }))}
            placeholder="Datamart Sales"
            className="rounded-xl border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            aria-label="Sender email address"
            value={senderForm.email_address}
            onChange={(event) => setSenderForm((current) => ({ ...current, email_address: event.target.value }))}
            placeholder="sales@datamart.com"
            className="rounded-xl border border-slate-300 px-3 py-2 text-sm"
          />
          <select
            aria-label="Sender provider"
            value={senderForm.provider}
            onChange={(event) => setSenderForm((current) => ({ ...current, provider: event.target.value as SenderAccount["provider"] }))}
            className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            <option value="manual_only">Manual only</option>
            <option value="gmail_oauth">Gmail OAuth</option>
            <option value="smtp">SMTP</option>
          </select>
          {senderForm.provider === "gmail_oauth" && (
            <p className="rounded-xl bg-teal-50 px-3 py-2 text-xs font-semibold text-teal-900 lg:col-span-5">
              You will connect securely with Google. No password is stored.
            </p>
          )}
          <input
            aria-label="Daily send limit"
            type="number"
            min={1}
            value={senderForm.daily_send_limit}
            onChange={(event) => setSenderForm((current) => ({ ...current, daily_send_limit: event.target.value }))}
            className="rounded-xl border border-slate-300 px-3 py-2 text-sm"
          />
          <button type="button" onClick={() => void addSenderAccount()} className="rounded-xl bg-teal-600 px-4 py-2 text-sm font-bold text-white">
            Add sender
          </button>
        </div>
        <div className="mt-4 grid gap-3 xl:grid-cols-2">
          {senderAccounts.length === 0 ? (
            <p className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-500">No sender accounts added yet.</p>
          ) : senderAccounts.map((account) => (
            <div key={account.id} className="rounded-2xl border border-slate-200 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-bold text-slate-950">{account.display_name}</p>
                  <p className="text-sm text-slate-500">{account.email_address}</p>
                </div>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[0.65rem] font-bold uppercase tracking-[0.12em] text-slate-700">
                  {account.is_active ? account.status : "disabled"}
                </span>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                {account.provider} | {account.sent_today}/{account.daily_send_limit ?? "unlimited"} sent today
              </p>
              {account.provider === "gmail_oauth" && account.status !== "connected" && (
                <p className="mt-2 rounded-lg bg-amber-50 p-2 text-xs font-semibold text-amber-900">
                  Connect Gmail to enable system sending from this account.
                </p>
              )}
              {account.provider === "smtp" && (
                <p className="mt-2 rounded-lg bg-amber-50 p-2 text-xs font-semibold text-amber-900">
                  SMTP secret storage is not enabled yet. This account can be recorded for manual sending only.
                </p>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void setSenderEnabled(account, !account.is_active)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold text-slate-800"
                >
                  {account.is_active ? "Disable" : "Enable"}
                </button>
                {account.provider === "gmail_oauth" && account.status !== "connected" && (
                  <button
                    type="button"
                    onClick={() => void connectGmail(account)}
                    className="rounded-lg bg-teal-600 px-3 py-2 text-xs font-bold text-white"
                  >
                    Connect Gmail
                  </button>
                )}
                {account.provider === "gmail_oauth" && account.status === "connected" && (
                  <button
                    type="button"
                    onClick={() => void disconnectGmail(account)}
                    className="rounded-lg border border-red-200 px-3 py-2 text-xs font-bold text-red-800"
                  >
                    Disconnect Gmail
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-bold text-slate-950">Profiles</h2>
          <div className="mt-4 space-y-3">
            {profiles.map((profile) => (
              <div key={profile.id} className="rounded-2xl border border-slate-200 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-bold text-slate-900">{profile.full_name || profile.email}</p>
                    <p className="text-xs text-slate-500">{profile.email}</p>
                  </div>
                  <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[0.65rem] font-bold uppercase tracking-[0.12em] text-slate-700">
                    {roleLabels[profile.role]}
                  </span>
                </div>
                <p className="mt-2 text-xs text-slate-500">{profile.is_active ? "Active" : "Inactive"}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-bold text-slate-950">Recent audit log</h2>
          <div className="mt-4 space-y-3">
            {auditLog.length === 0 ? (
              <p className="text-sm text-slate-500">No audit events recorded yet.</p>
            ) : (
              auditLog.map((entry) => (
                <div key={entry.id} className="rounded-2xl border border-slate-200 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-bold text-slate-900">{entry.action}</p>
                    <span className="text-[0.65rem] font-bold uppercase tracking-[0.12em] text-slate-500">{entry.entity_type}</span>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">{new Date(entry.created_at).toLocaleString()}</p>
                  {entry.entity_id && <p className="mt-2 text-xs text-slate-600">Entity: {entry.entity_id}</p>}
                  <pre className="mt-2 overflow-x-auto rounded-xl bg-slate-100 p-2 text-[0.7rem] text-slate-700">{JSON.stringify(entry.details, null, 2)}</pre>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
