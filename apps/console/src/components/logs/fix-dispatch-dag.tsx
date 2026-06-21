"use client";

import * as React from "react";
import {
  AlertCircle,
  BookOpen,
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
  RedisMark,
} from "@/components/common/brand-marks";
import { LabelTag } from "@/components/common/label-tag";
import { Button } from "@/components/ui/button";
import { healIncident } from "@/lib/promptetheus-api";
import type { EvalReport, HealReport } from "@/lib/types";
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

type DispatchHeal = (incidentId: string) => Promise<HealReport | null>;

interface FixDispatchDagProps {
  autoDemo?: boolean;
  dispatchHeal?: DispatchHeal;
  layout?: "prominent" | "compact";
  prominent?: boolean;
  run: LogRun;
}

const NODE_ICON: Record<FixDagNodeId, LucideIcon> = {
  dispatch_fix: Sparkles,
  merge_github: GitMerge,
  open_pr: GitPullRequest,
  plan_fix: FileCode2,
  read_logs: BookOpen,
  run_evals: ShieldCheck,
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
  read_logs: { step: 1, duration: "0.4s" },
  plan_fix: { step: 2, duration: "1.2s" },
  dispatch_fix: { step: 3, duration: "3.8s" },
  run_evals: { step: 4, duration: "2.1s" },
  open_pr: { step: 5, duration: "0.9s" },
  merge_github: { step: 6, duration: "human" },
};

/**
 * The work that happens *inside* each pipeline stage — the nested layer the
 * fullscreen view exposes so you can see what the agent actually does under the
 * hood, not just the six top-level tiles.
 */
const NODE_SUBSTEPS: Record<
  FixDagNodeId,
  Array<{ label: string; detail: string }>
> = {
  read_logs: [
    { label: "Fetch trace", detail: "Pull the failed session and its ordered events" },
    { label: "Parse payloads", detail: "Decode tool calls, LLM spans, browser actions" },
    { label: "Locate critical step", detail: "Mark the seq where the run diverged" },
    { label: "Collect evidence refs", detail: "Gather the receipts cited by detectors" },
  ],
  plan_fix: [
    { label: "Cluster failures", detail: "Group sibling sessions into one incident" },
    { label: "Build incident bundle", detail: "Root cause + representative trace + labels" },
    { label: "Draft fix plan", detail: "Step-by-step change set handed to the agent" },
  ],
  dispatch_fix: [
    { label: "Provision agent", detail: "Deploy the fix agent against the bundle" },
    { label: "Warm-start memory", detail: "Hydrate prior context from Redis" },
    { label: "Apply changes", detail: "Agent edits the repo on a fix branch" },
  ],
  run_evals: [
    { label: "Spin replay sandbox", detail: "Browserbase cloud replay of the run" },
    { label: "Before / after diff", detail: "Confirm the failure no longer reproduces" },
    { label: "Critique gate", detail: "Score meaningfulness and confidence" },
  ],
  open_pr: [
    { label: "Create branch", detail: "promptetheus/<incident>-fix" },
    { label: "Commit changed files", detail: "Bundle the verified diff" },
    { label: "Open pull request", detail: "Attach evidence and eval receipts" },
  ],
  merge_github: [
    { label: "Request review", detail: "Hand off to a human in GitHub" },
    { label: "Await approval", detail: "The loop stops here — never auto-merge" },
    { label: "Merge", detail: "A human merges from GitHub" },
  ],
};

const ANIMATION_NODE_DELAY_MS = 420;
const DEMO_NODE_DELAY_MS = 3000;
const MIN_DISPATCH_DURATION_MS = 2100;

