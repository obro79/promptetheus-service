import type {
  AgentPrDispatchResult,
  ClosedTestPullRequestResult,
  EvalScoreboard,
  HealReport,
  Project,
  Workspace,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_PROMPTETHEUS_API_URL;
const ENV_CONSOLE_TOKEN = process.env.NEXT_PUBLIC_PROMPTETHEUS_CONSOLE_TOKEN;
const SUPABASE_PROJECT_REF = process.env.NEXT_PUBLIC_SUPABASE_PROJECT_REF;

export interface RotateProjectKeyResult {
  project: Project;
  api_key: string;
  api_key_preview: string;
}

export interface ProjectSettingsResult {
  workspace: Workspace;
  projects: Project[];
}

interface ApiProject {
  id: string;
  workspace_id: string;
  name: string;
  api_key_preview?: string | null;
  retention_days?: number | null;
  created_at?: string | null;
  connected_repo?: string | null;
}

interface ApiProjectSettingsResult {
  workspace?: {
    id?: string | null;
    name?: string | null;
    created_at?: string | null;
  } | null;
  projects?: ApiProject[];
}

function browserConsoleToken(): string | null {
  if (typeof window === "undefined") return ENV_CONSOLE_TOKEN ?? null;
  return (
    window.localStorage.getItem("promptetheus.consoleToken") ??
    supabaseAccessTokenFromStorage() ??
    ENV_CONSOLE_TOKEN ??
    null
  );
}

function supabaseAccessTokenFromStorage(): string | null {
  const candidateKeys = SUPABASE_PROJECT_REF
    ? [`sb-${SUPABASE_PROJECT_REF}-auth-token`]
    : Object.keys(window.localStorage).filter(
        (key) => key.startsWith("sb-") && key.endsWith("-auth-token"),
      );

  for (const key of candidateKeys) {
    const raw = window.localStorage.getItem(key);
    if (!raw) continue;
    try {
      const parsed = JSON.parse(raw) as {
        access_token?: unknown;
        currentSession?: { access_token?: unknown };
      };
      const token = parsed.access_token ?? parsed.currentSession?.access_token;
      if (typeof token === "string" && token) {
        return token;
      }
    } catch {
      continue;
    }
  }
  return null;
}

function apiEnabled(): boolean {
  return Boolean(API_URL && browserConsoleToken());
}

async function apiFetch<T>(path: string, init: RequestInit): Promise<T | null> {
  if (!apiEnabled()) return null;
  const token = browserConsoleToken();
  const response = await fetch(`${API_URL?.replace(/\/$/, "")}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(`Promptetheus API ${response.status}: ${await response.text()}`);
  }
  return (await response.json()) as T;
}

function normalizeProject(project: ApiProject): Project {
  return {
    id: project.id,
    workspace_id: project.workspace_id,
    name: project.name,
    api_key_preview: project.api_key_preview ?? "not issued",
    connected_repo: project.connected_repo ?? null,
    retention_days: project.retention_days ?? 30,
    created_at: project.created_at ?? new Date(0).toISOString(),
  };
}

export async function listProjectSettings(
  fallbackWorkspace: Workspace,
): Promise<ProjectSettingsResult | null> {
  const result = await apiFetch<ApiProjectSettingsResult>("/api/projects", {
    method: "GET",
  });
  if (!result?.projects) return null;
  return {
    workspace: {
      ...fallbackWorkspace,
      id: result.workspace?.id ?? fallbackWorkspace.id,
      name: result.workspace?.name ?? fallbackWorkspace.name,
      created_at: result.workspace?.created_at ?? fallbackWorkspace.created_at,
    },
    projects: result.projects.map(normalizeProject),
  };
}

export async function rotateProjectApiKey(
  projectId: string,
): Promise<RotateProjectKeyResult | null> {
  const result = await apiFetch<{
    project: ApiProject;
    api_key: string;
    api_key_preview: string;
  }>(`/api/projects/${projectId}/api-key`, {
    method: "POST",
    body: "{}",
  });
  if (!result) return null;
  return {
    ...result,
    project: normalizeProject(result.project),
  };
}

/**
 * Run the self-healing loop for an incident (POST /api/incidents/{id}/heal).
 * Returns null when the API isn't configured so the static demo still renders.
 */
export async function healIncident(
  incidentId: string,
  maxAttempts?: number,
): Promise<HealReport | null> {
  return apiFetch<HealReport>(`/api/incidents/${incidentId}/heal`, {
    method: "POST",
    body: JSON.stringify(maxAttempts ? { max_attempts: maxAttempts } : {}),
  });
}

/**
 * Read a JSON body defensively. When the endpoint answers with HTML — e.g. an
 * auth redirect to the sign-in page, or a 404/500 framework error page — surface
 * a real status-coded error instead of a cryptic `Unexpected token '<'`.
 */
async function readJsonOrThrow<T>(response: Response, label: string): Promise<T> {
  const text = await response.text();
  let body: unknown;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    const detail =
      response.status === 401 || response.status === 403
        ? "authentication required — sign in to the console first"
        : `expected JSON but got ${response.headers.get("content-type") ?? "an HTML response"}`;
    throw new Error(`${label} ${response.status}: ${detail}`);
  }
  if (!response.ok) {
    const maybeError = (body as { error?: string }).error;
    throw new Error(maybeError || `${label} ${response.status}`);
  }
  return body as T;
}

export async function dispatchLogsAgentPrs(input: {
  agentName?: string | null;
  incidentId: string;
  incidentTitle?: string | null;
  rootCause?: string | null;
  sessionId: string;
}): Promise<AgentPrDispatchResult> {
  const response = await fetch("/api/logs/dispatch-agent", {
    body: JSON.stringify(input),
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    method: "POST",
  });
  return readJsonOrThrow<AgentPrDispatchResult>(response, "Agent dispatch");
}

export async function checkLogsAgentPrStatus(input: {
  dispatchResult: AgentPrDispatchResult;
  incidentId: string;
  sessionId: string;
}): Promise<AgentPrDispatchResult> {
  const response = await fetch("/api/logs/dispatch-agent/status", {
    body: JSON.stringify(input),
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    method: "POST",
  });
  const body = (await response.json()) as AgentPrDispatchResult | { error?: string };
  if (!response.ok) {
    throw new Error("error" in body && body.error ? body.error : `Agent PR status ${response.status}`);
  }
  return body as AgentPrDispatchResult;
}

export async function createClosedLogsTestPr(input: {
  agentName?: string | null;
  incidentId: string;
  incidentTitle?: string | null;
  rootCause?: string | null;
  sessionId: string;
}): Promise<ClosedTestPullRequestResult> {
  const response = await fetch("/api/logs/test-pr", {
    body: JSON.stringify(input),
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    method: "POST",
  });
  return readJsonOrThrow<ClosedTestPullRequestResult>(response, "Test PR");
}

/** Live eval scoreboard (GET /api/evals/scoreboard). Returns null when the API
 *  is not configured — callers fall back to the mock `getEvalScoreboard()`. */
export async function fetchEvalScoreboard(): Promise<EvalScoreboard | null> {
  const result = await apiFetch<{ scoreboard: EvalScoreboard }>(
    "/api/evals/scoreboard",
    { method: "GET" },
  );
  return result ? result.scoreboard : null;
}

export async function updateProjectSettings(
  projectId: string,
  patch: Pick<Project, "retention_days">,
): Promise<{ project: Project } | null> {
  const result = await apiFetch<{ project: ApiProject }>(`/api/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  return result ? { project: normalizeProject(result.project) } : null;
}
