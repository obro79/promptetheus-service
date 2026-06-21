import { Activity, Gauge, ListTree, Timer } from "lucide-react";

import { LogsDashboard } from "@/components/logs/logs-dashboard";
import { LogsAutoRefresh } from "@/components/logs/logs-auto-refresh";
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
import { loadLiveLogsData, type LogsData } from "@/lib/live-data";
import type { AnalysisResult, TraceEvent } from "@/lib/types";

export const metadata = {
  title: "Logs · Promptetheus",
  description: "Trace logs for instrumented agent runs.",
};

// Always render fresh so newly ingested runs show up (with the client poller).
export const dynamic = "force-dynamic";

/** Live logs from FastAPI, or the bundled seed when the backend is unreachable. */
async function loadLogsData(): Promise<LogsData & { isLive: boolean }> {
  const live = await loadLiveLogsData();
  if (live) return { ...live, isLive: true };

  const sessions = getSessions();
  const eventsBySession: Record<string, TraceEvent[]> = {};
  const analysesBySession: Record<string, AnalysisResult | undefined> = {};
  for (const session of sessions) {
    eventsBySession[session.id] = getEvents(session.id);
    analysesBySession[session.id] = getAnalysis(session.id);
  }
  return {
    sessions,
    projects: getProjects(),
    incidents: getIncidents(),
    eventsBySession,
    analysesBySession,
    isLive: false,
  };
}

export default async function LogsPage() {
  const { sessions, projects, incidents, eventsBySession, analysesBySession, isLive } =
    await loadLogsData();

  const failed = sessions.filter(
    (s) => s.status === "failed" || s.status === "error",
  ).length;
  const passed = sessions.filter((s) => s.status === "passed").length;

  return (
    <ConsolePage>
      <ConsolePageHeader>
        <div className="min-w-0">
          <ConsoleEyebrow icon={<ListTree className="size-3.5" strokeWidth={1.8} aria-hidden />}>
            Trace logs
          </ConsoleEyebrow>
          <h1 className="landing-display-lg max-w-4xl">Agent run logs</h1>
          <p className="mt-5 max-w-2xl text-sm leading-6 text-muted-foreground">
            Search, filter, and inspect instrumented runs with waterfall traces
            and event-level payloads. Use this view when you need LangSmith-style
            log exploration without leaving the console.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-2.5 text-[11px] font-medium text-muted-foreground">
            {isLive ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-success/10 px-2 py-1 text-[11px] font-semibold text-success">
                <span className="size-1.5 animate-pulse rounded-full bg-success" /> Live · ingesting
              </span>
            ) : null}
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

      <ConsolePageContent>
        {isLive ? <LogsAutoRefresh intervalMs={4000} /> : null}
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
