"use client";

import { useMemo, useState } from "react";
import Papa from "papaparse";
import Link from "next/link";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type LeadRow = {
  linkedin_url?: string;
  company_name?: string;
  person_name?: string;
  title?: string;
  company_url?: string;
  email?: string;
  country?: string;
  industry?: string;
};

type IntakeResult = { import_id: string; total: number; accepted: number; rejected: number; errors: { row: number; reason: string }[] };

const csvColumns = ["linkedin_url", "company_name", "person_name", "title", "company_url", "email", "country", "industry"];

export function LeadIntake() {
  const supabase = useMemo(() => createBrowserSupabaseClient(), []);
  const [mode, setMode] = useState<"links" | "csv">("links");
  const [links, setLinks] = useState("");
  const [csvRows, setCsvRows] = useState<LeadRow[]>([]);
  const [csvName, setCsvName] = useState("");
  const [parseError, setParseError] = useState("");
  const [result, setResult] = useState<IntakeResult | null>(null);
  const [busy, setBusy] = useState(false);

  function selectCsv(file?: File) {
    setResult(null);
    setParseError("");
    setCsvRows([]);
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv")) return setParseError("Select a .csv file.");

    Papa.parse<LeadRow>(file, {
      header: true,
      skipEmptyLines: true,
      transformHeader: (header) => header.trim().toLowerCase().replaceAll(" ", "_"),
      complete(output) {
        const unknown = output.meta.fields?.filter((field) => !csvColumns.includes(field)) ?? [];
        if (output.errors.length) return setParseError(output.errors[0].message);
        if (!output.data.length) return setParseError("The CSV contains no lead rows.");
        if (output.data.length > 100) return setParseError("The MVP accepts at most 100 leads per import.");
        setCsvName(file.name);
        setCsvRows(output.data);
        if (unknown.length) setParseError(`Ignored columns: ${unknown.join(", ")}`);
      },
      error(error) { setParseError(error.message); },
    });
  }

  async function submit() {
    if (!supabase) return;
    const rows: LeadRow[] = mode === "links"
      ? links.split(/\r?\n/).map((value) => value.trim()).filter(Boolean).map((linkedin_url) => ({ linkedin_url }))
      : csvRows;
    if (!rows.length) return setParseError(mode === "links" ? "Paste at least one LinkedIn profile URL." : "Select a CSV file first.");
    if (rows.length > 100) return setParseError("The MVP accepts at most 100 leads per import.");

    setBusy(true);
    setResult(null);
    setParseError("");
    const { data, error } = await supabase.rpc("ingest_leads", {
      rows,
      intake_source: mode === "links" ? "profile_links" : "csv",
      intake_file_name: mode === "links" ? "manual-profile-links" : csvName,
    });
    setBusy(false);
    if (error) return setParseError(error.message);
    setResult(data as IntakeResult);
    if (mode === "links") setLinks("");
  }

  return (
    <section className="space-y-6">
      <header className="rounded-3xl bg-slate-950 p-7 text-white sm:p-8">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Lead intake</p>
        <h1 className="mt-3 text-3xl font-bold">Add leads safely</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">Paste LinkedIn profile links or upload a CSV. Accepted leads are deduplicated, saved, and queued immediately. No LinkedIn scraping or messaging occurs.</p>
      </header>

      <div className="rounded-3xl border border-slate-200 bg-white shadow-sm">
        <div className="flex gap-2 border-b border-slate-200 p-4">
          <button type="button" onClick={() => setMode("links")} className={`rounded-xl px-4 py-2 text-sm font-bold ${mode === "links" ? "bg-teal-600 text-white" : "bg-slate-100 text-slate-600"}`}>Profile links</button>
          <button type="button" onClick={() => setMode("csv")} className={`rounded-xl px-4 py-2 text-sm font-bold ${mode === "csv" ? "bg-teal-600 text-white" : "bg-slate-100 text-slate-600"}`}>CSV upload</button>
        </div>

        <div className="p-5 sm:p-7">
          {mode === "links" ? <label className="block text-sm font-bold text-slate-800">LinkedIn profile URLs<textarea value={links} onChange={(event) => setLinks(event.target.value)} rows={9} placeholder={"https://www.linkedin.com/in/person-one\nhttps://www.linkedin.com/in/person-two"} className="mt-2 w-full rounded-2xl border border-slate-300 p-4 font-mono text-sm font-normal outline-none focus:border-teal-600" /><span className="mt-2 block text-xs font-normal text-slate-500">One public profile URL per line · maximum 100</span></label> : <div><label className="flex min-h-48 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 p-6 text-center hover:border-teal-500"><span className="text-lg font-bold text-slate-800">Choose a CSV file</span><span className="mt-2 text-sm text-slate-500">Required: at least linkedin_url, company_url, or company_name</span><input type="file" accept=".csv,text/csv" onChange={(event) => selectCsv(event.target.files?.[0])} className="sr-only" /></label>{csvName && <p className="mt-3 text-sm font-semibold text-teal-700">{csvName} · {csvRows.length} rows ready</p>}<p className="mt-3 text-xs leading-5 text-slate-500">Supported headers: {csvColumns.join(", ")}</p></div>}

          {parseError && <p role="alert" className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">{parseError}</p>}
          <button type="button" onClick={submit} disabled={busy} className="mt-6 rounded-xl bg-teal-600 px-5 py-3 text-sm font-bold text-white hover:bg-teal-700 disabled:opacity-60">{busy ? "Importing..." : "Import and queue leads"}</button>
        </div>
      </div>

      {result && <section className="rounded-3xl border border-teal-200 bg-teal-50 p-6"><p className="text-sm font-bold text-teal-950">Import completed</p><div className="mt-4 grid gap-3 sm:grid-cols-3">{[[result.total,"Total"],[result.accepted,"Accepted"],[result.rejected,"Rejected"]].map(([value,label]) => <div key={label} className="rounded-xl bg-white p-4"><p className="text-2xl font-black">{value}</p><p className="text-xs text-slate-500">{label}</p></div>)}</div>{result.errors.length > 0 && <ul className="mt-4 space-y-1 text-sm text-red-800">{result.errors.map((error) => <li key={`${error.row}-${error.reason}`}>Row {error.row}: {error.reason}</li>)}</ul>}<div className="mt-5 flex gap-3 text-sm font-bold text-teal-800"><Link href="/leads">View leads</Link><Link href="/imports">View import record</Link></div></section>}
    </section>
  );
}
