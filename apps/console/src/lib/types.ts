/**
 * Console domain types. Mirror the FastAPI server entities
 * (db/migrations/0001_canonical_entities.sql + server/models.py).
 * The event wire shape itself is the parity-locked schema.ts.
 */
import type { PromptetheusEvent } from "./schema";

export type { PromptetheusEvent };

export type SessionStatus = "running" | "passed" | "failed" | "error";
export type IncidentStatus = "open" | "triaged" | "fixing" | "fixed" | "ignored";
export type Severity = "critical" | "high" | "medium" | "low";
export type SessionModality = "browser" | "voice" | "support" | "workflow" | "coding";

export interface VoiceMessageMetadata {
  channel: "voice";
  speaker: "user" | "agent";
  start_ms: number;
  end_ms: number;
  interrupted?: boolean;
  sentiment?: number;
}

export interface Workspace {
  id: string;
  name: string;
  created_at: string;
}

export interface Project {
  id: string;
  workspace_id: string;
  name: string;
  api_key_preview: string; // e.g. "pk_live_…a1b2" (never the real key)
  connected_repo: string | null; // "owner/repo"
  retention_days: number;
  created_at: string;
}

export interface TraceSession {
  id: string;
  workspace_id: string;
  project_id: string;
  user_goal: string | null;
  agent: string | null;
  environment: string | null;
  status: SessionStatus;
  tags: string[];
  metadata: Record<string, unknown>;
  started_at: string;
  /** Derived/denormalized for list rendering. */
  event_count: number;
  duration_ms: number;
  incident_id: string | null;
}

/** An event as stored (wire event + server-assigned fields). */
export interface TraceEvent extends PromptetheusEvent {
  session_id: string;
  /** offset in ms from session start — drives the timeline scrubber. */
  t_offset_ms: number;
}

export interface ReplayArtifact {
  artifact_id: string;
  session_id: string;
  storage_path: string; // mock: a public path under /mock-artifacts
  content_type: string;
  size_bytes: number;
  /** maps event seq -> playback offset in seconds, for video/timeline sync. */
  event_time_map: Record<string, number>;
  /** total media duration in seconds. */
  duration_s: number;
  kind: "video" | "audio" | "screenshot" | "dom_snapshot";
}

export interface Detection {
  label: string;
  confidence: number;
  evidence_refs: number[]; // event seq numbers
  critical_step_seq: number | null;
  description?: string;
}

export interface AnalysisResult {
  session_id: string;
  detections: Detection[];
  labels: string[];
  critical_step_seq: number | null;
  confidence: number;
  root_cause: string | null;
  observed_final_state?: string;
  fallback: boolean;
  created_at: string;
}

export interface FixAgentResult {
  plan: string[];
  diff: string | null;
  summary: string | null;
  changed_files: string[];
  runner: "deterministic" | "claude" | "codex";
  confidence: number;
  evidence_refs: number[];
  fallback: boolean;
  regression_test?: string;
}

export interface Incident {
  id: string;
  workspace_id: string;
  project_id: string;
  label: string;
  title: string;
  severity: Severity;
  status: IncidentStatus;
  representative_session_id: string;
  owner_id: string | null;
  session_ids: string[];
  critical_step_seq: number | null;
  root_cause: string | null;
  fingerprint: string;
  labels: string[];
  pr_url: string | null;
  fix_agent_result: FixAgentResult | null;
  created_at: string;
  updated_at: string;
}

export interface RegressionRun {
  id: string;
  incident_id: string;
  pr_url: string | null;
  before_pass: number;
  before_total: number;
  after_pass: number;
  after_total: number;
  status: "queued" | "running" | "complete" | "failed";
  fallback: boolean;
  created_at: string;
}

/** The incident-context bundle (GET /api/incidents/{id}/context). */
export interface IncidentContext {
  incident: Incident;
  analysis: AnalysisResult;
  session: TraceSession;
  events: TraceEvent[];
  artifacts: ReplayArtifact[];
  regression_runs: RegressionRun[];
}
