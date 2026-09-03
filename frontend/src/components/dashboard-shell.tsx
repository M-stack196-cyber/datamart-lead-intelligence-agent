import Link from "next/link";
import type { ReactNode } from "react";
import { AuthGate } from "@/components/auth-gate";
import { AccountBadge } from "@/components/account-badge";

const navigation = [
  { label: "Dashboard", href: "/", marker: "D" },
  { label: "Leads", href: "/leads", marker: "L" },
  { label: "Add leads", href: "/add-leads", marker: "+" },
  { label: "Imports", href: "/imports", marker: "I" },
  { label: "Evidence", href: "/evidence", marker: "E" },
  { label: "ICP & Personas", href: "/icp", marker: "C" },
  { label: "Processing", href: "/processing", marker: "P" },
  { label: "Review", href: "/review", marker: "R" },
  { label: "Outreach", href: "/outreach", marker: "O" },
  { label: "Exports", href: "/exports", marker: "X" },
  { label: "Team", href: "/team", marker: "T" },
  { label: "Settings", href: "/settings", marker: "S" },
] as const;

type DashboardShellProps = {
  activePath: string;
  children: ReactNode;
};

export function DashboardShell({ activePath, children }: DashboardShellProps) {
  return (
    <AuthGate>
      <div className="min-h-screen bg-slate-100 lg:grid lg:grid-cols-[17rem_1fr]">
      <aside className="bg-slate-950 text-white lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col">
        <div className="flex h-20 items-center gap-3 border-b border-white/10 px-5 lg:px-6">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-400 font-black text-slate-950">
            DM
          </div>
          <div>
            <p className="font-bold tracking-tight">Datamart</p>
            <p className="text-xs text-slate-400">Lead Intelligence</p>
          </div>
        </div>

        <nav aria-label="Primary navigation" className="overflow-x-auto p-3 lg:flex-1 lg:overflow-y-auto lg:p-4">
          <ul className="flex min-w-max gap-1 lg:min-w-0 lg:flex-col">
            {navigation.map((item) => {
              const isActive = item.href === activePath;

              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={isActive ? "page" : undefined}
                    className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold transition-colors ${
                      isActive
                        ? "bg-teal-400 text-slate-950"
                        : "text-slate-300 hover:bg-white/10 hover:text-white"
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`flex h-7 w-7 items-center justify-center rounded-lg text-[0.65rem] font-black ${
                        isActive ? "bg-slate-950/10" : "bg-white/10"
                      }`}
                    >
                      {item.marker}
                    </span>
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="hidden border-t border-white/10 p-6 lg:block">
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-teal-300">Workspace</p>
          <p className="mt-2 text-sm text-slate-400">Versioned ICP enabled</p>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="flex min-h-20 items-center justify-between border-b border-slate-200 bg-white px-5 sm:px-8">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-teal-700">Datamart workspace</p>
            <p className="mt-1 text-sm text-slate-500">Lead Intelligence Agent</p>
          </div>
          <AccountBadge />
        </header>
        <main className="p-5 sm:p-8 lg:p-10">{children}</main>
      </div>
      </div>
    </AuthGate>
  );
}
