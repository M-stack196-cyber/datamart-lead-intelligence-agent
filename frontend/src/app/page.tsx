import { DashboardShell } from "@/components/dashboard-shell";

const architecture = [
  {
    title: "Lead data",
    provider: "Vibe Prospecting",
    detail: "Discovery, contact matching, company enrichment, and business signals.",
  },
  {
    title: "Intelligence",
    provider: "AWS Bedrock",
    detail: "Evidence-grounded analysis and outreach drafting after deterministic scoring.",
  },
  {
    title: "Data and identity",
    provider: "Supabase",
    detail: "PostgreSQL, authentication, role enforcement, and audit-ready records.",
  },
];

const safeguards = [
  "Hard disqualifiers stay deterministic",
  "Every important conclusion links to evidence",
  "Missing facts remain unknown",
  "No LinkedIn scraping or automatic messaging",
];

export default function DashboardPage() {
  return (
    <DashboardShell activePath="/">
      <div className="space-y-8">
        <section className="overflow-hidden rounded-3xl bg-slate-950 p-6 text-white shadow-sm sm:p-8">
          <div className="max-w-3xl">
            <span className="inline-flex rounded-full bg-teal-300 px-3 py-1 text-xs font-black uppercase tracking-[0.18em] text-slate-950">
              New foundation
            </span>
            <h1 className="mt-5 text-3xl font-bold tracking-tight sm:text-4xl">
              Datamart Lead Intelligence Agent
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-slate-300">
              The approved architecture is in place for evidence-backed lead discovery,
              qualification, scoring, and outreach preparation. Business workflows remain
              inactive until their implementation phases are approved.
            </p>
          </div>
        </section>

        <section aria-labelledby="architecture-heading">
          <p className="text-sm font-semibold text-teal-700">Approved providers</p>
          <h2 id="architecture-heading" className="mt-1 text-xl font-bold text-slate-950">
            Architecture boundaries
          </h2>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            {architecture.map((item) => (
              <article key={item.title} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">{item.title}</p>
                <h3 className="mt-3 text-lg font-bold text-slate-950">{item.provider}</h3>
                <p className="mt-2 text-sm leading-6 text-slate-600">{item.detail}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <p className="text-sm font-semibold text-teal-700">Non-negotiable safeguards</p>
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {safeguards.map((item) => (
              <li key={item} className="rounded-xl bg-slate-50 px-4 py-3 text-sm font-medium text-slate-700">
                {item}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </DashboardShell>
  );
}
