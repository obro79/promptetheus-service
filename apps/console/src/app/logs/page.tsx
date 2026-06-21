import { Activity, Gauge, ListTree, Timer } from "lucide-react";

import { LogsDashboard } from "@/components/logs/logs-dashboard";
import {
  ConsolePage,
  ConsolePageContent,
  ConsolePageHeader,
  ConsoleEyebrow,
  MetricReadout,
  SignalChip,
} from "@/components/common/console-primitives";
import {
  getAnalysis,
  getEvents,
  getIncidents,
  getProjects,
  getSessions,
} from "@/lib/data";
import type { AnalysisResult, TraceEvent } from "@/lib/types";

export const metadata = {
  title: "Logs · Promptetheus",
  description: "Trace logs for instrumented agent runs.",
};

export default function LogsPage() {
  const sessions = getSessions();
  const projects = getProjects();
  const incidents = getIncidents();
  const eventsBySession: Record<string, TraceEvent[]> = {};
  const analysesBySession: Record<string, AnalysisResult | undefined> = {};

  for (const session of sessions) {
    eventsBySession[session.id] = getEvents(session.id);
    analysesBySession[session.id] = getAnalysis(session.id);
  }

  const failed = sessions.filter(
    (s) => s.status === "failed" || s.status === "error",
  ).length;
  const passed = sessions.filter((s) => s.status === "passed").length;

  return (
    <ConsolePage>
      <ConsolePageHeader className="logs-header-spacious">
        <div className="min-w-0">
          <ConsoleEyebrow icon={<ListTree className="size-3.5" strokeWidth={1.8} aria-hidden />}>
            Observability
          </ConsoleEyebrow>
          <h1 className="landing-display-lg max-w-4xl text-[2.1rem] leading-[1.05] sm:text-[2.4rem]">
            Agent observability
          </h1>
          <p className="mt-2.5 max-w-2xl text-sm leading-6 text-muted-foreground">
            Monitor every agent, drill into runs and waterfall traces, and surface
            failure signals to debug agent failures in seconds.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2.5 text-[11px] font-medium text-muted-foreground">
            <SignalChip Icon={Activity} label="Live trace streaming" />
            <SignalChip Icon={Gauge} label="Failure signals attached" />
            <SignalChip Icon={Timer} label="Latency percentiles" />
          </div>
        </div>
        <dl className="grid w-full grid-cols-3 gap-3 lg:w-auto">
          <MetricReadout label="Total" value={sessions.length} />
          <MetricReadout label="Failed" value={failed} tone="warning" />
          <MetricReadout label="Passed" value={passed} tone="signal" />
        </dl>
      </ConsolePageHeader>

      <div aria-hidden className="logs-header-arc" />

      <ConsolePageContent>
        <LogsDashboard
          sessions={sessions}
          projects={projects}
          incidents={incidents}
          eventsBySession={eventsBySession}
          analysesBySession={analysesBySession}
        />
      </ConsolePageContent>
    </ConsolePage>
  );
}
