"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type Role = "admin" | "manager" | "sales";
type Profile = {
  id: string;
  email: string;
  full_name: string | null;
  role: Role;
  is_active: boolean;
  created_at: string;
};

const roleLabels: Record<Role, string> = {
  admin: "Admin",
  manager: "Manager",
  sales: "Sales",
};

const roleColors: Record<Role, string> = {
  admin: "bg-violet-50 text-violet-800", 
  manager: "bg-amber-50 text-amber-800",
  sales: "bg-teal-50 text-teal-800",
};

export function TeamWorkspace() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [currentRole, setCurrentRole] = useState<Role | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!supabase) return;
    setLoading(true);
    setError("");

    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) {
      setLoading(false);
      return;
    }

    const { data: roleData, error: roleError } = await supabase
      .from("profiles")
      .select("role")
      .eq("id", userData.user.id)
      .single();

    if (roleError) {
      setError(roleError.message);
      setLoading(false);
      return;
    }

    const nextRole = (roleData?.role as Role | undefined) ?? null;
    setCurrentRole(nextRole);

    if (nextRole !== "admin" && nextRole !== "manager") {
      setProfiles([]);
      setLoading(false);
      return;
    }

    const { data, error: profilesError } = await supabase
      .from("profiles")
      .select("id,email,full_name,role,is_active,created_at")
      .order("created_at", { ascending: false });

    if (profilesError) {
      setError(profilesError.message);
    } else {
      setProfiles((data ?? []) as Profile[]);
    }

    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    const task = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(task);
  }, [load]);

  async function updateRole(profileId: string, nextRole: Role) {
    if (!supabase || currentRole !== "admin") return;
    setUpdatingId(profileId);
    setError("");
    setNotice("");

    const { error: rpcError } = await supabase.rpc("set_user_role", {
      target_user_id: profileId,
      new_role: nextRole,
    });

    setUpdatingId(null);
    if (rpcError) {
      setError(rpcError.message);
      return;
    }

    setNotice("Role updated for the selected team member.");
    await load();
  }

  const canManageRoles = currentRole === "admin";

  return (
    <section className="space-y-6">
      <header className="rounded-3xl bg-slate-950 p-7 text-white">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Team access</p>
        <h1 className="mt-3 text-3xl font-bold">Team and role controls</h1>
        <p className="mt-3 text-sm text-slate-300">
          Review the team roster and enforce role boundaries for admin-managed access.
        </p>
      </header>

      {error && <p className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      {notice && <p className="rounded-xl bg-teal-50 p-4 text-sm text-teal-800">{notice}</p>}

      <div className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
        {loading ? (
          <p className="p-4 text-sm text-slate-500">Loading team roster...</p>
        ) : currentRole === "sales" ? (
          <div className="rounded-2xl bg-slate-50 p-5 text-sm text-slate-600">
            Your account is restricted to sales visibility. Only admin and manager roles can view the full team roster.
          </div>
        ) : profiles.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">No profiles are visible to this account.</p>
        ) : (
          <div className="space-y-3">
            {profiles.map((profile) => (
              <article key={profile.id} className="flex flex-col gap-3 rounded-2xl border border-slate-200 p-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="text-lg font-bold text-slate-950">{profile.full_name || profile.email}</p>
                  <p className="text-sm text-slate-600">{profile.email}</p>
                </div>

                <div className="flex flex-col gap-3 md:flex-row md:items-center">
                  <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${roleColors[profile.role]}`}>
                    {roleLabels[profile.role]}
                  </span>
                  <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${profile.is_active ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"}`}>
                    {profile.is_active ? "Active" : "Inactive"}
                  </span>

                  {canManageRoles ? (
                    <select
                      aria-label={`Change team role for ${profile.email}`}
                      value={profile.role}
                      onChange={(event) => void updateRole(profile.id, event.target.value as Role)}
                      disabled={updatingId === profile.id}
                      className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 outline-none focus:border-teal-500 disabled:opacity-60"
                    >
                      <option value="admin">Admin</option>
                      <option value="manager">Manager</option>
                      <option value="sales">Sales</option>
                    </select>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
