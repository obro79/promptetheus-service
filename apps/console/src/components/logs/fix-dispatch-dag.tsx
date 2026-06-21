"use client";

import * as React from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  ExternalLink,
  FileCode2,
  GitBranch,
  GitMerge,
  GitPullRequest,
  Loader2,
  Maximize2,
  Minimize2,
  Network,
  ShieldCheck,
  Sparkles,
  Timer,
  X,
  type LucideIcon,
} from "lucide-react";

import {
  BrowserbaseMark,
  DevinMark,
  McpMark,
  RedisMark,
  SupabaseMark,
} from "@/components/common/brand-marks";
import { LabelTag } from "@/components/common/label-tag";
import { Button } from "@/components/ui/button";
import { checkLogsAgentPrStatus, healIncident } from "@/lib/promptetheus-api";
import type {
  AgentPrDispatchResult,
  AgentPullRequestResult,
  EvalReport,
  HealReport,
} from "@/lib/types";
import { cn, pct } from "@/lib/utils";
import { buildTraceTree, eventSummary, eventTitle, type LogRun, type TraceNode } from "./model";
import {
  FIX_DAG_NODE_IDS,
  buildFixDagEvidence,
  type FixDagEvidence,
  type FixDagEvidenceTone,
  type FixDagNode,
  type FixDagNodeId,
  type FixDagNodeStatus,
  type FixDagPhase,
  projectFixDispatchDag,
} from "./fix-dispatch-dag-model";

type DispatchHeal = (
  incidentId: string,
  run: LogRun,
) => Promise<HealReport | AgentPrDispatchResult | null>;
type CheckDispatchStatus = (input: {
  dispatchResult: AgentPrDispatchResult;
  incidentId: string;
  sessionId: string;
}) => Promise<AgentPrDispatchResult>;

interface FixDispatchDagProps {
  autoDemo?: boolean;
  checkDispatchStatus?: CheckDispatchStatus;
  dispatchHeal?: DispatchHeal;
  dispatchLabel?: string;
  layout?: "prominent" | "compact";
  prominent?: boolean;
  run: LogRun;
}

type NodeIconComponent = React.ComponentType<{ className?: string }>;

function makeNodeIcon(Icon: LucideIcon): NodeIconComponent {
  function NodeIcon({ className }: { className?: string }) {
    return <Icon className={className} aria-hidden="true" strokeWidth={1.8} />;
  }
  return NodeIcon;
}

const NODE_ICON: Record<FixDagNodeId, NodeIconComponent> = {
  dispatch_fix: makeNodeIcon(Sparkles),
  merge_github: makeNodeIcon(GitMerge),
  open_pr: makeNodeIcon(GitPullRequest),
  plan_fix: makeNodeIcon(FileCode2),
  read_logs: SupabaseMark,
  run_evals: makeNodeIcon(ShieldCheck),
};

const NODE_POSITIONS: Record<FixDagNodeId, { x: number; y: number }> = {
  read_logs: { x: 96, y: 92 },
  plan_fix: { x: 264, y: 92 },
  dispatch_fix: { x: 432, y: 92 },
  run_evals: { x: 600, y: 92 },
  open_pr: { x: 768, y: 92 },
  merge_github: { x: 936, y: 92 },
};

const CANVAS = { width: 1040, height: 268 };
const NODE_WIDTH = 132;

/** Y where the node row ends (center 92 + roughly half the node height). */
const NODE_BOTTOM_Y = 144;
/** Y where the infrastructure branch chips sit, below the node row. */
const BRANCH_Y = 200;

/**
 * The infrastructure each step runs on, branched underneath its node so the DAG
 * shows *where* the work happened — the agent deployment, Redis memory, the
 * Browserbase replay — with the real sponsor logos.
 */
const INFRA_BRANCHES: Array<{
  underNode: FixDagNodeId;
  Mark: (props: { className?: string }) => React.ReactElement;
  label: string;
  detail: string;
}> = [
  { underNode: "read_logs", Mark: McpMark, label: "MCP", detail: "Supabase context" },
  { underNode: "plan_fix", Mark: DevinMark, label: "Devin", detail: "fix agent deployed" },
  { underNode: "dispatch_fix", Mark: RedisMark, label: "Redis", detail: "warm-start memory" },
  { underNode: "run_evals", Mark: BrowserbaseMark, label: "Browserbase", detail: "cloud replay" },
];

/**
 * The roadmap each step occupies: its position in the pipeline (1–6) and a
 * representative wall-clock cost, so the DAG reads as an ordered timeline —
 * "what runs, in what order, and how long it takes".
 */
const STEP_META: Record<FixDagNodeId, { step: number; duration: string }> = {
  read_logs: { step: 1, duration: "6s" },
  plan_fix: { step: 2, duration: "6s" },
  dispatch_fix: { step: 3, duration: "6s" },
  run_evals: { step: 4, duration: "6s" },
  open_pr: { step: 5, duration: "6s" },
  merge_github: { step: 6, duration: "human" },
};

/**
 * The work that happens *inside* each pipeline stage — the nested layer the
 * fullscreen view exposes so you can see what the agent actually does under the
 * hood, not just the six top-level tiles. Each sub-step can branch further into
 * the concrete operations it performs.
 */
interface FixDagSubStep {
  label: string;
  detail: string;
  children?: FixDagSubStep[];
}

const NODE_SUBSTEPS: Record<FixDagNodeId, FixDagSubStep[]> = {
  read_logs: [
    {
      label: "Open MCP session",
      detail: "Authenticate to the Promptetheus MCP server (Supabase-backed)",
      children: [
        { label: "list_sessions", detail: "MCP tool — locate the failed run by id" },
        { label: "RLS scope", detail: "Workspace-isolated read, service role gated" },
      ],
    },
    {
      label: "Fetch trace over MCP",
      detail: "get_session_events pulls the ordered event rows from Postgres",
      children: [
        { label: "events table", detail: "seq-ordered tool calls, LLM spans, browser actions" },
        { label: "artifacts", detail: "Signed URLs for replay snapshots in Supabase Storage" },
      ],
    },
    {
      label: "Locate critical step",
      detail: "Mark the seq where the run diverged",
      children: [
        { label: "analysis_results", detail: "critical_step_seq from the detector pass" },
      ],
    },
    {
      label: "Collect evidence refs",
      detail: "Gather the receipts cited by detectors",
    },
  ],
  plan_fix: [
    {
      label: "Cluster failures",
      detail: "Group sibling sessions into one incident",
      children: [
        { label: "fingerprint", detail: "Stable hash of the failure signature" },
        { label: "representative run", detail: "Pick the clearest reproduction" },
      ],
    },
    {
      label: "Build incident bundle",
      detail: "Root cause + representative trace + labels",
      children: [
        { label: "root_cause", detail: "Synthesized from the critical step + detectors" },
        { label: "labels", detail: "Failure taxonomy applied to the cluster" },
      ],
    },
    {
      label: "Draft fix plan",
      detail: "Step-by-step change set handed to the agent",
      children: [
        { label: "target files", detail: "Files the change is expected to touch" },
        { label: "acceptance check", detail: "What the eval gate must prove" },
      ],
    },
  ],
  dispatch_fix: [
    {
      label: "Select & provision agent",
      detail: "Deploy the fix agent against the bundle",
      children: [
        { label: "pick runner", detail: "Devin or deterministic fallback" },
        { label: "spin workspace", detail: "Sandboxed container, repo cloned at HEAD" },
        { label: "mount bundle", detail: "Incident plan + evidence handed to the agent" },
      ],
    },
    {
      label: "Warm-start memory",
      detail: "Hydrate prior context from Redis",
      children: [
        { label: "load fingerprint", detail: "Recall prior attempts on this incident" },
        { label: "seed context", detail: "Pre-fill the agent's working set" },
      ],
    },
    {
      label: "Apply changes",
      detail: "Agent edits the repo on a fix branch",
      children: [
        { label: "propose diff", detail: "Agent reasons over the plan and edits files" },
        { label: "write to branch", detail: "Commit onto promptetheus/<incident>-fix" },
        { label: "local typecheck", detail: "Fast feedback before the eval gate" },
      ],
    },
  ],
  run_evals: [
    {
      label: "Spin replay sandbox",
      detail: "Browserbase cloud replay of the run",
      children: [
        { label: "rehydrate state", detail: "Restore the failing step's inputs" },
        { label: "replay headless", detail: "Re-run the agent against the candidate" },
      ],
    },
    {
      label: "Before / after diff",
      detail: "Confirm the failure no longer reproduces",
      children: [
        { label: "before", detail: "Original run still fails the assertion" },
        { label: "after", detail: "Patched run passes the same assertion" },
      ],
    },
    {
      label: "Critique gate",
      detail: "Score meaningfulness and confidence",
      children: [
        { label: "meaningful?", detail: "Reject no-op or cosmetic changes" },
        { label: "confidence", detail: "Gate threshold before a PR is opened" },
      ],
    },
  ],
  open_pr: [
    {
      label: "Create branch",
      detail: "promptetheus/<incident>-fix",
    },
    {
      label: "Commit changed files",
      detail: "Bundle the verified diff",
    },
    {
      label: "Open pull request",
      detail: "Attach evidence and eval receipts",
      children: [
        { label: "PR body", detail: "Root cause, before/after evals, evidence refs" },
        { label: "link incident", detail: "PR url written back to the incident row" },
      ],
    },
  ],
  merge_github: [
    { label: "Request review", detail: "Hand off to a human in GitHub" },
    { label: "Await approval", detail: "The loop stops here — never auto-merge" },
    { label: "Merge", detail: "A human merges from GitHub" },
  ],
};

