import type { HealAttempt, HealReport, Incident, TraceEvent } from "@/lib/types";
import { eventSummary, eventTitle, type LogRun } from "./model";

export type FixDagNodeId =
  | "read_logs"
  | "plan_fix"
  | "dispatch_fix"
  | "run_evals"
  | "open_pr"
  | "merge_github";

export type FixDagNodeStatus =
  | "pending"
  | "active"
  | "complete"
  | "ready"
  | "preview"
  | "blocked"
  | "disabled";

export type FixDagPhase =
  | "idle"
  | "running"
  | "pr_opened"
  | "escalated"
  | "demo"
  | "demo_complete"
  | "error";

export interface FixDagNodeDefinition {
  id: FixDagNodeId;
  label: string;
  description: string;
}

export interface FixDagNode extends FixDagNodeDefinition {
  status: FixDagNodeStatus;
  summary: string;
}

export interface FixDagEdge {
  from: FixDagNodeId;
  to: FixDagNodeId;
  status: FixDagNodeStatus;
}

export interface FixDagProjection {
  mode: "disabled" | "idle" | "running" | "live" | "demo" | "blocked" | "error";
  headline: string;
  detail: string;
  nodes: FixDagNode[];
  edges: FixDagEdge[];
  currentNodeId: FixDagNodeId;
  selectedDefaultNodeId: FixDagNodeId;
  prUrl: string | null;
  prPreview: boolean;
}

export type FixDagEvidenceMode = "local" | "live" | "demo" | "blocked";
export type FixDagEvidenceTone = "info" | "success" | "warning" | "error";

export interface FixDagEvidenceItem {
  label: string;
  value: string;
  tone?: FixDagEvidenceTone;
  href?: string;
}

export interface FixDagEvidence {
  nodeId: FixDagNodeId;
  title: string;
  subtitle: string;
  mode: FixDagEvidenceMode;
  items: FixDagEvidenceItem[];
  details: string[];
}

export const FIX_DAG_NODE_IDS: FixDagNodeId[] = [
  "read_logs",
  "plan_fix",
  "dispatch_fix",
  "run_evals",
  "open_pr",
  "merge_github",
];

export const FIX_DAG_NODES: FixDagNodeDefinition[] = [
  {
    id: "read_logs",
    label: "Read logs",
    description: "Collect the selected run, event payloads, root cause, and evidence refs.",
  },
  {
    id: "plan_fix",
    label: "Plan fix",
    description: "Build the incident bundle and draft the fix plan from the failed trace.",
  },
  {
    id: "dispatch_fix",
    label: "Dispatch fix",
    description: "Run the fix agent or deterministic fallback against the incident bundle.",
  },
  {
    id: "run_evals",
    label: "Run evals",
    description: "Gate the candidate with critique, replay, and before/after eval checks.",
  },
  {
    id: "open_pr",
    label: "Open PR",
    description: "Attach a real GitHub pull request or labeled preview to the incident.",
  },
  {
    id: "merge_github",
    label: "Merge PR",
    description: "Leave final merge control in GitHub after the PR and evals are ready.",
  },
];

const NODE_SUMMARY: Record<FixDagNodeId, string> = {
  read_logs: "Ready to package run evidence.",
  plan_fix: "Waiting for dispatch.",
  dispatch_fix: "Waiting for fix agent handoff.",
  run_evals: "Waiting for eval gate.",
  open_pr: "Waiting for PR creation.",
  merge_github: "Waiting for a real PR link.",
};

const NODE_ORDER = new Map(FIX_DAG_NODE_IDS.map((id, index) => [id, index]));

export function nextFixDagNode(id: FixDagNodeId): FixDagNodeId {
  const index = NODE_ORDER.get(id) ?? 0;
  return FIX_DAG_NODE_IDS[Math.min(index + 1, FIX_DAG_NODE_IDS.length - 1)];
}

