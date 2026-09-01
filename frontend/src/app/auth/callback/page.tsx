"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

export default function AuthCallbackPage() {
  const router = useRouter();
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [message, setMessage] = useState("Completing secure sign-in...");

  useEffect(() => {
    if (!supabase) {
      return;
    }

    const task = window.setTimeout(async () => {
      const { data, error } = await supabase.auth.getSession();
      if (error || !data.session) {
        setMessage("The sign-in link is invalid or expired. Return to login and request a new link.");
        return;
      }
      router.replace("/");
      router.refresh();
    }, 0);

    return () => window.clearTimeout(task);
  }, [router, supabase]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 p-6">
      <section className="max-w-lg rounded-3xl bg-white p-8 text-center shadow-xl">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-700">Datamart authentication</p>
        <h1 className="mt-3 text-2xl font-bold text-slate-950">{supabase ? message : "Supabase configuration is missing."}</h1>
      </section>
    </main>
  );
}
