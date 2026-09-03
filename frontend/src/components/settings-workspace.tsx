"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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
      const [{ data: profilesData, error: profilesError }, { data: auditData, error: auditError }] = await Promise.all([
        supabase.from("profiles").select("id,email,full_name,role,is_active").order("created_at", { ascending: false }),
        supabase.from("audit_log").select("id,action,entity_type,entity_id,details,created_at,actor_id").order("created_at", { ascending: false }).limit(20),
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
    } else {
      setProfiles([]);
      setAuditLog([]);
    }

    setLoading(false);
  }, [error, supabase]);

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
