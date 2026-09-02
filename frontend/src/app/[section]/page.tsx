import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DashboardShell } from "@/components/dashboard-shell";
import { IcpManager } from "@/components/icp-manager";
import { LeadIntake } from "@/components/lead-intake";
import { LeadsWorkspace } from "@/components/leads-workspace";
import { ImportsWorkspace } from "@/components/imports-workspace";
import { ProcessingWorkspace } from "@/components/processing-workspace";
import { EvidenceWorkspace } from "@/components/evidence-workspace";
import { ExportsWorkspace } from "@/components/exports-workspace";
import { ReviewWorkspace } from "@/components/review-workspace";

const sections = { leads: "Leads", "add-leads": "Add leads", imports: "Imports", evidence: "Evidence", icp: "ICP & Personas", processing: "Processing", review: "Review", exports: "Exports", team: "Team", settings: "Settings" } as const;
type SectionKey = keyof typeof sections;
type SectionPageProps = { params: Promise<{ section: string }> };
const isSection = (value: string): value is SectionKey => value in sections;
export function generateStaticParams() { return Object.keys(sections).map((section) => ({ section })); }
export async function generateMetadata({ params }: SectionPageProps): Promise<Metadata> { const { section } = await params; return isSection(section) ? { title: sections[section] } : {}; }
export default async function SectionPage({ params }: SectionPageProps) {
  const { section } = await params; if (!isSection(section)) notFound();
  if (section === "icp") return <DashboardShell activePath="/icp"><IcpManager /></DashboardShell>;
  if (section === "add-leads") return <DashboardShell activePath="/add-leads"><LeadIntake /></DashboardShell>;
  if (section === "leads") return <DashboardShell activePath="/leads"><LeadsWorkspace /></DashboardShell>;
  if (section === "imports") return <DashboardShell activePath="/imports"><ImportsWorkspace /></DashboardShell>;
  if (section === "processing") return <DashboardShell activePath="/processing"><ProcessingWorkspace /></DashboardShell>;
  if (section === "review") return <DashboardShell activePath="/review"><ReviewWorkspace /></DashboardShell>;
  if (section === "evidence") return <DashboardShell activePath="/evidence"><EvidenceWorkspace /></DashboardShell>;
  if (section === "exports") return <DashboardShell activePath="/exports"><ExportsWorkspace /></DashboardShell>;
  return <DashboardShell activePath={`/${section}`}><section className="flex min-h-[28rem] items-center justify-center rounded-3xl border border-slate-200 bg-white p-6 text-center shadow-sm"><div><h1 className="text-3xl font-bold">Ready for its approved implementation phase.</h1></div></section></DashboardShell>;
}
