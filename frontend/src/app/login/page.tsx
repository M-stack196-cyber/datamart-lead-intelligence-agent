"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supabase) return setMessage("Supabase browser configuration is missing.");
    setLoading(true);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (error) return setMessage(error.message);
    router.replace("/");
    router.refresh();
  }

  async function sendMagicLink() {
    if (!supabase || !email) return setMessage("Enter your approved Datamart email first.");
    setLoading(true);
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
    setLoading(false);
    setMessage(error ? error.message : "Check your email for the secure sign-in link.");
  }

  return (
    <main className="grid min-h-screen bg-slate-950 lg:grid-cols-[1.1fr_0.9fr]">
      <section className="hidden p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-xl bg-teal-400 font-black text-slate-950">DM</span><div><p className="font-bold">Datamart</p><p className="text-xs text-slate-400">Lead Intelligence</p></div></div>
        <div className="max-w-xl"><p className="text-xs font-bold uppercase tracking-[0.2em] text-teal-300">Secure sales workspace</p><h1 className="mt-5 text-5xl font-bold leading-tight">Evidence-backed leads, scored with discipline.</h1><p className="mt-5 text-lg leading-8 text-slate-300">Authentication and role controls protect Datamart&apos;s lead research, ICP rules, and outreach drafts.</p></div>
        <p className="text-xs text-slate-500">Research, score, and draft only. No automatic LinkedIn messaging.</p>
      </section>
      <section className="flex items-center justify-center bg-slate-100 p-6 sm:p-10">
        <form onSubmit={signIn} className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-7 shadow-xl sm:p-9">
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-700">Datamart team access</p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-slate-950">Sign in</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">Use the account approved by your Datamart administrator.</p>
          <label className="mt-7 block text-sm font-bold text-slate-700">Email<input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 font-normal outline-none focus:border-teal-600" /></label>
          <label className="mt-4 block text-sm font-bold text-slate-700">Password<input required type="password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 font-normal outline-none focus:border-teal-600" /></label>
          {message && <p role="status" className="mt-4 rounded-xl bg-slate-100 p-3 text-sm text-slate-700">{message}</p>}
          <button disabled={loading} className="mt-6 w-full rounded-xl bg-teal-600 px-4 py-3 text-sm font-bold text-white hover:bg-teal-700 disabled:opacity-60">{loading ? "Please wait..." : "Sign in securely"}</button>
          <button type="button" disabled={loading} onClick={sendMagicLink} className="mt-3 w-full rounded-xl border border-slate-300 px-4 py-3 text-sm font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-60">Email me a magic link</button>
        </form>
      </section>
    </main>
  );
}