export function projectFixDispatchDag({
  activeNodeId = "read_logs",
  error,
  incident,
  phase,
  report,
}: {
  activeNodeId?: FixDagNodeId;
  error?: string | null;
  incident?: Incident | null;
  phase: FixDagPhase;
  report?: HealReport | null;
}): FixDagProjection {
  if (!incident) {
    return buildProjection({
      currentNodeId: "read_logs",
      detail: "Select a failed run with an attached incident before dispatching a fix.",
      headline: "No incident attached",
      mode: "disabled",
      nodeStatus: () => "disabled",
      prPreview: false,
      prUrl: null,
      selectedDefaultNodeId: "read_logs",
    });
  }

  if (phase === "running") {
    return buildProjection({
      currentNodeId: activeNodeId,
      detail: "The dispatch is moving through log reading, planning, fix handoff, evals, and PR preparation.",
      headline: "Dispatch running",
      mode: "running",
      nodeStatus: (id) => statusByActiveNode(id, activeNodeId),
      prPreview: false,
      prUrl: null,
      selectedDefaultNodeId: activeNodeId,
    });
  }

  if (phase === "pr_opened") {
    const prUrl = report?.pr?.pr_url ?? incident.pr_url ?? null;
    const preview = Boolean(report?.pr?.fallback);
    return buildProjection({
      currentNodeId: preview ? "open_pr" : "merge_github",
      detail: preview
        ? "The fix path generated a PR preview. Connect GitHub PR creation to merge this from GitHub."
        : "The eval gate passed and the pull request is ready for human review in GitHub.",
      headline: preview ? "PR preview ready" : "PR ready for GitHub",
      mode: "live",
      nodeStatus: (id) => {
        if (preview && id === "open_pr") return "preview";
        if (preview && id === "merge_github") return "blocked";
        if (id === "merge_github") return "ready";
        return "complete";
      },
      prPreview: preview,
      prUrl,
      selectedDefaultNodeId: preview ? "open_pr" : "merge_github",
    });
  }

  if (phase === "escalated") {
    return buildProjection({
      currentNodeId: "run_evals",
      detail: report?.reason ?? "The heal loop escalated before a safe PR could be opened.",
      headline: "Eval gate blocked dispatch",
      mode: "blocked",
      nodeStatus: (id) => {
        const index = NODE_ORDER.get(id) ?? 0;
        if (index < (NODE_ORDER.get("run_evals") ?? 0)) return "complete";
        return "blocked";
      },
      prPreview: false,
      prUrl: null,
      selectedDefaultNodeId: "run_evals",
    });
  }

  if (phase === "demo") {
    return buildProjection({
      currentNodeId: "open_pr",
      detail: "Connect the Promptetheus API to open a real PR. This local run only demonstrates the dispatch path.",
      headline: "Demo dispatch complete",
      mode: "demo",
      nodeStatus: (id) => {
        if (id === "open_pr") return "preview";
        if (id === "merge_github") return "blocked";
        return "complete";
      },
      prPreview: true,
      prUrl: null,
      selectedDefaultNodeId: "open_pr",
    });
  }

  if (phase === "demo_complete") {
    return buildProjection({
      currentNodeId: "merge_github",
      detail: "Demo mode completed the fix path. Connect the API to open and merge a real GitHub PR.",
      headline: "Merge-ready PR path",
      mode: "demo",
      nodeStatus: (id) => (id === "merge_github" ? "ready" : "complete"),
      prPreview: true,
      prUrl: incident.pr_url,
      selectedDefaultNodeId: "merge_github",
    });
  }

  if (phase === "error") {
    return buildProjection({
      currentNodeId: "dispatch_fix",
      detail: error ?? "The dispatch failed before the fix path could complete.",
      headline: "Dispatch failed",
      mode: "error",
      nodeStatus: (id) => {
        const index = NODE_ORDER.get(id) ?? 0;
        if (index < (NODE_ORDER.get("dispatch_fix") ?? 0)) return "complete";
        if (id === "dispatch_fix") return "blocked";
        return "pending";
      },
      prPreview: false,
      prUrl: null,
      selectedDefaultNodeId: "dispatch_fix",
    });
  }

  return buildProjection({
    currentNodeId: "read_logs",
    detail: "Dispatch reads the selected run, packages a fix plan, runs evals, and opens a PR when the gate passes.",
    headline: "Ready to dispatch",
    mode: "idle",
    nodeStatus: (id) => (id === "read_logs" ? "complete" : "pending"),
    prPreview: false,
    prUrl: incident.pr_url,
    selectedDefaultNodeId: "read_logs",
  });
}