export function FixDispatchDag({
  autoDemo = false,
  dispatchHeal = healIncident,
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
  const [error, setError] = React.useState<string | null>(null);
  const [fullscreen, setFullscreen] = React.useState(false);
  const timers = React.useRef<Array<ReturnType<typeof setTimeout>>>([]);

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
    setError(null);

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
    setError(null);
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

  const dispatch = React.useCallback(async () => {
    if (!incident || phase === "running") return;

    clearTimers();
    const startedAt = Date.now();
    setPhase("running");
    setActiveNodeId("read_logs");
    setSelectedNodeId("read_logs");
    setReport(null);
    setError(null);

    FIX_DAG_NODE_IDS.slice(1, 5).forEach((id, index) => {
      timers.current.push(
        setTimeout(() => {
          setActiveNodeId(id);
          setSelectedNodeId(id);
        }, ANIMATION_NODE_DELAY_MS * (index + 1)),
      );
    });

    const settle = (callback: () => void) => {
      const remaining = Math.max(0, MIN_DISPATCH_DURATION_MS - (Date.now() - startedAt));
      timers.current.push(setTimeout(callback, remaining));
    };

    try {
      const result = await dispatchHeal(incident.id);
      settle(() => {
        if (result === null) {
          setPhase("demo");
          setActiveNodeId("open_pr");
          setSelectedNodeId("open_pr");
          return;
        }
        setReport(result);
        if (result.status === "pr_opened") {
          setPhase("pr_opened");
          setActiveNodeId(result.pr?.fallback ? "open_pr" : "merge_github");
          setSelectedNodeId(result.pr?.fallback ? "open_pr" : "merge_github");
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
  }, [clearTimers, dispatchHeal, incident, phase]);

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
      : phase === "running"
      ? "Dispatching..."
      : report || phase === "demo" || phase === "error"
        ? "Re-run dispatch"
        : "Dispatch fix";

  return (
    <div className="space-y-3" aria-label="Fix dispatch DAG">
      <div
        className={cn(
          "rounded-xl border bg-panel/70 p-3",
          isProminent ? "border-accent/25 bg-accent/[0.04] p-4" : "border-border",
        )}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              {isProminent ? (
                <span className="inline-flex size-8 items-center justify-center rounded-lg border border-accent/25 bg-accent-muted text-accent">
                  <Sparkles className="size-4" />
                </span>
              ) : null}
              <p className="text-sm font-semibold text-foreground">{projection.headline}</p>
              <ModeTag mode={projection.mode} />
              {autoDemo ? <LabelTag label="3s demo loop" /> : null}
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
              size="sm"
              onClick={() => setFullscreen(true)}
              disabled={!incident}
              aria-label="Expand DAG to fullscreen"
            >
              <Maximize2 className="size-3.5" />
              Expand
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={autoDemo ? replayDemo : dispatch}
              disabled={!incident || phase === "running"}
              aria-label={incident ? "Dispatch fix for selected run" : "Dispatch fix unavailable"}
            >
              {phase === "running" ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Sparkles className="size-3.5" />
              )}
              {buttonLabel}
            </Button>
          </div>
        </div>
      </div>

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

        {isProminent ? <ProofPanel evidence={evidence} /> : null}
      </div>

      {fullscreen ? (
        <FixDagFullscreen
          buttonLabel={buttonLabel}
          evidence={evidence}
          onClose={() => setFullscreen(false)}
          onDispatch={autoDemo ? replayDemo : dispatch}
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
  const items: DagTreeItem[] = NODE_SUBSTEPS[node.id].map((substep, index) => ({
    id: `${node.id}-sub-${index}`,
    label: substep.label,
    detail: substep.detail,
  }));

  if (node.id === "read_logs") {
    const traceItems = traceTreeToItems(buildTraceTree(run.events));
    if (traceItems.length && items[0]) {
      items[0] = { ...items[0], children: traceItems };
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

/**
 * The near-fullscreen "under the hood" view. Drops the filter/shortcut chrome
 * and expands every pipeline stage into a deeply nested branch tree — sub-steps,
 * real trace events, deployed infra, and the PR — while the Proof receipts live
 * in a drawer that pops open from the right.
 */
function FixDagFullscreen({
  buttonLabel,
  evidence,
  onClose,
  onDispatch,
  phase,
  projection,
  run,
  selectedNodeId,
  onSelectNode,
}: {
  buttonLabel: string;
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
            disabled={!run.incident || phase === "running"}
          >
            {phase === "running" ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Sparkles className="size-3.5" />
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
              <ProofPanel evidence={evidence} />
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
  node,
  children,
  collapsed,
  onToggle,
  selected,
  onSelect,
  last,
}: {
  node: FixDagNode;
  children: DagTreeItem[];
  collapsed: boolean;
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
          <div className="border-t border-border/60 px-3 py-3 pl-11">
            <DagTree items={children} />
          </div>
        ) : null}
      </div>
    </li>
  );
}

function ProofPanel({ evidence }: { evidence: FixDagEvidence }) {
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
                <ExternalLink className="ml-1 inline size-3" aria-hidden="true" />
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
    </aside>
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
        "absolute min-h-[88px] w-[132px] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-xl border bg-panel p-2.5 text-left shadow-sm outline-none transition-all hover:border-accent/30 focus-visible:ring-2 focus-visible:ring-ring",
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
            "inline-flex size-7 shrink-0 items-center justify-center rounded-lg border",
            nodeTone(node.status).icon,
          )}
        >
          <Icon className="size-3.5" aria-hidden="true" />
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
          <span className={cn("inline-flex size-8 items-center justify-center rounded-lg border", nodeTone(node.status).icon)}>
            <Icon className="size-4" aria-hidden="true" />
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
              <ExternalLink className="size-3.5" />
              Open PR in GitHub
            </a>
          </Button>
        ) : (
          <span className="inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-full border border-border bg-elevated px-3 text-xs text-muted-foreground">
            <CircleDot className="size-3" />
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
      {mode === "running" ? <Loader2 className="size-3 animate-spin" /> : null}
      {mode === "error" ? <AlertCircle className="size-3" /> : null}
      {mode === "live" ? <CheckCircle2 className="size-3" /> : null}
      {mode === "demo" ? <Network className="size-3" /> : null}
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