const DAG_ICON_FRAME =
  "inline-flex size-9 shrink-0 items-center justify-center rounded-xl border border-accent/25 bg-accent-muted text-accent shadow-[0_12px_34px_hsl(var(--glow-accent)/0.18)]";

const PIPELINE_STEP_DELAY_MS = 6000;
const PIPELINE_TOTAL_DURATION_MS = PIPELINE_STEP_DELAY_MS * (FIX_DAG_NODE_IDS.length - 1);
const DEMO_NODE_DELAY_MS = PIPELINE_STEP_DELAY_MS;
const PR_POLL_INTERVAL_MS = 5000;
const PR_POLL_TIMEOUT_MS = 120000;

type DevinWorkRow = {
  detail: string;
  id: string;
  label: string;
  url?: string | null;
};

const DEFAULT_DEVIN_WORK_ORDERS: DevinWorkRow[] = [
  { detail: "replaying UI traces and fixing route behavior", id: "browser", label: "Browser agent" },
  { detail: "validating chat regressions and prompt handling", id: "chat", label: "Chat agent" },
  { detail: "checking voice workflow fallout before PR handoff", id: "voice", label: "Voice agent" },
];

export function FixDispatchDag({
  autoDemo = false,
  checkDispatchStatus,
  dispatchHeal,
  dispatchLabel = "Dispatch fix",
  layout,
  prominent = false,
  run,
}: FixDispatchDagProps) {
  const incident = run.incident ?? null;
  const isProminent = layout === "prominent" || prominent;
  const [phase, setPhase] = React.useState<FixDagPhase>("idle");
  const [activeNodeId, setActiveNodeId] = React.useState<FixDagNodeId>("read_logs");
  const [selectedNodeId, setSelectedNodeId] = React.useState<FixDagNodeId>("read_logs");
  const [report, setReport] = React.useState<HealReport | null>(null);
  const [agentDispatch, setAgentDispatch] = React.useState<AgentPrDispatchResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [fullscreen, setFullscreen] = React.useState(false);
  const [checkingPr, setCheckingPr] = React.useState(false);
  const timers = React.useRef<Array<ReturnType<typeof setTimeout>>>([]);
  const prPollStartedAt = React.useRef<number | null>(null);

  const clearTimers = React.useCallback(() => {
    for (const timer of timers.current) clearTimeout(timer);
    timers.current = [];
  }, []);

  const replayDemo = React.useCallback(() => {
    if (!incident) return;

    clearTimers();
    setPhase("running");
    setActiveNodeId("read_logs");
    setSelectedNodeId("read_logs");
    setReport(null);
    setAgentDispatch(null);
    setCheckingPr(false);
    setError(null);
    prPollStartedAt.current = null;

    FIX_DAG_NODE_IDS.slice(1).forEach((id, index) => {
      timers.current.push(
        setTimeout(() => {
          setActiveNodeId(id);
          setSelectedNodeId(id);
        }, DEMO_NODE_DELAY_MS * (index + 1)),
      );
    });
    timers.current.push(
      setTimeout(() => {
        setPhase("demo_complete");
        setActiveNodeId("merge_github");
        setSelectedNodeId("merge_github");
      }, DEMO_NODE_DELAY_MS * (FIX_DAG_NODE_IDS.length - 1)),
    );
  }, [clearTimers, incident]);

  React.useEffect(() => {
    clearTimers();
    setPhase("idle");
    setActiveNodeId("read_logs");
    setSelectedNodeId("read_logs");
    setReport(null);
    setAgentDispatch(null);
    setCheckingPr(false);
    setError(null);
    prPollStartedAt.current = null;
    return clearTimers;
  }, [clearTimers, incident?.id, run.session.id]);

  React.useEffect(() => {
    if (!autoDemo || !incident) return;
    replayDemo();
    return clearTimers;
  }, [autoDemo, clearTimers, incident, replayDemo, run.session.id]);

  React.useEffect(() => {
    if (!fullscreen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreen(false);
    };
    document.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [fullscreen]);

  const projection = projectFixDispatchDag({
    activeNodeId,
    error,
    incident,
    phase,
    report,
  });

  React.useEffect(() => {
    setSelectedNodeId(projection.selectedDefaultNodeId);
  }, [projection.selectedDefaultNodeId]);

  const selectedNode =
    projection.nodes.find((node) => node.id === selectedNodeId) ??
    projection.nodes.find((node) => node.id === projection.currentNodeId) ??
    projection.nodes[0];
  const evidence = buildFixDagEvidence({
    activeNodeId: selectedNode?.id ?? projection.currentNodeId,
    error,
    phase,
    report,
    run,
  });

  const checkForPr = React.useCallback(async () => {
    if (!incident || !agentDispatch || checkingPr || agentDispatchHasOpenedPr(agentDispatch)) return;

    setCheckingPr(true);
    try {
      const updated = await (checkDispatchStatus ?? defaultCheckDispatchStatus)({
        dispatchResult: agentDispatch,
        incidentId: incident.id,
        sessionId: run.session.id,
      });
      setError(null);
      setAgentDispatch(updated);
      if (agentDispatchHasOpenedPr(updated)) {
        const normalizedReport = agentDispatchToHealReport(updated, incident.id);
        setReport(normalizedReport);
        setPhase("pr_opened");
        setActiveNodeId("merge_github");
        setSelectedNodeId("merge_github");
      } else {
        setReport(null);
        setPhase("waiting_for_pr");
        setActiveNodeId("open_pr");
        setSelectedNodeId("open_pr");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to check Devin PR status.");
      setPhase("waiting_for_pr");
      setActiveNodeId("open_pr");
      setSelectedNodeId("open_pr");
    } finally {
      setCheckingPr(false);
    }
  }, [agentDispatch, checkDispatchStatus, checkingPr, incident, run.session.id]);

  React.useEffect(() => {
    if (!incident || phase !== "waiting_for_pr" || !agentDispatch || agentDispatchHasOpenedPr(agentDispatch)) return;
    if (agentDispatch.trackingStatus === "tracking_unavailable") return;

    if (prPollStartedAt.current === null) prPollStartedAt.current = Date.now();
    if (Date.now() - prPollStartedAt.current >= PR_POLL_TIMEOUT_MS) return;

    const timer = setTimeout(() => {
      void checkForPr();
    }, PR_POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [agentDispatch, checkForPr, incident, phase]);

  const dispatch = React.useCallback(async () => {
    if (!incident || phase === "running") return;

    clearTimers();
    const startedAt = Date.now();
    setPhase("running");
    setActiveNodeId("read_logs");
    setSelectedNodeId("read_logs");
    setReport(null);
    setAgentDispatch(null);
    setCheckingPr(false);
    setError(null);
    prPollStartedAt.current = null;

    FIX_DAG_NODE_IDS.slice(1, -1).forEach((id, index) => {
      timers.current.push(
        setTimeout(() => {
          setActiveNodeId(id);
          setSelectedNodeId(id);
        }, PIPELINE_STEP_DELAY_MS * (index + 1)),
      );
    });

    const settle = (callback: () => void) => {
      const remaining = Math.max(0, PIPELINE_TOTAL_DURATION_MS - (Date.now() - startedAt));
      timers.current.push(setTimeout(callback, remaining));
    };

    try {
      const result = await (dispatchHeal ?? defaultDispatchHeal)(incident.id, run);
      settle(() => {
        if (result === null) {
          setPhase("demo");
          setActiveNodeId("open_pr");
          setSelectedNodeId("open_pr");
          return;
        }
        if (isAgentPrDispatchResult(result)) {
          setAgentDispatch(result);
          if (!agentDispatchHasOpenedPr(result) && result.status !== "error") {
            setReport(null);
            setPhase("waiting_for_pr");
            setActiveNodeId("open_pr");
            setSelectedNodeId("open_pr");
            prPollStartedAt.current = Date.now();
            return;
          }
        } else {
          setAgentDispatch(null);
        }
        const normalizedReport = isAgentPrDispatchResult(result)
          ? agentDispatchToHealReport(result, incident.id)
          : result;
        setReport(normalizedReport);
        if (normalizedReport.status === "pr_opened") {
          setPhase("pr_opened");
          setActiveNodeId(normalizedReport.pr?.fallback ? "open_pr" : "merge_github");
          setSelectedNodeId(normalizedReport.pr?.fallback ? "open_pr" : "merge_github");
        } else {
          setPhase("escalated");
          setActiveNodeId("run_evals");
          setSelectedNodeId("run_evals");
        }
      });
    } catch (caught) {
      settle(() => {
        setError(caught instanceof Error ? caught.message : "Unable to dispatch fix.");
        setPhase("error");
        setActiveNodeId("dispatch_fix");
        setSelectedNodeId("dispatch_fix");
      });
    }
  }, [clearTimers, dispatchHeal, incident, phase, run]);

  const attempts = report?.attempts ?? 0;
  const evalAttempt = React.useMemo(
    () => [...(report?.trail ?? [])].reverse().find((attempt) => attempt.eval),
    [report],
  );
  const confidence = evalAttempt?.eval ? averageEvalConfidence(evalAttempt.eval) : null;
  const buttonLabel =
    autoDemo
      ? phase === "running"
        ? "Running demo..."
        : "Replay DAG"
      : phase === "waiting_for_pr"
        ? checkingPr
          ? "Checking..."
          : "Check for PR"
        : phase === "running"
          ? "Dispatching..."
          : report || phase === "demo" || phase === "error"
            ? "Re-run dispatch"
            : dispatchLabel;
  const buttonAction = autoDemo ? replayDemo : phase === "waiting_for_pr" ? checkForPr : dispatch;
  const buttonBusy = phase === "running" || checkingPr;

  return (
    <div className="space-y-3" aria-label="Fix dispatch DAG">
      <div
        className={cn(
          "landing-framed-surface surface-hover p-3",
          isProminent && "border-accent/25 bg-accent/[0.04] p-4",
        )}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/40 px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
              <Network className="size-3" aria-hidden="true" />
              Powered by Orkes AgentSpan
            </span>
            <div className="flex flex-wrap items-center gap-2">
              {isProminent ? (
                <span className={DAG_ICON_FRAME} aria-hidden="true">
                  <Sparkles className="size-4" strokeWidth={1.8} />
                </span>
              ) : null}
              <p className="text-sm font-semibold text-foreground">{projection.headline}</p>
              <ModeTag mode={projection.mode} />
              {autoDemo ? <LabelTag label="30s demo loop" /> : null}
              {projection.prPreview ? <LabelTag label="PR preview" /> : null}
              {attempts > 0 ? <LabelTag label={`${attempts} attempt${attempts === 1 ? "" : "s"}`} /> : null}
              {confidence !== null ? <LabelTag label={`eval ${pct(confidence)}`} /> : null}
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">
              {projection.detail}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              type="button"
              variant="outline"
              className="min-h-10"
              size="sm"
              onClick={() => setFullscreen(true)}
              disabled={!incident}
              aria-label="Expand DAG to fullscreen"
            >
              <Maximize2 className="size-3.5" strokeWidth={1.8} />
              Expand
            </Button>
            <Button
              type="button"
              size="sm"
              className="min-h-10"
              onClick={buttonAction}
              disabled={!incident || buttonBusy}
              aria-label={
                incident
                  ? phase === "waiting_for_pr"
                    ? "Check for Devin PR"
                    : "Dispatch fix for selected run"
                  : "Dispatch fix unavailable"
              }
            >
              {buttonBusy ? (
                <Loader2 className="size-3.5 animate-spin" strokeWidth={1.8} />
              ) : (
                <Sparkles className="size-3.5" strokeWidth={1.8} />
              )}
              {buttonLabel}
            </Button>
          </div>
        </div>
      </div>

      {phase === "waiting_for_pr" ? (
        <DevinAgentsWorkingPanel agentDispatch={agentDispatch} />
      ) : null}

      <div className={cn(isProminent && "flex flex-col gap-3")}>
        <div className="landing-framed-surface overflow-hidden">
        <div className="overflow-x-auto">
          <div
            className="relative"
            style={{ width: CANVAS.width, height: CANVAS.height }}
          >
            <svg
              className="absolute inset-0"
              width={CANVAS.width}
              height={CANVAS.height}
              aria-hidden="true"
            >
              <style>
                {`
                  @keyframes fix-dag-edge-flow {
                    from { stroke-dashoffset: 0; }
                    to { stroke-dashoffset: -24; }
                  }
                `}
              </style>
              {projection.edges.map((edge) => {
                const from = NODE_POSITIONS[edge.from];
                const to = NODE_POSITIONS[edge.to];
                const active = edge.status === "active";
                return (
                  <line
                    key={`${edge.from}-${edge.to}`}
                    x1={from.x + NODE_WIDTH / 2}
                    y1={from.y}
                    x2={to.x - NODE_WIDTH / 2}
                    y2={to.y}
                    strokeLinecap="round"
                    strokeWidth={active ? 2.5 : 1.5}
                    className={edgeStroke(edge.status)}
                    style={{
                      animation: active
                        ? "fix-dag-edge-flow 1s linear infinite"
                        : undefined,
                      strokeDasharray: active ? "8 8" : edge.status === "pending" ? "4 8" : undefined,
                    }}
                  />
                );
              })}
            </svg>

            {projection.nodes.map((node) => (
              <FixDagNodeCard
                key={node.id}
                current={node.id === projection.currentNodeId}
                node={node}
                selected={node.id === selectedNode?.id}
                onSelect={() => setSelectedNodeId(node.id)}
              />
            ))}

            {INFRA_BRANCHES.map((branch) => {
              const node = projection.nodes.find((n) => n.id === branch.underNode);
              const reached = node ? node.status !== "pending" : false;
              return (
                <InfraBranch
                  key={branch.label}
                  x={NODE_POSITIONS[branch.underNode].x}
                  Mark={branch.Mark}
                  label={branch.label}
                  detail={branch.detail}
                  reached={reached}
                />
              );
            })}
          </div>
        </div>

        <div className="border-t border-border/70 bg-panel/65 p-3">
          <NodeInspector
            node={selectedNode}
            prPreview={projection.prPreview}
            prUrl={projection.prUrl}
            run={run}
          />
        </div>
        </div>

        {isProminent ? <ProofPanel agentDispatch={agentDispatch} evidence={evidence} /> : null}
      </div>

      {fullscreen ? (
        <FixDagFullscreen
          agentDispatch={agentDispatch}
          buttonLabel={buttonLabel}
          buttonBusy={buttonBusy}
          evidence={evidence}
          onClose={() => setFullscreen(false)}
          onDispatch={buttonAction}
          phase={phase}
          projection={projection}
          run={run}
          selectedNodeId={selectedNode?.id ?? projection.currentNodeId}
          onSelectNode={setSelectedNodeId}
        />
      ) : null}
    </div>
  );
}

/**
 * One row of the nested "under the hood" tree. Renders an arbitrarily deep tree
 * with file-explorer style branch connectors (the parent `ul` draws the vertical
 * spine, each row draws its own elbow) so every layer reads as indented and
 * clearly *underneath* its parent — down to individual trace events.
 */
interface DagTreeItem {
  id: string;
  label: string;
  detail?: string;
  mono?: boolean;
  tone?: "default" | "accent" | "success" | "warning" | "muted";
  Mark?: (props: { className?: string }) => React.ReactElement;
  href?: string;
  children?: DagTreeItem[];
}

function dagDotTone(tone: DagTreeItem["tone"]): string {
  if (tone === "accent") return "bg-accent/70";
  if (tone === "success") return "bg-success";
  if (tone === "warning") return "bg-warning";
  if (tone === "muted") return "bg-border";
  return "bg-muted-foreground/50";
}

function dagTextTone(tone: DagTreeItem["tone"]): string {
  if (tone === "accent") return "text-accent";
  if (tone === "success") return "text-success";
  if (tone === "warning") return "text-warning";
  if (tone === "muted") return "text-muted-foreground";
  return "text-foreground";
}

function DagTree({ items, surface = "bg-panel" }: { items: DagTreeItem[]; surface?: string }) {
  return (
    <ul className="relative ml-[7px] list-none border-l border-border/60 pl-0">
      {items.map((item, index) => (
        <DagTreeRow
          key={item.id}
          item={item}
          last={index === items.length - 1}
          surface={surface}
        />
      ))}
    </ul>
  );
}

function DagTreeRow({
  item,
  last,
  surface,
}: {
  item: DagTreeItem;
  last: boolean;
  surface: string;
}) {
  const Mark = item.Mark;
  return (
    <li className="relative pl-4">
      {/* horizontal elbow into the row */}
      <span aria-hidden className="absolute left-0 top-[12px] h-px w-3 bg-border/60" />
      {/* mask the spine below the last child so the branch terminates cleanly */}
      {last ? (
        <span aria-hidden className={cn("absolute -left-px top-[13px] bottom-0 w-px", surface)} />
      ) : null}
      <div className="flex items-start gap-2 py-1">
        {Mark ? (
          <Mark className="mt-0.5 size-3.5 shrink-0" />
        ) : (
          <span
            aria-hidden
            className={cn("mt-[7px] size-1.5 shrink-0 rounded-full", dagDotTone(item.tone))}
          />
        )}
        <div className="min-w-0">
          {item.href ? (
            <a
              href={item.href}
              target="_blank"
              rel="noreferrer"
              className={cn(
                "text-xs font-medium underline-offset-2 hover:underline",
                dagTextTone(item.tone),
              )}
            >
              {item.label}
              <ExternalLink className="ml-1 inline size-3" aria-hidden="true" />
            </a>
          ) : (
            <span className={cn("text-xs font-medium", item.mono && "mono", dagTextTone(item.tone))}>
              {item.label}
            </span>
          )}
          {item.detail ? (
            <span className="ml-1.5 break-words text-xs text-muted-foreground">— {item.detail}</span>
          ) : null}
        </div>
      </div>
      {item.children?.length ? <DagTree items={item.children} surface={surface} /> : null}
    </li>
  );
}

function subStepsToItems(prefix: string, steps: FixDagSubStep[]): DagTreeItem[] {
  return steps.map((step, index) => {
    const id = `${prefix}-${index}`;
    return {
      id,
      label: step.label,
      detail: step.detail,
      children: step.children ? subStepsToItems(id, step.children) : undefined,
    } satisfies DagTreeItem;
  });
}

function traceTreeToItems(nodes: TraceNode[]): DagTreeItem[] {
  return nodes.map((node) => {
    const summary = eventSummary(node.event);
    return {
      id: `ev-${node.event.seq}`,
      label: `#${node.event.seq} ${eventTitle(node.event)}`,
      detail: summary ? summary.slice(0, 120) : undefined,
      mono: true,
      tone: node.event.type === "error" ? "warning" : "muted",
      children: node.children.length ? traceTreeToItems(node.children) : undefined,
    } satisfies DagTreeItem;
  });
}

/** Build the nested tree under a stage: its sub-steps, the real trace events it
 *  touches, the infra it deploys onto, and the PR branch / files it carries. */
function buildStageChildren(
  node: FixDagNode,
  run: LogRun,
  ctx: {
    infra: (typeof INFRA_BRANCHES)[number] | null;
    prBranch: string | null;
    prFiles: string[];
    prUrl: string | null;
  },
): DagTreeItem[] {
  const items: DagTreeItem[] = subStepsToItems(`${node.id}-sub`, NODE_SUBSTEPS[node.id]);

  if (node.id === "read_logs") {
    // Nest the real trace events MCP returned under the "Fetch trace" sub-step.
    const traceItems = traceTreeToItems(buildTraceTree(run.events));
    if (traceItems.length && items[1]) {
      items[1] = {
        ...items[1],
        children: [...(items[1].children ?? []), ...traceItems],
      };
    }
    const criticalSeq =
      run.analysis?.critical_step_seq ?? run.incident?.critical_step_seq ?? null;
    const critical =
      criticalSeq === null ? undefined : run.events.find((event) => event.seq === criticalSeq);
    if (critical && items[2]) {
      items[2] = {
        ...items[2],
        tone: "warning",
        children: [
          ...(items[2].children ?? []),
          {
            id: `crit-${critical.seq}`,
            label: `#${critical.seq} ${eventTitle(critical)}`,
            detail: eventSummary(critical) || undefined,
            mono: true,
            tone: "warning",
          },
        ],
      };
    }
  }

  if (ctx.infra) {
    items.push({
      id: `${node.id}-infra`,
      label: ctx.infra.label,
      detail: ctx.infra.detail,
      Mark: ctx.infra.Mark,
      tone: "accent",
    });
  }
  if (ctx.prBranch) {
    items.push({
      id: `${node.id}-branch`,
      label: ctx.prBranch,
      detail: "fix branch",
      mono: true,
      tone: "accent",
      Mark: (props) => <GitBranch className={cn("text-accent", props.className)} />,
    });
  }
  if (ctx.prFiles.length) {
    items.push({
      id: `${node.id}-files`,
      label: "Changed files",
      children: ctx.prFiles.map((file) => ({
        id: `file-${node.id}-${file}`,
        label: file,
        mono: true,
        tone: "muted",
        Mark: (props) => <FileCode2 className={cn("text-muted-foreground", props.className)} />,
      })),
    });
  }
  if (ctx.prUrl) {
    items.push({
      id: `${node.id}-pr`,
      label: "Open PR in GitHub",
      href: ctx.prUrl,
      tone: "success",
    });
  }

  return items;
}

function DevinWorkStyles() {
  return (
    <style>
      {`
        @keyframes devin-work-lane {
          0% { transform: translateX(-120%); opacity: 0; }
          16% { opacity: 1; }
          76% { opacity: 1; }
          100% { transform: translateX(220%); opacity: 0; }
        }
        @keyframes devin-node-glow {
          0%, 100% { transform: scale(0.92); opacity: 0.45; }
          50% { transform: scale(1.08); opacity: 0.85; }
        }
        @media (prefers-reduced-motion: reduce) {
          .devin-work-lane,
          .devin-node-glow {
            animation: none !important;
            transform: none !important;
          }
        }
      `}
    </style>
  );
}

function devinWorkRows(agentDispatch: AgentPrDispatchResult | null) {
  const requests = agentDispatch?.pullRequests ?? [];
  if (!requests.length) return DEFAULT_DEVIN_WORK_ORDERS;

  return requests.map((pullRequest) => {
    const prUrl = agentPullRequestPrUrl(pullRequest);
    return {
      detail: prUrl
        ? `PR #${pullRequest.openedPrNumber ?? pullRequest.number ?? "ready"} detected`
        : pullRequest.kind === "devin_session"
          ? "session live; creating branch, patch, evals, and PR"
          : pullRequest.kind === "devin_issue"
            ? "GitHub issue assigned; Devin is opening the PR"
            : "PR handoff in progress",
      id: pullRequest.externalId ?? `${pullRequest.agentType}-${pullRequest.number}`,
      label: `${agentTypeLabel(pullRequest.agentType)} Devin agent`,
      url: prUrl ?? pullRequest.url,
    };
  });
}

function agentTypeLabel(agentType: AgentPullRequestResult["agentType"]) {
  return agentType.charAt(0).toUpperCase() + agentType.slice(1);
}

function DevinAgentsWorkingPanel({
  agentDispatch,
  variant = "compact",
}: {
  agentDispatch: AgentPrDispatchResult | null;
  variant?: "compact" | "fullscreen";
}) {
  const rows = devinWorkRows(agentDispatch);
  return (
    <section
      aria-live="polite"
      className={cn(
        "landing-framed-surface overflow-hidden border-accent/25 bg-accent/[0.045]",
        variant === "fullscreen" && "mx-auto mb-4 max-w-4xl",
      )}
    >
      <DevinWorkStyles />
      <div className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <span className="relative inline-flex size-11 shrink-0 items-center justify-center rounded-2xl border border-accent/30 bg-accent-muted text-accent shadow-[0_18px_42px_hsl(var(--glow-accent)/0.18)]">
            <span
              aria-hidden="true"
              className="devin-node-glow absolute inset-1 rounded-2xl border border-accent/35"
              style={{ animation: "devin-node-glow 1.8s ease-in-out infinite" }}
            />
            <DevinMark className="relative size-5" />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground">
              Devin agents are fixing the project
            </p>
            <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
              Branch work, eval checks, and PR creation are running in Devin; Promptetheus is
              watching GitHub for the real PR links.
            </p>
          </div>
        </div>
        <span className="inline-flex min-h-9 shrink-0 items-center gap-2 rounded-full border border-accent/25 bg-panel/70 px-3 text-xs font-medium text-accent">
          <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" strokeWidth={1.8} />
          PR detection active
        </span>
      </div>
      <div
        className={cn(
          "grid gap-px border-t border-border/70 bg-border/60",
          variant === "fullscreen" ? "sm:grid-cols-3" : "lg:grid-cols-3",
        )}
      >
        {rows.map((row, index) => (
          <div key={row.id} className="bg-panel/80 p-3">
            <div className="flex items-center justify-between gap-2">
              {row.url ? (
                <a
                  href={row.url}
                  target="_blank"
                  rel="noreferrer"
                  className="min-w-0 truncate text-xs font-semibold text-foreground underline-offset-2 hover:underline"
                >
                  {row.label}
                </a>
              ) : (
                <span className="min-w-0 truncate text-xs font-semibold text-foreground">
                  {row.label}
                </span>
              )}
              <span className="flex shrink-0 items-center gap-1 text-[10px] uppercase text-accent">
                <CircleDot className="size-2.5 animate-pulse motion-reduce:animate-none" strokeWidth={1.8} />
                fixing
              </span>
            </div>
            <p className="mt-1 min-h-8 text-xs leading-4 text-muted-foreground">{row.detail}</p>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <span
                aria-hidden="true"
                className="devin-work-lane block h-full w-1/2 rounded-full bg-accent/70"
                style={{
                  animation: "devin-work-lane 1.65s ease-in-out infinite",
                  animationDelay: `${index * 180}ms`,
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function DevinStageLoadingRows({ agentDispatch }: { agentDispatch: AgentPrDispatchResult | null }) {
  const rows = devinWorkRows(agentDispatch);
  return (
    <div className="rounded-xl border border-accent/25 bg-accent/[0.04] p-3">
      <div className="flex items-center gap-2">
        <Loader2 className="size-3.5 animate-spin text-accent motion-reduce:animate-none" strokeWidth={1.8} />
        <p className="text-xs font-semibold text-foreground">
          Devin is working through the prebuilt PR handoff steps
        </p>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        {rows.map((row, index) => (
          <div key={row.id} className="rounded-lg border border-border/70 bg-panel/70 p-2">
            <p className="truncate text-[11px] font-semibold text-foreground">{row.label}</p>
            <p className="mt-0.5 min-h-8 text-[11px] leading-4 text-muted-foreground">
              {row.detail}
            </p>
            <div className="mt-2 flex items-center gap-1">
              {[0, 1, 2].map((dot) => (
                <span
                  key={dot}
                  aria-hidden="true"
                  className="size-1.5 rounded-full bg-accent animate-pulse motion-reduce:animate-none"
                  style={{ animationDelay: `${index * 120 + dot * 160}ms` }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * The near-fullscreen "under the hood" view. Drops the filter/shortcut chrome
 * and expands every pipeline stage into a deeply nested branch tree — sub-steps,
 * real trace events, deployed infra, and the PR — while the Proof receipts live
 * in a drawer that pops open from the right.
 */
function FixDagFullscreen({
  agentDispatch,
  buttonLabel,
  buttonBusy,
  evidence,
  onClose,
  onDispatch,
  phase,
  projection,
  run,
  selectedNodeId,
  onSelectNode,
}: {
  agentDispatch: AgentPrDispatchResult | null;
  buttonLabel: string;
  buttonBusy: boolean;
  evidence: FixDagEvidence;
  onClose: () => void;
  onDispatch: () => void;
  phase: FixDagPhase;
  projection: ReturnType<typeof projectFixDispatchDag>;
  run: LogRun;
  selectedNodeId: FixDagNodeId;
  onSelectNode: (id: FixDagNodeId) => void;
}) {
  const [collapsed, setCollapsed] = React.useState<Set<FixDagNodeId>>(new Set());
  const [drawerOpen, setDrawerOpen] = React.useState(true);

  const prFiles =
    projection.prPreview || projection.prUrl
      ? run.incident?.fix_agent_result?.changed_files ?? []
      : [];
  const prBranch = `promptetheus/${run.incident?.id ?? run.session.id}-fix`;

  const toggleStage = (id: FixDagNodeId) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectStage = (id: FixDagNodeId) => {
    onSelectNode(id);
    setDrawerOpen(true);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Fix dispatch DAG — fullscreen"
      className="fixed inset-0 z-50 flex flex-col bg-background/95 backdrop-blur-sm"
    >
      <header className="flex items-center justify-between gap-3 border-b border-border/70 bg-panel/80 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="inline-flex size-8 items-center justify-center rounded-lg border border-accent/25 bg-accent-muted text-accent">
            <Network className="size-4" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-foreground">{projection.headline}</p>
            <p className="truncate text-xs text-muted-foreground">{projection.detail}</p>
          </div>
          <ModeTag mode={projection.mode} />
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            type="button"
            size="sm"
            onClick={onDispatch}
            disabled={!run.incident || buttonBusy}
            aria-label={
              run.incident
                ? phase === "waiting_for_pr"
                  ? "Check for Devin PR"
                  : "Dispatch fix for selected run"
                : "Dispatch fix unavailable"
            }
          >
            {buttonBusy ? (
              <Loader2 className="size-3.5 animate-spin" strokeWidth={1.8} />
            ) : (
              <Sparkles className="size-3.5" strokeWidth={1.8} />
            )}
            {buttonLabel}
          </Button>
          <Button
            type="button"
            variant={drawerOpen ? "default" : "outline"}
            size="sm"
            aria-pressed={drawerOpen}
            onClick={() => setDrawerOpen((open) => !open)}
          >
            <ShieldCheck className="size-3.5" />
            Proof
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onClose} aria-label="Close fullscreen DAG">
            <Minimize2 className="size-3.5" />
            Collapse
          </Button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex size-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="size-4" />
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-y-auto px-4 py-5">
          {phase === "waiting_for_pr" ? (
            <DevinAgentsWorkingPanel agentDispatch={agentDispatch} variant="fullscreen" />
          ) : null}

          <ol className="mx-auto flex max-w-4xl flex-col gap-3">
            {projection.nodes.map((node, index) => {
              const infra = INFRA_BRANCHES.find((branch) => branch.underNode === node.id) ?? null;
              const isPrStage = node.id === "open_pr" || node.id === "merge_github";
              const children = buildStageChildren(node, run, {
                infra,
                prBranch: isPrStage ? prBranch : null,
                prFiles: isPrStage ? prFiles : [],
                prUrl: isPrStage ? projection.prUrl : null,
              });
              return (
                <FixDagStageLayer
                  key={node.id}
                  node={node}
                  children={children}
                  collapsed={collapsed.has(node.id)}
                  loading={phase === "waiting_for_pr" && node.id === "open_pr"}
                  agentDispatch={agentDispatch}
                  onToggle={() => toggleStage(node.id)}
                  selected={node.id === selectedNodeId}
                  onSelect={() => selectStage(node.id)}
                  last={index === projection.nodes.length - 1}
                />
              );
            })}
          </ol>
        </div>

        <aside
          aria-label="Proof receipts"
          className={cn(
            "shrink-0 overflow-hidden border-l border-border/70 bg-panel/60 transition-[width] duration-300",
            drawerOpen ? "w-[360px]" : "w-0 border-l-0",
          )}
        >
          <div className="flex h-full w-[360px] flex-col">
            <div className="flex items-center justify-between gap-2 border-b border-border/70 px-3 py-2.5">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Proof — {evidence.title}
              </p>
              <button
                type="button"
                onClick={() => setDrawerOpen(false)}
                aria-label="Close proof drawer"
                className="flex size-7 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="size-3.5" />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              <ProofPanel agentDispatch={agentDispatch} evidence={evidence} />
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

/**
 * A single pipeline stage rendered as an expandable layer: the stage tile, then
 * its nested branch tree (sub-steps → trace events → infra → PR) indented
 * underneath. Collapsible so deep runs stay scannable.
 */
function FixDagStageLayer({
  agentDispatch,
  node,
  children,
  collapsed,
  loading,
  onToggle,
  selected,
  onSelect,
  last,
}: {
  agentDispatch: AgentPrDispatchResult | null;
  node: FixDagNode;
  children: DagTreeItem[];
  collapsed: boolean;
  loading: boolean;
  onToggle: () => void;
  selected: boolean;
  onSelect: () => void;
  last: boolean;
}) {
  const Icon = NODE_ICON[node.id];
  const meta = STEP_META[node.id];
  const tone = nodeTone(node.status);
  const reached = node.status !== "pending" && node.status !== "disabled";

  return (
    <li className="relative">
      {!last ? (
        <span
          aria-hidden
          className={cn(
            "absolute left-[18px] top-[48px] bottom-[-12px] w-px",
            reached ? "bg-accent/40" : "bg-border",
          )}
        />
      ) : null}
      <div
        className={cn(
          "rounded-xl border bg-panel transition-colors",
          tone.border,
          selected && "ring-2 ring-accent/25",
        )}
      >
        <div className="flex items-center gap-2 px-2 py-2.5">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={!collapsed}
            aria-label={collapsed ? "Expand stage" : "Collapse stage"}
            className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronRight className={cn("size-4 transition-transform", !collapsed && "rotate-90")} />
          </button>
          <button
            type="button"
            onClick={onSelect}
            aria-pressed={selected}
            className="flex min-w-0 flex-1 items-center gap-3 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span
              className={cn(
                "relative inline-flex size-9 shrink-0 items-center justify-center rounded-lg border",
                tone.icon,
              )}
            >
              <Icon className="size-4" aria-hidden="true" />
              {node.status === "active" ? (
                <span className="absolute inset-0 animate-pulse rounded-lg ring-2 ring-accent/40" />
              ) : null}
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2">
                <span className="text-sm font-semibold text-foreground">
                  {meta.step}. {node.label}
                </span>
                <span className={cn("mono text-[10px] uppercase", tone.text)}>
                  {node.status.replace("_", " ")}
                </span>
              </span>
              <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                {node.description}
              </span>
            </span>
            <span className="mono hidden shrink-0 items-center gap-1 text-[11px] text-muted-foreground sm:flex">
              <Timer className="size-3" aria-hidden="true" />
              {meta.duration}
            </span>
          </button>
        </div>

        {!collapsed ? (
          <div className="space-y-3 border-t border-border/60 px-3 py-3 pl-11">
            {loading ? <DevinStageLoadingRows agentDispatch={agentDispatch} /> : null}
            <DagTree items={children} />
          </div>
        ) : null}
      </div>
    </li>
  );
}

async function defaultDispatchHeal(incidentId: string): Promise<HealReport | null> {
  return healIncident(incidentId);
}

async function defaultCheckDispatchStatus(input: {
  dispatchResult: AgentPrDispatchResult;
  incidentId: string;
  sessionId: string;
}): Promise<AgentPrDispatchResult> {
  return checkLogsAgentPrStatus(input);
}

function isAgentPrDispatchResult(
  result: HealReport | AgentPrDispatchResult,
): result is AgentPrDispatchResult {
  return "pullRequests" in result;
}

function agentDispatchHasOpenedPr(result: AgentPrDispatchResult): boolean {
  return result.pullRequests.some((pullRequest) => Boolean(agentPullRequestPrUrl(pullRequest)));
}

function agentPullRequestPrUrl(pullRequest: AgentPullRequestResult): string | null {
  if (pullRequest.openedPrUrl) return pullRequest.openedPrUrl;
  if (pullRequest.kind === "pull_request") return pullRequest.url;
  return null;
}

function agentDispatchToHealReport(
  result: AgentPrDispatchResult,
  incidentId: string,
): HealReport {
  const primary = result.pullRequests.find((pullRequest) => agentPullRequestPrUrl(pullRequest));
  const opened = result.pullRequests.filter((pullRequest) => agentPullRequestPrUrl(pullRequest));
  const devinHandoffMode = result.pullRequests.some((pullRequest) =>
    pullRequest.kind === "devin_session" || pullRequest.kind === "devin_issue",
  );
  return {
    attempts: result.pullRequests.length,
    incident_id: incidentId,
    warm_start: null,
    orchestrator: result.orchestrator === "orkes" ? "orkes" : "local Orkes workflow",
    pr: primary
      ? {
          branch: primary.openedPrBranch ?? primary.branch ?? undefined,
          changed_files: result.pullRequests
            .filter((pullRequest) => agentPullRequestPrUrl(pullRequest))
            .map((pullRequest) =>
              pullRequest.kind === "devin_session" || pullRequest.kind === "devin_issue"
                ? `${pullRequest.agentType} Devin-opened PR`
                : `${pullRequest.agentType} agent`,
            ),
          fallback: false,
          pr_url: agentPullRequestPrUrl(primary),
          title: primary.openedPrTitle ?? primary.title,
        }
      : null,
    reason: opened.length
      ? null
      : result.trackingStatus === "tracking_unavailable"
        ? "Devin dispatched; GitHub PR tracking unavailable."
        : "Waiting for Devin to open a GitHub PR.",
    source: devinHandoffMode
      ? `logs_orkes_devin_pr_tracking:${result.targetRepo}`
      : `logs_agent_dispatch:${result.targetRepo}`,
    status: opened.length ? "pr_opened" : "escalated",
    trail: [
      {
        attempt: 1,
        critique: {
          approved: opened.length === result.pullRequests.length,
          confidence: opened.length / Math.max(1, result.pullRequests.length),
          reason:
            opened.length === result.pullRequests.length
              ? devinHandoffMode
                ? "Browser, chat, and voice Devin PRs detected."
                : "Browser, chat, and voice agent PRs opened."
              : `${opened.length} of ${result.pullRequests.length} agent dispatches completed.`,
        },
        diagnosis: devinHandoffMode
          ? `Orkes workflow dispatched Devin and tracked GitHub PRs in ${result.targetRepo} from the selected logs.`
          : `Dispatch selected logs into ${result.targetRepo} agent PRs.`,
        eval: null,
        kind: "agent_pr_dispatch",
        passed: opened.length > 0,
        regression: {
          opened_prs: opened.length,
          total_prs: result.pullRequests.length,
        },
        runner: "codex",
      },
    ],
    workflow_run_id: result.workflowRunId ?? null,
  };
}

function ProofPanel({
  agentDispatch,
  evidence,
}: {
  agentDispatch: AgentPrDispatchResult | null;
  evidence: FixDagEvidence;
}) {
  return (
    <aside className="landing-framed-surface overflow-hidden" aria-label="Fix DAG proof">
      <div className="border-b border-border/70 bg-panel/65 p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase text-muted-foreground">Proof</p>
            <h3 className="mt-1 truncate text-sm font-semibold text-foreground">{evidence.title}</h3>
          </div>
          <EvidenceModeTag mode={evidence.mode} />
        </div>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">{evidence.subtitle}</p>
      </div>

      <div className="divide-y divide-border/70">
        {evidence.items.map((item) => (
          <div
            key={`${item.label}-${item.value}`}
            className="grid grid-cols-[92px_minmax(0,1fr)] gap-3 px-3 py-2.5"
          >
            <span className="text-[10px] font-semibold uppercase text-muted-foreground">
              {item.label}
            </span>
            {item.href ? (
              <a
                href={item.href}
                target="_blank"
                rel="noreferrer"
                className={cn(
                  "min-w-0 truncate text-xs font-medium underline-offset-4 hover:underline",
                  evidenceToneClass(item.tone),
                )}
              >
                {item.value}
                <ExternalLink className="ml-1 inline size-3" aria-hidden="true" strokeWidth={1.8} />
              </a>
            ) : (
              <span className={cn("min-w-0 break-words text-xs font-medium", evidenceToneClass(item.tone))}>
                {item.value}
              </span>
            )}
          </div>
        ))}
      </div>

      {evidence.details.length ? (
        <div className="border-t border-border/70 bg-elevated/40 p-3">
          <p className="text-[10px] font-semibold uppercase text-muted-foreground">Receipts</p>
          <ul className="mt-2 space-y-2">
            {evidence.details.slice(0, 4).map((detail) => (
              <li key={detail} className="flex gap-2 text-xs leading-5 text-muted-foreground">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-accent/70" aria-hidden="true" />
                <span className="min-w-0 break-words">{detail}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {agentDispatch ? <AgentPullRequestList result={agentDispatch} /> : null}
    </aside>
  );
}

function AgentPullRequestList({ result }: { result: AgentPrDispatchResult }) {
  const devinSessionMode = result.pullRequests.some((pullRequest) => pullRequest.kind === "devin_session");
  const devinIssueMode = !devinSessionMode && result.pullRequests.some((pullRequest) => pullRequest.kind === "devin_issue");
  return (
    <div className="border-t border-border/70 bg-panel p-3">
      {result.workflowStages?.length ? <WorkflowReceipt result={result} /> : null}
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground">
          {devinSessionMode ? "Devin sessions" : devinIssueMode ? "Devin PR requests" : "Agent PRs"}
        </p>
        <span className="mono text-[10px] text-muted-foreground">{result.targetRepo}</span>
      </div>
      {result.trackingStatus ? (
        <p
          className={cn(
            "mt-2 rounded-xl border px-3 py-2 text-xs leading-5",
            result.trackingStatus === "tracking_unavailable"
              ? "border-warning/25 bg-warning/10 text-warning"
              : result.trackingStatus === "tracking"
                ? "border-success/25 bg-success/10 text-success"
                : "border-accent/20 bg-accent-muted text-accent",
          )}
        >
          {result.trackingStatus === "tracking_unavailable"
            ? result.trackingError ?? "Devin dispatched; GitHub PR tracking unavailable."
            : result.trackingStatus === "tracking"
              ? "GitHub PR detected from Devin."
              : "Checking GitHub for a Devin-created PR."}
        </p>
      ) : null}
      <ul className="mt-2 space-y-2">
        {result.pullRequests.map((pullRequest) => (
          <AgentPullRequestItem key={pullRequest.agentType} pullRequest={pullRequest} />
        ))}
      </ul>
    </div>
  );
}

function WorkflowReceipt({ result }: { result: AgentPrDispatchResult }) {
  const orchestratorLabel = result.orchestrator === "orkes" ? "Orkes workflow" : "Local Orkes workflow";
  return (
    <div className="mb-3 rounded-xl border border-accent/20 bg-accent-muted/50 p-3 shadow-[inset_0_1px_0_hsl(0_0%_100%/0.62)]">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase text-accent">{orchestratorLabel}</p>
          <p className="mono mt-1 truncate text-[10px] text-muted-foreground">
            {result.workflowRunId ?? "workflow pending"}
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-accent/25 bg-panel/80 px-2.5 py-1 text-[10px] font-semibold uppercase text-accent">
          eval gated
        </span>
      </div>

      {result.evalGate ? (
        <div className="mt-2 rounded-xl border border-border/60 bg-panel/70 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] font-semibold uppercase text-muted-foreground">Eval gate</p>
            <span
              className={cn(
                "rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase",
                result.evalGate.status === "passed"
                  ? "border-success/25 bg-success/10 text-success"
                  : result.evalGate.status === "failed"
                    ? "border-destructive/25 bg-destructive/10 text-destructive"
                    : "border-warning/25 bg-warning/10 text-warning",
              )}
            >
              {result.evalGate.status}
            </span>
          </div>
          <p className="mt-1 text-xs leading-5 text-foreground">{result.evalGate.assertion}</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">{result.evalGate.note}</p>
          <div className="mt-2 grid grid-cols-3 gap-2 text-[10px] text-muted-foreground">
            <span>Cases {result.evalGate.caseCount}</span>
            <span>Before fail {result.evalGate.beforeFail}</span>
            <span>After fail {result.evalGate.afterFail ?? "pending"}</span>
          </div>
        </div>
      ) : null}

      {result.sentryProof ? (
        <p className="mt-2 text-xs leading-5 text-muted-foreground">
          Sentry: {result.sentryProof.configured ? "configured" : "local only"}
          {result.sentryProof.traceId ? ` - ${result.sentryProof.traceId}` : ""}. {result.sentryProof.detail}
        </p>
      ) : null}

      <ol className="mt-2 space-y-1.5">
        {(result.workflowStages ?? []).map((stage) => (
          <li key={stage.id} className="flex items-start gap-2 text-xs">
            <span
              className={cn(
                "mt-1.5 size-2 shrink-0 rounded-full",
                stage.status === "passed"
                  ? "bg-success"
                  : stage.status === "running"
                    ? "bg-accent"
                    : stage.status === "failed" || stage.status === "blocked"
                      ? "bg-destructive"
                      : "bg-muted-foreground/35",
              )}
              aria-hidden="true"
            />
            <span className="min-w-0">
              <span className="font-medium text-foreground">{stage.label}</span>
              <span className="text-muted-foreground"> - {stage.detail}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function AgentPullRequestItem({
  pullRequest,
}: {
  pullRequest: AgentPullRequestResult;
}) {
  const label = `${pullRequest.agentType[0].toUpperCase()}${pullRequest.agentType.slice(1)} agent`;
  const devinSession = pullRequest.kind === "devin_session";
  const devinIssue = pullRequest.kind === "devin_issue";
  const openedPrUrl = agentPullRequestPrUrl(pullRequest);
  return (
    <li className="rounded-xl border border-border/70 bg-elevated/45 p-3 shadow-[inset_0_1px_0_hsl(0_0%_100%/0.62)]">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold text-foreground">{label}</p>
          {openedPrUrl ? (
            <a
              href={openedPrUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-flex max-w-full items-center gap-1 truncate text-xs font-medium text-success underline-offset-4 hover:underline"
            >
              <span className="truncate">
                PR #{pullRequest.openedPrNumber ?? pullRequest.number ?? "detected"}:{" "}
                {pullRequest.openedPrTitle ?? pullRequest.title}
              </span>
              <ExternalLink className="size-3 shrink-0" aria-hidden="true" strokeWidth={1.8} />
            </a>
          ) : null}
          {pullRequest.url ? (
            <a
              href={pullRequest.url}
              target="_blank"
              rel="noreferrer"
              className={cn(
                "mt-1 inline-flex max-w-full items-center gap-1 truncate text-xs font-medium underline-offset-4 hover:underline",
                openedPrUrl ? "text-muted-foreground" : "text-accent",
              )}
            >
              <span className="truncate">
                {devinSession
                  ? `Session${pullRequest.externalId ? ` ${pullRequest.externalId}` : ""}: ${pullRequest.title}`
                  : `${devinIssue ? "Task" : "PR"} #${pullRequest.number}: ${pullRequest.title}`}
              </span>
              <ExternalLink className="size-3 shrink-0" aria-hidden="true" strokeWidth={1.8} />
            </a>
          ) : !openedPrUrl ? (
            <p className="mt-1 text-xs text-destructive">{pullRequest.error ?? "PR failed."}</p>
          ) : null}
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase",
            openedPrUrl
              ? "border-success/25 bg-success/10 text-success"
              : pullRequest.devinReviewRequested
                ? "border-success/25 bg-success/10 text-success"
                : pullRequest.devinPrRequested
                  ? "border-accent/25 bg-accent-muted text-accent"
                  : pullRequest.url
                    ? "border-warning/25 bg-warning/10 text-warning"
                    : "border-destructive/25 bg-destructive/10 text-destructive",
          )}
        >
          {openedPrUrl
            ? "PR opened"
            : pullRequest.devinReviewRequested
              ? "Devin requested"
              : pullRequest.devinPrRequested
                ? "Devin creating PR"
                : pullRequest.url
                  ? "Review pending"
                  : "Failed"}
        </span>
      </div>
    </li>
  );
}

function EvidenceModeTag({ mode }: { mode: FixDagEvidence["mode"] }) {
  const tone = {
    blocked: "border-warning/25 bg-warning/10 text-warning",
    demo: "border-warning/25 bg-warning/10 text-warning",
    live: "border-success/25 bg-success/10 text-success",
    local: "border-accent/20 bg-accent-muted text-accent",
  }[mode];
  return (
    <span className={cn("inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase", tone)}>
      {mode}
    </span>
  );
}

function evidenceToneClass(tone: FixDagEvidenceTone | undefined) {
  if (tone === "success") return "text-success";
  if (tone === "warning") return "text-warning";
  if (tone === "error") return "text-destructive";
  return "text-foreground";
}

/**
 * A sponsor-infrastructure branch dropping from a DAG node down to a logo chip,
 * showing which service that step ran on. Dims until the step is reached.
 */
function InfraBranch({
  x,
  Mark,
  label,
  detail,
  reached,
}: {
  x: number;
  Mark: (props: { className?: string }) => React.ReactElement;
  label: string;
  detail: string;
  reached: boolean;
}) {
  return (
    <div
      className={cn(
        "absolute flex -translate-x-1/2 flex-col items-center transition-opacity duration-500",
        reached ? "opacity-100" : "opacity-35",
      )}
      style={{ left: x, top: NODE_BOTTOM_Y }}
      aria-hidden="true"
    >
      <span
        className={cn(
          "w-px",
          reached ? "bg-accent/50" : "bg-border",
        )}
        style={{ height: BRANCH_Y - NODE_BOTTOM_Y - 4 }}
      />
      <span
        className={cn(
          "flex items-center gap-1.5 whitespace-nowrap rounded-lg border bg-panel px-2 py-1 shadow-sm",
          reached ? "border-accent/30" : "border-border/70",
        )}
      >
        <Mark className="size-4 shrink-0" />
        <span className="flex flex-col leading-none">
          <span className="text-[10px] font-semibold text-foreground">{label}</span>
          <span className="mt-0.5 text-[9px] text-muted-foreground">{detail}</span>
        </span>
      </span>
    </div>
  );
}

function FixDagNodeCard({
  current,
  node,
  onSelect,
  selected,
}: {
  current: boolean;
  node: FixDagNode;
  onSelect: () => void;
  selected: boolean;
}) {
  const Icon = NODE_ICON[node.id];
  const position = NODE_POSITIONS[node.id];
  const meta = STEP_META[node.id];
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "absolute min-h-[88px] w-[132px] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-2xl border bg-panel/85 p-2.5 text-left shadow-[0_16px_42px_hsl(var(--shadow-color)/0.12)] outline-none backdrop-blur transition-all hover:border-accent/30 hover:shadow-[0_18px_48px_hsl(var(--glow-accent)/0.16)] focus-visible:ring-2 focus-visible:ring-ring",
        nodeTone(node.status).border,
        selected && "ring-2 ring-accent/25",
        current && node.status === "active" && "shadow-glow",
      )}
      style={{ left: position.x, top: position.y }}
    >
      {current && node.status === "active" ? (
        <span className="absolute inset-x-0 top-0 h-0.5 animate-pulse bg-accent" />
      ) : null}
      <span
        className="absolute right-1.5 top-1.5 inline-flex size-4 items-center justify-center rounded-full border border-border/70 bg-elevated text-[9px] font-semibold text-muted-foreground"
        aria-hidden="true"
      >
        {meta.step}
      </span>
      <span className="flex min-w-0 items-center gap-2 pr-4">
        <span
          className={cn(
            "inline-flex size-8 shrink-0 items-center justify-center rounded-xl border",
            nodeTone(node.status).icon,
          )}
          aria-hidden="true"
        >
          <Icon className="size-3.5" />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-xs font-semibold text-foreground">{node.label}</span>
          <span className={cn("mono text-[9px] uppercase", nodeTone(node.status).text)}>
            {node.status.replace("_", " ")}
          </span>
        </span>
      </span>
      <span className="mt-2 flex items-center gap-1 text-[10px] text-muted-foreground">
        <Timer className="size-3 shrink-0" aria-hidden="true" />
        <span className="mono">{meta.duration}</span>
      </span>
      <span className="mt-1 block truncate text-[10px] leading-4 text-muted-foreground">
        {node.summary}
      </span>
    </button>
  );
}

function NodeInspector({
  node,
  prPreview,
  prUrl,
  run,
}: {
  node?: FixDagNode;
  prPreview: boolean;
  prUrl: string | null;
  run: LogRun;
}) {
  if (!node) return null;
  const Icon = NODE_ICON[node.id];
  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span
            className={cn("inline-flex size-9 items-center justify-center rounded-xl border", nodeTone(node.status).icon)}
            aria-hidden="true"
          >
            <Icon className="size-4" />
          </span>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-foreground">{node.label}</h3>
            <p className={cn("mono text-[10px] uppercase", nodeTone(node.status).text)}>
              {node.status}
            </p>
          </div>
        </div>
        <p className="mt-2 max-w-2xl text-xs leading-5 text-muted-foreground">
          {node.description}
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <LabelTag label={run.session.id} />
          {run.incident ? <LabelTag label={run.incident.label.replaceAll("_", " ")} /> : null}
          {prPreview ? <LabelTag label="preview only" /> : null}
        </div>
      </div>
      {node.id === "merge_github" || node.id === "open_pr" ? (
        prUrl ? (
          <Button asChild variant="outline" size="sm" className="shrink-0">
            <a href={prUrl} target="_blank" rel="noreferrer" aria-label="Open PR in GitHub">
              <ExternalLink className="size-3.5" strokeWidth={1.8} />
              Open PR in GitHub
            </a>
          </Button>
        ) : (
          <span className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-full border border-border bg-elevated px-3 text-xs text-muted-foreground">
            <CircleDot className="size-3" strokeWidth={1.8} />
            No GitHub PR link yet
          </span>
        )
      ) : null}
    </div>
  );
}

function ModeTag({ mode }: { mode: ReturnType<typeof projectFixDispatchDag>["mode"] }) {
  const tone = {
    blocked: "border-warning/25 bg-warning/10 text-warning",
    demo: "border-warning/25 bg-warning/10 text-warning",
    disabled: "border-border bg-elevated text-muted-foreground",
    error: "border-destructive/25 bg-destructive/10 text-destructive",
    idle: "border-accent/20 bg-accent-muted text-accent",
    live: "border-success/25 bg-success/10 text-success",
    running: "border-accent/20 bg-accent-muted text-accent",
  }[mode];
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase", tone)}>
      {mode === "running" ? <Loader2 className="size-3 animate-spin" strokeWidth={1.8} /> : null}
      {mode === "error" ? <AlertCircle className="size-3" strokeWidth={1.8} /> : null}
      {mode === "live" ? <CheckCircle2 className="size-3" strokeWidth={1.8} /> : null}
      {mode === "demo" ? <Network className="size-3" strokeWidth={1.8} /> : null}
      {mode.replace("_", " ")}
    </span>
  );
}

function nodeTone(status: FixDagNodeStatus) {
  if (status === "complete" || status === "ready") {
    return {
      border: "border-success/30",
      icon: "border-success/25 bg-success/10 text-success",
      text: "text-success",
    };
  }
  if (status === "active") {
    return {
      border: "border-accent/45",
      icon: "border-accent/25 bg-accent-muted text-accent",
      text: "text-accent",
    };
  }
  if (status === "blocked") {
    return {
      border: "border-warning/40",
      icon: "border-warning/25 bg-warning/10 text-warning",
      text: "text-warning",
    };
  }
  if (status === "preview") {
    return {
      border: "border-accent/25",
      icon: "border-accent/20 bg-accent-muted text-accent",
      text: "text-accent",
    };
  }
  if (status === "disabled") {
    return {
      border: "border-border/70 opacity-70",
      icon: "border-border bg-elevated text-muted-foreground",
      text: "text-muted-foreground",
    };
  }
  return {
    border: "border-border/80",
    icon: "border-border bg-elevated text-muted-foreground",
    text: "text-muted-foreground",
  };
}

function edgeStroke(status: FixDagNodeStatus) {
  if (status === "complete" || status === "ready") return "stroke-success/70";
  if (status === "active") return "stroke-accent/90";
  if (status === "blocked") return "stroke-warning/80";
  if (status === "preview") return "stroke-accent/55";
  if (status === "disabled") return "stroke-border/60";
  return "stroke-border";
}

function averageEvalConfidence(report: EvalReport): number {
  if (!report.cases.length) return 0;
  return report.cases.reduce((sum, testCase) => sum + testCase.confidence, 0) / report.cases.length;
}