export function buildFixDagEvidence({
  activeNodeId,
  error,
  phase,
  report,
  run,
}: {
  activeNodeId: FixDagNodeId;
  error?: string | null;
  phase: FixDagPhase;
  report?: HealReport | null;
  run: LogRun;
}): FixDagEvidence {
  const incident = run.incident ?? null;
  const liveAttempt = latestAttempt(report);
  const evalAttempt = latestEvalAttempt(report);
  const mode = evidenceMode(phase, report);

  if (!incident) {
    return {
      details: [
        "This run can still be inspected, but Promptetheus needs an attached incident before it can dispatch a fix.",
      ],
      items: [
        { label: "Session", value: run.session.id },
        { label: "Events", value: String(run.events.length || run.session.event_count) },
        { label: "Run status", value: run.session.status, tone: "warning" },
      ],
      mode: "blocked",
      nodeId: activeNodeId,
      subtitle: "No incident is available to package into a fix bundle.",
      title: "No incident available",
    };
  }

  switch (activeNodeId) {
    case "read_logs":
      return buildReadLogsEvidence(run, mode);
    case "plan_fix":
      return buildPlanEvidence(run, mode);
    case "dispatch_fix":
      return buildDispatchEvidence(run, mode, liveAttempt, report);
    case "run_evals":
      return buildEvalEvidence(run, mode, evalAttempt, report, error);
    case "open_pr":
      return buildPrEvidence(run, mode, report);
    case "merge_github":
      return buildMergeEvidence(run, mode, report);
  }
}

function buildProjection({
  currentNodeId,
  detail,
  headline,
  mode,
  nodeStatus,
  prPreview,
  prUrl,
  selectedDefaultNodeId,
}: {
  currentNodeId: FixDagNodeId;
  detail: string;
  headline: string;
  mode: FixDagProjection["mode"];
  nodeStatus: (id: FixDagNodeId) => FixDagNodeStatus;
  prPreview: boolean;
  prUrl: string | null;
  selectedDefaultNodeId: FixDagNodeId;
}): FixDagProjection {
  const nodes = FIX_DAG_NODES.map((definition) => {
    const status = nodeStatus(definition.id);
    return {
      ...definition,
      status,
      summary: summaryForStatus(definition.id, status),
    };
  });

  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const edges = FIX_DAG_NODE_IDS.slice(0, -1).map((from, index) => {
    const to = FIX_DAG_NODE_IDS[index + 1];
    return {
      from,
      to,
      status: edgeStatus(nodeMap.get(from)?.status ?? "pending", nodeMap.get(to)?.status ?? "pending"),
    };
  });

  return {
    currentNodeId,
    detail,
    edges,
    headline,
    mode,
    nodes,
    prPreview,
    prUrl,
    selectedDefaultNodeId,
  };
}

function statusByActiveNode(id: FixDagNodeId, activeNodeId: FixDagNodeId): FixDagNodeStatus {
  const index = NODE_ORDER.get(id) ?? 0;
  const activeIndex = NODE_ORDER.get(activeNodeId) ?? 0;
  if (index < activeIndex) return "complete";
  if (index === activeIndex) return "active";
  return "pending";
}

function edgeStatus(from: FixDagNodeStatus, to: FixDagNodeStatus): FixDagNodeStatus {
  if (from === "disabled" || to === "disabled") return "disabled";
  if (from === "blocked" || to === "blocked") return "blocked";
  if (to === "active") return "active";
  if (from === "complete" && ["complete", "ready", "preview"].includes(to)) return "complete";
  if (to === "preview") return "preview";
  if (to === "ready") return "ready";
  return "pending";
}

function summaryForStatus(id: FixDagNodeId, status: FixDagNodeStatus): string {
  if (status === "complete") return "Completed";
  if (status === "active") return "In progress";
  if (status === "ready") return "Ready";
  if (status === "preview") return "Preview generated";
  if (status === "blocked") return id === "merge_github" ? "Requires a real PR" : "Needs attention";
  if (status === "disabled") return "Unavailable";
  return NODE_SUMMARY[id];
}

function buildReadLogsEvidence(run: LogRun, mode: FixDagEvidenceMode): FixDagEvidence {
  const criticalSeq = run.analysis?.critical_step_seq ?? run.incident?.critical_step_seq ?? null;
  const criticalEvent = criticalSeq === null ? undefined : run.events.find((event) => event.seq === criticalSeq);
  const evidenceRefs = uniqueEvidenceRefs(run);
  const recent = [...run.events]
    .sort((a, b) => b.seq - a.seq)
    .slice(0, 3)
    .map(describeEvent);

  return {
    details: [
      criticalEvent ? `Critical event: ${describeEvent(criticalEvent)}` : "Critical event is inferred from the incident bundle.",
      ...recent,
    ],
    items: compactItems([
      { label: "Session", value: run.session.id },
      { label: "Event count", value: String(run.events.length || run.session.event_count) },
      criticalSeq === null ? null : { label: "Critical seq", value: `#${criticalSeq}`, tone: "warning" },
      evidenceRefs.length ? { label: "Evidence refs", value: evidenceRefs.map((ref) => `#${ref}`).join(", ") } : null,
      { label: "Status", value: run.session.status, tone: run.session.status === "failed" ? "warning" : "info" },
    ]),
    mode,
    nodeId: "read_logs",
    subtitle: "Receipts are pulled from the selected trace before a fix is planned.",
    title: "Read selected run",
  };
}

