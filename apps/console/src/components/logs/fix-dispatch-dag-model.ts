import type { HealReport, Incident } from "@/lib/types";

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
