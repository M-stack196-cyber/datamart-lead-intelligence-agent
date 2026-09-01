"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import type { User } from "@supabase/supabase-js";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type AuthGateProps = { children: ReactNode };

export function AuthGate({ children }: AuthGateProps) {
  const router = useRouter();
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(Boolean(supabase));

  useEffect(() => {
    if (!supabase) {
      return;
    }

    void supabase.auth.getUser().then(({ data }) => {
      setUser(data.user);
      setLoading(false);
      if (!data.user) router.replace("/login");
    });

    const { data: listener } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
      if (!session?.user) router.replace("/login");
    });

    return () => listener.subscription.unsubscribe();
  }, [router, supabase]);

  if (!supabase) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-100 p-6">
        <section className="max-w-lg rounded-3xl border border-amber-200 bg-white p-8 shadow-sm">
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-amber-700">Configuration required</p>
          <h1 className="mt-3 text-2xl font-bold text-slate-950">Connect the dashboard to Supabase</h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            Add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY to the ignored local environment file, then restart the frontend.
          </p>
        </section>
      </main>
    );
  }

  if (loading || !user) {
    return <main className="flex min-h-screen items-center justify-center bg-slate-950 text-sm font-bold text-teal-300">Checking secure workspace access...</main>;
  }

  return children;
}
