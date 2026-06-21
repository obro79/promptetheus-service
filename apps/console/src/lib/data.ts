/**
 * Mock data access layer. Reads from the repo-root /data folder.
 * Mirrors the FastAPI endpoint surface so swapping to the real API later
 * is a one-file change (replace these bodies with fetch() calls).
 */
import type {
  AnalysisResult,
  EvalScoreboard,
  EvalScoreboardRow,
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

// ── Eval scoreboard ───────────────────────────────────────────────────────────
// Mirrors GET /api/evals/scoreboard. Derived from the healed-state incidents in
// the seed so the page renders rich demo data; swapping to the live endpoint is
// a one-line change (see fetchEvalScoreboard in promptetheus-api.ts).

function _hash(value: string): number {
  let h = 0;
  for (let i = 0; i < value.length; i += 1) h = (h * 31 + value.charCodeAt(i)) >>> 0;
  return h;
}

function _between(value: string, lo: number, hi: number): number {
  return Number((lo + ((_hash(value) % 1000) / 1000) * (hi - lo)).toFixed(2));
}

/** Per-incident eval verdicts + workspace rollup (mock of the scoreboard API). */
export function getEvalScoreboard(): EvalScoreboard {
  const healed = incidents.filter((i) =>
    i.status === "fixing" || i.status === "fixed" || i.status === "triaged",
  );

  const rows: EvalScoreboardRow[] = healed.map((incident, index) => {
    // One representative blocked fix near the end: the judge caught a candidate
    // that still contradicted the evidence, so the gate held the PR back.
    const blocked = healed.length > 2 && index === healed.length - 1;
    const fallback = incident.status === "triaged" && index % 2 === 0;
    const afterPassed = !blocked;
    return {
      incident_id: incident.id,
      label: incident.label,
      before_passed: false,
      after_passed: afterPassed,
      confidence: afterPassed
        ? _between(incident.id, 0.82, 0.97)
        : _between(incident.id, 0.18, 0.44),
      attempts: 1 + (_hash(incident.id) % 3),
      fallback,
      passed: afterPassed,
      reason: afterPassed
        ? "Fixed answer is consistent with the retrieved evidence."
        : "Candidate still contradicts the retrieved evidence — gate blocked the PR.",
    };
  });

  const total = rows.length;
  const passed = rows.filter((row) => row.passed).length;
  const flips = rows.filter((row) => !row.before_passed && row.after_passed).length;
  const fallbackCount = rows.filter((row) => row.fallback).length;
  const avgConfidence = total
    ? Number((rows.reduce((acc, row) => acc + row.confidence, 0) / total).toFixed(2))
    : 0;

  return {
    total,
    passed,
    pass_rate: total ? Number((passed / total).toFixed(2)) : 0,
    flips,
    avg_confidence: avgConfidence,
    fallback_count: fallbackCount,
    rows,
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
