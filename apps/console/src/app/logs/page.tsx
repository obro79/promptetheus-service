import { ListTree } from "lucide-react";

import { LogsDashboard } from "@/components/logs/logs-dashboard";
import {
  ConsolePage,
  ConsolePageContent,
  ConsolePageHeader,
  ConsoleEyebrow,
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

  return (
    <ConsolePage>
      <ConsolePageHeader narrow>
        <div className="min-w-0">
          <ConsoleEyebrow icon={<ListTree className="size-3.5" strokeWidth={1.8} aria-hidden />}>
            Trace logs
          </ConsoleEyebrow>
          <h1 className="text-2xl font-serif tracking-tight text-foreground">Agent run logs</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Search, filter, and inspect runs with waterfall traces and event payloads.
          </p>
        </div>
      </ConsolePageHeader>

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
