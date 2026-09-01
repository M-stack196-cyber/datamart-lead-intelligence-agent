"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type Profile = { full_name: string | null; email: string; role: "admin" | "manager" | "sales" };

export function AccountBadge() {
  const router = useRouter();
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [profile, setProfile] = useState<Profile | null>(null);

  useEffect(() => {
    if (!supabase) return;
    void supabase.auth.getUser().then(async ({ data }) => {
      if (!data.user) return;
      const { data: row } = await supabase.from("profiles").select("full_name,email,role").eq("id", data.user.id).single();
      if (row) setProfile(row as Profile);
    });
  }, [supabase]);

  async function signOut() {
    if (!supabase) return;
    await supabase.auth.signOut();
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="flex items-center gap-3">
      {profile && <span className="hidden text-right sm:block"><span className="block text-xs font-bold text-slate-700">{profile.full_name || profile.email}</span><span className="block text-[0.65rem] font-bold uppercase tracking-[0.14em] text-teal-700">{profile.role}</span></span>}
      <button type="button" onClick={signOut} className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100">Sign out</button>
    </div>
  );
}
