import type {
  AnalysisResult,
  Incident,
  Project,
  TraceEvent,
  TraceSession,
} from "@/lib/types";

export type LogColumn =
  | "status"
  | "run"
  | "input"
  | "output"
  | "error"
  | "project"
  | "environment"
  | "start_time"
  | "latency"
  | "feedback"
  | "tokens";

export type LogSortKey =
  | "start_time"
  | "latency"
  | "tokens"
  | "events"
  | "status"
  | "run";

export type LogTimeRange = "1h" | "24h" | "7d" | "all";

export interface LogFilters {
  query: string;
  status: TraceSession["status"] | "all";
  failedOnly: boolean;
  timeRange: LogTimeRange;
  projects: string[];
  environments: string[];
  tags: string[];
}

export interface LogRun {
  session: TraceSession;
  project: Project | undefined;
  incident: Incident | undefined;
  analysis: AnalysisResult | undefined;
  events: TraceEvent[];
  inputPreview: string;
  outputPreview: string;
  errorPreview: string;
  totalTokens: number;
  latencyMs: number;
  feedbackCount: number;
  confidence: number | null;
}

export interface LogMetrics {
  totalRuns: number;
  failedRuns: number;
  errorRate: number;
  p50LatencyMs: number;
  p99LatencyMs: number;
  totalTokens: number;
}

export interface TraceNode {
  id: string;
  event: TraceEvent;
  children: TraceNode[];
}

export interface VisibleTraceNode {
  node: TraceNode;
  depth: number;
}

export const DEFAULT_COLUMNS: LogColumn[] = ["status", "run", "error", "latency"];

const FILTER_NOW = Date.parse("2026-06-18T17:00:00Z");

function payloadRecord(event: TraceEvent): Record<string, unknown> {
  return event.payload as Record<string, unknown>;
}

