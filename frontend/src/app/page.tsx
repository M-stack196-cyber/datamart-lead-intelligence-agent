import { DashboardShell } from "@/components/dashboard-shell";

const foundationItems = [
  {
    title: "Workspace ready",
    description: "The frontend and API foundations are configured for local development.",
  },
  {
    title: "Data stays truthful",
    description: "No sample metrics, charts, leads, or business results are shown.",
  },
  {
    title: "Phase boundaries set",
    description: "Future product areas are visible as placeholders and remain inactive.",
  },
];

export default function DashboardPage() {
  return (
    <DashboardShell activePath="/">
      <div className="space-y-8">
        <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <div className="max-w-3xl">
            <span className="inline-flex rounded-full bg-teal-50 px-3 py-1 text-xs font-bold uppercase tracking-[0.18em] text-teal-700">
              Phase 1 foundation
            </span>
            <h1 className="mt-5 text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">
              Lead intelligence, built on a clear foundation.
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-slate-600">
              This workspace is ready for phased development. Operational data and
              workflows will appear only after their corresponding phases are approved
              and implemented.
            </p>
          </div>
        </section>

        <section aria-labelledby="foundation-heading">
          <div className="mb-4 flex items-end justify-between gap-4">
            <div>
              <p className="text-sm font-semibold text-teal-700">Project status</p>
              <h2 id="foundation-heading" className="mt-1 text-xl font-bold text-slate-950">
                Foundation checkpoints
              </h2>
            </div>
            <span className="hidden text-sm text-slate-500 sm:block">No business data connected</span>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            {foundationItems.map((item, index) => (
              <article
                key={item.title}
                className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-950 text-sm font-bold text-white">
                  {String(index + 1).padStart(2, "0")}
                </div>
                <h3 className="mt-5 font-bold text-slate-950">{item.title}</h3>
                <p className="mt-2 text-sm leading-6 text-slate-600">{item.description}</p>
              </article>
            ))}
          </div>
        </section>
      </div>
    </DashboardShell>
  );
}
