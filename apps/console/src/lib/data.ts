/**
 * Mock data access layer. Reads from the repo-root /data folder.
 * Mirrors the FastAPI endpoint surface so swapping to the real API later
 * is a one-file change (replace these bodies with fetch() calls).
 */
import type {
  AnalysisResult,
  Incident,
  IncidentContext,
  Project,
  RegressionRun,
  ReplayArtifact,
  TraceEvent,
  TraceSession,
  Workspace,
} from "./types";

import workspaceData from "@data/workspace.json";
import sessionsData from "@data/sessions.json";
import eventsData from "@data/events.json";
import incidentsData from "@data/incidents.json";
import analysisData from "@data/analysis.json";
import artifactsData from "@data/artifacts.json";
import regressionData from "@data/regression.json";

const workspace = workspaceData as unknown as { workspace: Workspace; projects: Project[] };
const sessions = sessionsData as unknown as TraceSession[];
const eventsBySession = eventsData as unknown as Record<string, TraceEvent[]>;
const incidents = incidentsData as unknown as Incident[];
const analysisBySession = analysisData as unknown as Record<string, AnalysisResult>;
const artifactsBySession = artifactsData as unknown as Record<string, ReplayArtifact[]>;
const regressionByIncident = regressionData as unknown as Record<string, RegressionRun[]>;

export function getWorkspace(): Workspace {
  return workspace.workspace;
}

export function getProjects(): Project[] {
  return workspace.projects;
}

export function getProject(id: string): Project | undefined {
  return workspace.projects.find((p) => p.id === id);
}

export function getSessions(): TraceSession[] {
  return [...sessions].sort((a, b) => b.started_at.localeCompare(a.started_at));
}

export function getSession(id: string): TraceSession | undefined {
  return sessions.find((s) => s.id === id);
}

export function getEvents(sessionId: string): TraceEvent[] {
  return eventsBySession[sessionId] ?? [];
}

export function getAnalysis(sessionId: string): AnalysisResult | undefined {
  return analysisBySession[sessionId];
}

export function getArtifacts(sessionId: string): ReplayArtifact[] {
  return artifactsBySession[sessionId] ?? [];
}

export function getIncidents(): Incident[] {
  return [...incidents].sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function getIncident(id: string): Incident | undefined {
  return incidents.find((i) => i.id === id);
}

export function getRegressionRuns(incidentId: string): RegressionRun[] {
  return regressionByIncident[incidentId] ?? [];
}

export function getIncidentContext(id: string): IncidentContext | undefined {
  const incident = getIncident(id);
  if (!incident) return undefined;
  const sessionId = incident.representative_session_id;
  const session = getSession(sessionId);
  const analysis = getAnalysis(sessionId);
  if (!session || !analysis) return undefined;
  return {
    incident,
    analysis,
    session,
    events: getEvents(sessionId),
    artifacts: getArtifacts(sessionId),
    regression_runs: getRegressionRuns(id),
  };
}

/** Stats for the dashboard hero. */
export function getOverviewStats() {
  const open = incidents.filter((i) => i.status === "open").length;
  const fixed = incidents.filter((i) => i.status === "fixed").length;
  const failed = sessions.filter((s) => s.status === "failed").length;
  return {
    sessions: sessions.length,
    incidents: incidents.length,
    openIncidents: open,
    fixedIncidents: fixed,
    failedSessions: failed,
  };
}
