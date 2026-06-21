import { LogsDashboard } from "@/components/logs/logs-dashboard";
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
  description: "LangSmith-style trace logs for instrumented agent runs.",
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
    <LogsDashboard
      sessions={sessions}
      projects={projects}
      incidents={incidents}
      eventsBySession={eventsBySession}
      analysesBySession={analysesBySession}
    />
  );
}