function buildPlanEvidence(run: LogRun, mode: FixDagEvidenceMode): FixDagEvidence {
  const incident = run.incident;
  return {
    details: [
      incident?.root_cause ?? run.analysis?.root_cause ?? run.errorPreview,
      `Representative session: ${incident?.representative_session_id ?? run.session.id}`,
    ].filter(Boolean),
    items: compactItems([
      { label: "Incident", value: incident?.title ?? "No incident title" },
      { label: "Severity", value: incident?.severity ?? "unknown", tone: incident?.severity === "critical" ? "warning" : "info" },
      { label: "Labels", value: (incident?.labels ?? run.analysis?.labels ?? []).join(", ") || "unlabeled" },
      run.confidence === null ? null : { label: "Confidence", value: formatPercent(run.confidence), tone: "success" },
      { label: "Fingerprint", value: incident?.fingerprint ?? "pending" },
    ]),
    mode,
    nodeId: "plan_fix",
    subtitle: "Promptetheus turns the failure cluster into an incident-scoped fix plan.",
    title: "Plan fix from incident",
  };
}

function buildDispatchEvidence(
  run: LogRun,
  mode: FixDagEvidenceMode,
  attempt: HealAttempt | null,
  report?: HealReport | null,
): FixDagEvidence {
  const fixResult = run.incident?.fix_agent_result;
  return {
    details: [
      attempt?.diagnosis ?? fixResult?.summary ?? run.incident?.root_cause ?? "Using local incident evidence until the live heal report returns.",
      fixResult?.plan?.slice(0, 2).join(" -> ") ?? "",
    ].filter(Boolean),
    items: compactItems([
      { label: "Source", value: report?.source ?? "selected run evidence" },
      { label: "Orchestrator", value: report?.orchestrator ?? "local demo sequence" },
      { label: "Runner", value: attempt?.runner ?? fixResult?.runner ?? "deterministic preview" },
      { label: "Attempt", value: attempt ? String(attempt.attempt) : String(report?.attempts ?? 1) },
      report?.workflow_run_id ? { label: "Workflow", value: report.workflow_run_id } : null,
    ]),
    mode,
    nodeId: "dispatch_fix",
    subtitle: "The fix handoff is tied to the same incident payload used by the live API.",
    title: "Dispatch fix agent",
  };
}

function buildEvalEvidence(
  run: LogRun,
  mode: FixDagEvidenceMode,
  attempt: HealAttempt | null,
  report?: HealReport | null,
  error?: string | null,
): FixDagEvidence {
  const evalReport = attempt?.eval ?? null;
  const firstCase = evalReport?.cases[0] ?? null;
  const blockedReason = error ?? report?.reason ?? firstCase?.reason ?? evalReport?.note ?? null;
  const passed = evalReport?.passed ?? (mode === "demo" ? true : null);

  return {
    details: [
      firstCase?.assertion ? `Assertion: ${firstCase.assertion}` : `Local assertion: ${run.errorPreview || run.analysis?.root_cause || "failed trace should be corrected"}`,
      blockedReason ? `Reason: ${blockedReason}` : "",
      attempt?.critique?.reason ? `Critique: ${attempt.critique.reason}` : "",
    ].filter(Boolean),
    items: compactItems([
      { label: "Eval", value: passed === null ? "pending" : passed ? "passed" : "failed", tone: passed ? "success" : passed === false ? "error" : "info" },
      { label: "Before fail", value: String(evalReport?.before_fail ?? attempt?.regression?.before_fail ?? 1) },
      { label: "After fail", value: String(evalReport?.after_fail ?? attempt?.regression?.after_fail ?? (mode === "demo" ? 0 : "pending")), tone: evalReport?.after_fail === 0 || mode === "demo" ? "success" : "info" },
      firstCase ? { label: "Confidence", value: formatPercent(firstCase.confidence), tone: "success" } : run.confidence === null ? null : { label: "Confidence", value: formatPercent(run.confidence) },
      evalReport ? { label: "Meaningful", value: evalReport.meaningful ? "yes" : "no", tone: evalReport.meaningful ? "success" : "warning" } : null,
    ]),
    mode: report?.status === "escalated" || error ? "blocked" : mode,
    nodeId: "run_evals",
    subtitle: "The eval gate proves the fix changes the failing behavior before PR handoff.",
    title: "Run eval gate",
  };
}

