import type { HealReport, Project, Workspace } from "./types";

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
