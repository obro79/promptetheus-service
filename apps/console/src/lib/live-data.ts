/**
 * Server-side live read layer. Fetches the logs surface (sessions + events +
 * analysis + incidents) from the live FastAPI gateway, normalizing the leaner
 * API rows into the console's richer view types. Returns `null` on any failure
 * (API not configured, backend down, empty) so callers fall back to the bundled
 * seed — live when the backend is up, safe when it isn't.
 */
import type {
  AnalysisResult,
  Incident,
  Project,
  TraceEvent,
  TraceSession,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_PROMPTETHEUS_API_URL;
const TOKEN = process.env.NEXT_PUBLIC_PROMPTETHEUS_CONSOLE_TOKEN;

type RawSession = { id: string; incident_id?: string | null; [k: string]: unknown };
type RawIncident = {
  id: string;
  label?: string;
  title?: string;
  root_cause?: string | null;
  labels?: string[];
  session_ids?: string[];
  representative_session_id?: string;
  fingerprint?: string;
  pr_url?: string | null;
  created_at?: string;
  updated_at?: string;
  [k: string]: unknown;
};

async function api<T>(path: string): Promise<T | null> {
  if (!API_URL || !TOKEN) return null;
  try {
    const res = await fetch(`${API_URL.replace(/\/$/, "")}${path}`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${TOKEN}`, Accept: "application/json" },
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

function titleFromLabel(label: string): string {
  return label.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export interface LogsData {
  sessions: TraceSession[];
  projects: Project[];
  incidents: Incident[];
  eventsBySession: Record<string, TraceEvent[]>;
  analysesBySession: Record<string, AnalysisResult | undefined>;
}

export async function loadLiveLogsData(): Promise<LogsData | null> {
  const sessRes = await api<{ sessions: RawSession[] }>("/api/sessions");
  if (!sessRes?.sessions?.length) return null; // nothing live → use seed

  const [incRes, projRes] = await Promise.all([
    api<{ incidents: RawIncident[] }>("/api/incidents"),
    api<{ projects: Project[] }>("/api/projects"),
  ]);

  const eventsBySession: Record<string, TraceEvent[]> = {};
  const analysesBySession: Record<string, AnalysisResult | undefined> = {};
  await Promise.all(
    sessRes.sessions.map(async (s) => {
      const [ev, an] = await Promise.all([
        api<{ events: TraceEvent[] }>(`/api/traces/${s.id}/events`),
        api<{ analysis: AnalysisResult }>(`/api/traces/${s.id}/analysis`),
      ]);
      eventsBySession[s.id] = ev?.events ?? [];
      analysesBySession[s.id] = an?.analysis ?? undefined;
    }),
  );

  // Reverse-map incidents → their sessions for run linking, and backfill the
  // display fields the backend incident row doesn't carry (title/root_cause/
  // labels come from the representative session's analysis).
  const sessionIncidentId: Record<string, string> = {};
  const incidents: Incident[] = (incRes?.incidents ?? []).map((inc) => {
    for (const sid of inc.session_ids ?? []) sessionIncidentId[sid] = inc.id;
    const analysis = inc.representative_session_id
      ? analysesBySession[inc.representative_session_id]
      : undefined;
    const now = new Date().toISOString();
    return {
      ...inc,
      title: inc.title ?? titleFromLabel(inc.label ?? "incident"),
      root_cause: inc.root_cause ?? analysis?.root_cause ?? null,
      labels: inc.labels ?? analysis?.labels ?? [],
      fingerprint: inc.fingerprint ?? inc.id,
      pr_url: inc.pr_url ?? null,
      created_at: inc.created_at ?? now,
      updated_at: inc.updated_at ?? now,
    } as Incident;
  });

  const sessions: TraceSession[] = sessRes.sessions.map(
    (s) => ({ ...s, incident_id: s.incident_id ?? sessionIncidentId[s.id] ?? null }) as TraceSession,
  );

  return {
    sessions,
    projects: projRes?.projects ?? [],
    incidents,
    eventsBySession,
    analysesBySession,
  };
}