function buildPrEvidence(run: LogRun, mode: FixDagEvidenceMode, report?: HealReport | null): FixDagEvidence {
  const pr = report?.pr ?? null;
  const fallback = pr?.fallback ?? mode !== "live";
  const changedFiles = pr?.changed_files ?? run.incident?.fix_agent_result?.changed_files ?? [];

  return {
    details: [
      changedFiles.length ? `Changed files: ${changedFiles.join(", ")}` : "Changed files are preview-only until the live heal report returns.",
      fallback ? "PR preview only. Connect the API/GitHub integration to open a real pull request." : "Live GitHub PR was opened after evals passed.",
    ],
    items: compactItems([
      { label: "Title", value: pr?.title ?? `Fix ${run.incident?.label.replaceAll("_", " ") ?? "incident"}` },
      { label: "Branch", value: pr?.branch ?? `promptetheus/${run.incident?.id ?? run.session.id}-fix` },
      { label: "Files", value: changedFiles.length ? String(changedFiles.length) : "preview pending" },
      { label: "Mode", value: fallback ? "PR preview" : "real GitHub PR", tone: fallback ? "warning" : "success" },
      pr?.pr_url ? { label: "GitHub", value: pr.pr_url, href: pr.pr_url, tone: "success" } : null,
    ]),
    mode: fallback ? "demo" : mode,
    nodeId: "open_pr",
    subtitle: "A PR is prepared only after the eval gate says the candidate is useful.",
    title: fallback ? "Open PR preview" : "Open real PR",
  };
}

function buildMergeEvidence(run: LogRun, mode: FixDagEvidenceMode, report?: HealReport | null): FixDagEvidence {
  const prUrl = report?.pr?.pr_url ?? run.incident?.pr_url ?? null;
  const fallback = report?.pr?.fallback ?? !prUrl;
  const blocked = report?.status === "escalated" || fallback;

  return {
    details: [
      blocked
        ? "Promptetheus does not merge from the app. This state becomes actionable when a real GitHub PR link exists."
        : "Review and merge remain in GitHub after the live PR and eval receipts are available.",
      report?.reason ?? "",
    ].filter(Boolean),
    items: compactItems([
      { label: "Merge action", value: "external GitHub review" },
      { label: "State", value: blocked ? "preview or blocked" : "ready in GitHub", tone: blocked ? "warning" : "success" },
      { label: "Mode", value: fallback ? "preview" : "real PR", tone: fallback ? "warning" : "success" },
      prUrl ? { label: "PR link", value: prUrl, href: prUrl, tone: "success" } : null,
    ]),
    mode: blocked ? "blocked" : mode,
    nodeId: "merge_github",
    subtitle: "The final state is a GitHub-ready handoff, not an in-app merge button.",
    title: blocked ? "Merge blocked until real PR" : "Merge in GitHub",
  };
}

function evidenceMode(phase: FixDagPhase, report?: HealReport | null): FixDagEvidenceMode {
  if (phase === "escalated" || phase === "error") return "blocked";
  if (report) return "live";
  if (phase === "demo" || phase === "demo_complete" || phase === "running") return "demo";
  return "local";
}

function latestAttempt(report?: HealReport | null): HealAttempt | null {
  const trail = report?.trail ?? [];
  return trail.length ? trail[trail.length - 1] : null;
}

function latestEvalAttempt(report?: HealReport | null): HealAttempt | null {
  const trail = report?.trail ?? [];
  for (let index = trail.length - 1; index >= 0; index -= 1) {
    if (trail[index].eval) return trail[index];
  }
  return null;
}

function uniqueEvidenceRefs(run: LogRun): number[] {
  const refs = new Set<number>();
  for (const detection of run.analysis?.detections ?? []) {
    for (const ref of detection.evidence_refs) refs.add(ref);
  }
  for (const ref of run.incident?.fix_agent_result?.evidence_refs ?? []) refs.add(ref);
  return [...refs].sort((a, b) => a - b);
}

function describeEvent(event: TraceEvent): string {
  const summary = eventSummary(event);
  return `#${event.seq} ${eventTitle(event)}${summary ? ` - ${summary}` : ""}`;
}

function compactItems(items: Array<FixDagEvidenceItem | null>): FixDagEvidenceItem[] {
  return items.filter((item): item is FixDagEvidenceItem => Boolean(item));
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}
