import type { Metadata } from "next";
import { Activity, Inbox, ShieldCheck, Sparkles } from "lucide-react";

import { getIncidents } from "@/lib/data";
import {
  ConsolePage,
  ConsolePageContent,
  ConsolePageHeader,
  ConsoleEyebrow,
  MetricReadout,
  SignalChip,
} from "@/components/common/console-primitives";
import { IncidentsView } from "@/components/incidents/incidents-view";

export const metadata: Metadata = {
  title: "Incidents · Promptetheus",
  description: "Clustered agent failures detected across your sessions.",
};

export default function IncidentsPage() {
  const incidents = getIncidents();

  const open = incidents.filter(
    (i) => i.status === "open" || i.status === "triaged" || i.status === "fixing",
  ).length;
  const fixed = incidents.filter((i) => i.status === "fixed").length;
  const affected = incidents.reduce(
    (acc, i) => acc + i.session_ids.length,
    0,
  );

  return (
    <ConsolePage>
      <ConsolePageHeader>
        <div className="min-w-0">
          <ConsoleEyebrow icon={<Inbox className="size-3.5" strokeWidth={1.8} aria-hidden />}>
            Failure inbox
          </ConsoleEyebrow>
          <h1 className="display max-w-4xl text-5xl leading-[0.92] text-foreground sm:text-6xl lg:text-7xl">
            Incidents requiring judgment
          </h1>
          <p className="mt-5 max-w-2xl text-sm leading-6 text-muted-foreground">
            Repeated agent failures, ranked by evidence quality, replayability,
            and fix coverage. Each cluster is treated like a case file, not
            another dashboard row.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-2.5 text-[11px] font-medium text-muted-foreground">
            <SignalChip Icon={Sparkles} label="Replay artifacts attached" />
            <SignalChip Icon={ShieldCheck} label="Regression coverage tracked" />
            <SignalChip Icon={Activity} label="Live sessions streaming" />
          </div>
        </div>
        <dl className="grid w-full grid-cols-3 gap-3 lg:w-auto">
          <MetricReadout label="Unresolved" value={open} tone="warning" />
          <MetricReadout label="Resolved" value={fixed} tone="signal" />
          <MetricReadout label="Impacted runs" value={affected} />
        </dl>
      </ConsolePageHeader>

      <ConsolePageContent>
        <IncidentsView incidents={incidents} />
      </ConsolePageContent>
    </ConsolePage>
  );
}