function stringifyPreview(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function eventTitle(event: TraceEvent): string {
  const payload = payloadRecord(event);
  switch (event.type) {
    case "user_message":
      return "Human";
    case "agent_message":
      return "AI";
    case "llm_call":
      return String(payload.model ?? "Model");
    case "tool_call":
      return String(payload.tool_name ?? "Tool call");
    case "tool_result":
      return "Tool result";
    case "browser_action":
      return String(payload.action ?? "Browser action");
    case "goal_check":
      return "Goal check";
    case "error":
      return String(payload.error_type ?? "Error");
    case "metric":
    case "score":
      return String(payload.name ?? event.type);
    default:
      return event.type.replaceAll("_", " ");
  }
}

export function eventSummary(event: TraceEvent): string {
  const payload = payloadRecord(event);
  switch (event.type) {
    case "user_message":
    case "agent_message":
      return stringifyPreview(payload.content);
    case "tool_call":
      return `${String(payload.tool_name ?? "tool")} ${stringifyPreview(payload.arguments)}`;
    case "tool_result":
      return payload.error ? stringifyPreview(payload.error) : stringifyPreview(payload.result) || "ok";
    case "browser_action":
      return `${String(payload.action ?? "")} ${String(payload.target ?? payload.url ?? "")}`;
    case "dom_snapshot":
      return stringifyPreview(payload.visible_text ?? payload.url);
    case "screenshot":
      return stringifyPreview(payload.source ?? payload.artifact_id);
    case "retrieval":
      return stringifyPreview(payload.query);
    case "llm_call":
      return `${String(payload.model ?? "model")} ${String(payload.input_tokens ?? "?")} -> ${String(
        payload.output_tokens ?? "?",
      )} tokens`;
    case "goal_check":
      return payload.passed === false
        ? stringifyPreview((payload.mismatches as string[] | undefined)?.[0] ?? "failed")
        : "passed";
    case "error":
      return stringifyPreview(payload.message ?? payload.error_type);
    case "state_change":
      return stringifyPreview(payload.name);
    case "session_end":
      return `status ${String(payload.status ?? "")}`;
    case "score":
    case "metric":
      return `${String(payload.name ?? event.type)} ${String(payload.value ?? "")}${String(payload.unit ?? "")}`;
    default:
      return event.type;
  }
}

function firstEventSummary(events: TraceEvent[], type: TraceEvent["type"]): string {
  const event = events.find((candidate) => candidate.type === type);
  return event ? eventSummary(event) : "";
}

function lastOutput(events: TraceEvent[]): string {
  const event = [...events]
    .reverse()
    .find((candidate) =>
      ["agent_message", "tool_result", "goal_check", "session_end"].includes(candidate.type),
    );
  return event ? eventSummary(event) : "";
}

function firstError(events: TraceEvent[], analysis?: AnalysisResult): string {
  const explicit = events.find((event) => event.type === "error");
  if (explicit) return eventSummary(explicit);
  const failedGoal = events.find(
    (event) =>
      event.type === "goal_check" &&
      (payloadRecord(event) as { passed?: boolean }).passed === false,
  );
  if (failedGoal) return eventSummary(failedGoal);
  return analysis?.root_cause ?? "";
}

function tokenCount(events: TraceEvent[]): number {
  return events.reduce((sum, event) => {
    if (event.type !== "llm_call") return sum;
    const payload = payloadRecord(event);
    return (
      sum +
      Number(payload.input_tokens ?? 0) +
      Number(payload.output_tokens ?? 0)
    );
  }, 0);
}

function latency(events: TraceEvent[], session: TraceSession): number {
  const llmLatency = events.reduce((sum, event) => {
    if (event.type !== "llm_call") return sum;
    return sum + Number(payloadRecord(event).latency_ms ?? 0);
  }, 0);
  return llmLatency || session.duration_ms;
}

export function buildLogRuns({
  sessions,
  projects,
  incidents,
  eventsBySession,
  analysesBySession,
}: {
  sessions: TraceSession[];
  projects: Project[];
  incidents: Incident[];
  eventsBySession: Record<string, TraceEvent[]>;
  analysesBySession: Record<string, AnalysisResult | undefined>;
}): LogRun[] {
  return sessions.map((session) => {
    const events = [...(eventsBySession[session.id] ?? [])].sort((a, b) => a.seq - b.seq);
    const analysis = analysesBySession[session.id];
    return {
      session,
      project: projects.find((project) => project.id === session.project_id),
      incident: incidents.find((incident) => incident.id === session.incident_id),
      analysis,
      events,
      inputPreview: firstEventSummary(events, "user_message") || session.user_goal || session.id,
      outputPreview: lastOutput(events),
      errorPreview: firstError(events, analysis),
      totalTokens: tokenCount(events),
      latencyMs: latency(events, session),
      feedbackCount: analysis?.detections.length ?? 0,
      confidence: analysis?.confidence ?? null,
    };
  });
}

function inTimeRange(run: LogRun, range: LogTimeRange, now = FILTER_NOW): boolean {
  if (range === "all") return true;
  const started = Date.parse(run.session.started_at);
  if (!Number.isFinite(started)) return true;
  const hours = range === "1h" ? 1 : range === "24h" ? 24 : 24 * 7;
  return now - started <= hours * 60 * 60 * 1000;
}

export function filterLogRuns(runs: LogRun[], filters: LogFilters): LogRun[] {
  const query = filters.query.trim().toLowerCase();
  const projects = new Set(filters.projects);
  const environments = new Set(filters.environments);
  const tags = new Set(filters.tags);

  return runs.filter((run) => {
    if (filters.status !== "all" && run.session.status !== filters.status) return false;
    if (filters.failedOnly && !["failed", "error"].includes(run.session.status)) return false;
    if (projects.size > 0 && !projects.has(run.session.project_id)) return false;
    if (
      environments.size > 0 &&
      (!run.session.environment || !environments.has(run.session.environment))
    ) return false;
    if (tags.size > 0 && !run.session.tags.some((tag) => tags.has(tag))) return false;
    if (!inTimeRange(run, filters.timeRange)) return false;
    if (!query) return true;

    const haystack = [
      run.session.id,
      run.session.user_goal,
      run.session.agent,
      run.session.environment,
      run.project?.name,
      run.incident?.title,
      run.inputPreview,
      run.outputPreview,
      run.errorPreview,
      run.session.tags.join(" "),
      run.analysis?.labels.join(" "),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });
}

export function sortLogRuns(
  runs: LogRun[],
  key: LogSortKey,
  direction: "asc" | "desc",
): LogRun[] {
  const factor = direction === "asc" ? 1 : -1;
  return [...runs].sort((a, b) => {
    let av: number | string;
    let bv: number | string;
    switch (key) {
      case "latency":
        av = a.latencyMs;
        bv = b.latencyMs;
        break;
      case "tokens":
        av = a.totalTokens;
        bv = b.totalTokens;
        break;
      case "events":
        av = a.session.event_count;
        bv = b.session.event_count;
        break;
      case "status":
        av = a.session.status;
        bv = b.session.status;
        break;
      case "run":
        av = a.session.user_goal ?? a.session.id;
        bv = b.session.user_goal ?? b.session.id;
        break;
      case "start_time":
      default:
        av = Date.parse(a.session.started_at);
        bv = Date.parse(b.session.started_at);
    }
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * factor;
    return String(av).localeCompare(String(bv)) * factor;
  });
}

function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[index];
}

export function deriveLogMetrics(runs: LogRun[]): LogMetrics {
  const failedRuns = runs.filter((run) => ["failed", "error"].includes(run.session.status)).length;
  return {
    totalRuns: runs.length,
    failedRuns,
    errorRate: runs.length ? failedRuns / runs.length : 0,
    p50LatencyMs: percentile(
      runs.map((run) => run.latencyMs),
      50,
    ),
    p99LatencyMs: percentile(
      runs.map((run) => run.latencyMs),
      99,
    ),
    totalTokens: runs.reduce((sum, run) => sum + run.totalTokens, 0),
  };
}

export interface AgentGroup {
  projectId: string;
  label: string;
  totalRuns: number;
  failedRuns: number;
}

export function groupRunsByAgent(runs: LogRun[], projects: Project[]): AgentGroup[] {
  const byProject = new Map<string, AgentGroup>();
  for (const project of projects) {
    byProject.set(project.id, {
      projectId: project.id,
      label: project.name,
      totalRuns: 0,
      failedRuns: 0,
    });
  }
  for (const run of runs) {
    const id = run.session.project_id;
    if (!byProject.has(id)) {
      byProject.set(id, {
        projectId: id,
        label: run.project?.name ?? id,
        totalRuns: 0,
        failedRuns: 0,
      });
    }
    const group = byProject.get(id)!;
    group.totalRuns += 1;
    if (["failed", "error"].includes(run.session.status)) group.failedRuns += 1;
  }
  return Array.from(byProject.values()).filter((g) => g.totalRuns > 0);
}

function nodeId(event: TraceEvent): string {
  return event.span_id ?? `${event.session_id}:${event.seq}`;
}

function heuristicDepth(event: TraceEvent): 0 | 1 | 2 {
  if (["user_message", "agent_message", "goal_check", "session_end"].includes(event.type)) {
    return 0;
  }
  if (["tool_call", "llm_call", "retrieval", "state_change", "error", "score", "metric"].includes(event.type)) {
    return 1;
  }
  return 2;
}

export function buildTraceTree(events: TraceEvent[]): TraceNode[] {
  const ordered = [...events].sort((a, b) => a.seq - b.seq);
  const hasParents = ordered.some((event) => event.span_id || event.parent_id);
  if (hasParents) {
    const byId = new Map<string, TraceNode>();
    const roots: TraceNode[] = [];
    for (const event of ordered) byId.set(nodeId(event), { id: nodeId(event), event, children: [] });
    for (const event of ordered) {
      const node = byId.get(nodeId(event))!;
      const parent = event.parent_id ? byId.get(event.parent_id) : undefined;
      if (parent) parent.children.push(node);
      else roots.push(node);
    }
    return roots;
  }

  const roots: TraceNode[] = [];
  let currentRoot: TraceNode | undefined;
  let currentOperation: TraceNode | undefined;

  for (const event of ordered) {
    const node: TraceNode = { id: nodeId(event), event, children: [] };
    const depth = heuristicDepth(event);
    if (depth === 0) {
      roots.push(node);
      currentRoot = node;
      currentOperation = undefined;
    } else if (depth === 1) {
      if (currentRoot) currentRoot.children.push(node);
      else roots.push(node);
      currentOperation = node;
    } else if (currentOperation) {
      currentOperation.children.push(node);
    } else if (currentRoot) {
      currentRoot.children.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}

export function flattenTraceTree(
  nodes: TraceNode[],
  expanded: Set<string>,
  depth = 0,
): VisibleTraceNode[] {
  const visible: VisibleTraceNode[] = [];
  for (const node of nodes) {
    visible.push({ node, depth });
    if (node.children.length > 0 && expanded.has(node.id)) {
      visible.push(...flattenTraceTree(node.children, expanded, depth + 1));
    }
  }
  return visible;
}

export function allExpandable(nodes: TraceNode[], ids = new Set<string>()): Set<string> {
  for (const node of nodes) {
    if (node.children.length) ids.add(node.id);
    allExpandable(node.children, ids);
  }
  return ids;
}

export function firstFailedEvent(run: LogRun): TraceEvent | undefined {
  const critical = run.analysis?.critical_step_seq;
  return (
    run.events.find((event) => event.seq === critical) ??
    run.events.find(
      (event) =>
        event.type === "error" ||
        (event.type === "goal_check" &&
          (event.payload as { passed?: boolean }).passed === false),
    ) ??
    run.events[0]
  );
}

export function pickDefaultRun(runs: LogRun[]): LogRun | undefined {
  if (runs.length === 0) return undefined;
  const failed = runs.filter((run) => ["failed", "error"].includes(run.session.status));
  const pool = failed.length > 0 ? failed : runs;
  return sortLogRuns(pool, "start_time", "desc")[0];
}
