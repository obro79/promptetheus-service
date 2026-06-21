"use client";

import * as React from "react";
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  CircleDot,
  ExternalLink,
  FileCode2,
  GitMerge,
  GitPullRequest,
  Loader2,
  Network,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { LabelTag } from "@/components/common/label-tag";
import { Button } from "@/components/ui/button";
import { healIncident } from "@/lib/promptetheus-api";
import type {
  AgentPrDispatchResult,
  AgentPullRequestResult,
  EvalReport,
  HealReport,
} from "@/lib/types";
import { cn, pct } from "@/lib/utils";
import type { LogRun } from "./model";
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

interface FixDispatchDagProps {
  autoDemo?: boolean;
  dispatchHeal?: DispatchHeal;
  dispatchLabel?: string;
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
  read_logs: { x: 82, y: 108 },
  plan_fix: { x: 224, y: 108 },
  dispatch_fix: { x: 366, y: 108 },
  run_evals: { x: 508, y: 108 },
  open_pr: { x: 650, y: 108 },
  merge_github: { x: 792, y: 108 },
};

const CANVAS = { width: 880, height: 230 };
const NODE_WIDTH = 124;

const ANIMATION_NODE_DELAY_MS = 420;
const DEMO_NODE_DELAY_MS = 3000;
const MIN_DISPATCH_DURATION_MS = 2100;

export function FixDispatchDag({
  autoDemo = false,
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
    setAgentDispatch(null);
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
    setAgentDispatch(null);
    setError(null);
    return clearTimers;
  }, [clearTimers, incident?.id, run.session.id]);

  React.useEffect(() => {
    if (!autoDemo || !incident) return;
    replayDemo();
    return clearTimers;
  }, [autoDemo, clearTimers, incident, replayDemo, run.session.id]);

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
    setAgentDispatch(null);
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
      const result = await (dispatchHeal ?? defaultDispatchHeal)(incident.id, run);
      settle(() => {
        if (result === null) {
          setPhase("demo");
          setActiveNodeId("open_pr");
          setSelectedNodeId("open_pr");
          return;
        }
        const normalizedReport = isAgentPrDispatchResult(result)
          ? agentDispatchToHealReport(result, incident.id)
          : result;
        setAgentDispatch(isAgentPrDispatchResult(result) ? result : null);
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
      : phase === "running"
      ? "Dispatching..."
      : report || phase === "demo" || phase === "error"
        ? "Re-run dispatch"
        : dispatchLabel;

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

      <div className={cn(isProminent && "grid gap-3 xl:grid-cols-[minmax(0,1fr)_340px]")}>
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
    </div>
  );
}

async function defaultDispatchHeal(incidentId: string): Promise<HealReport | null> {
  return healIncident(incidentId);
}

function isAgentPrDispatchResult(
  result: HealReport | AgentPrDispatchResult,
): result is AgentPrDispatchResult {
  return "pullRequests" in result;
}

function agentDispatchToHealReport(
  result: AgentPrDispatchResult,
  incidentId: string,
): HealReport {
  const primary = result.pullRequests.find((pullRequest) => pullRequest.url);
  const opened = result.pullRequests.filter((pullRequest) => pullRequest.url);
  return {
    attempts: result.pullRequests.length,
    incident_id: incidentId,
    orchestrator: "maintainerOS",
    pr: primary
      ? {
          branch: primary.branch ?? undefined,
          changed_files: result.pullRequests
            .filter((pullRequest) => pullRequest.url)
            .map((pullRequest) => `${pullRequest.agentType} agent`),
          fallback: false,
          pr_url: primary.url,
          title: primary.title,
        }
      : null,
    reason: opened.length ? null : "No demo agent pull requests opened.",
    source: `logs_agent_dispatch:${result.targetRepo}`,
    status: opened.length ? "pr_opened" : "escalated",
    trail: [
      {
        attempt: 1,
        critique: {
          approved: opened.length === result.pullRequests.length,
          confidence: opened.length / Math.max(1, result.pullRequests.length),
          reason:
            opened.length === result.pullRequests.length
              ? "Browser, chat, and voice agent PRs opened."
              : `${opened.length} of ${result.pullRequests.length} agent PRs opened.`,
        },
        diagnosis: `Dispatch selected logs into ${result.targetRepo} agent PRs.`,
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
    workflow_run_id: null,
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

      {agentDispatch ? <AgentPullRequestList result={agentDispatch} /> : null}
    </aside>
  );
}

function AgentPullRequestList({ result }: { result: AgentPrDispatchResult }) {
  return (
    <div className="border-t border-border/70 bg-panel p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground">
          Agent PRs
        </p>
        <span className="mono text-[10px] text-muted-foreground">{result.targetRepo}</span>
      </div>
      <ul className="mt-2 space-y-2">
        {result.pullRequests.map((pullRequest) => (
          <AgentPullRequestItem key={pullRequest.agentType} pullRequest={pullRequest} />
        ))}
      </ul>
    </div>
  );
}

function AgentPullRequestItem({
  pullRequest,
}: {
  pullRequest: AgentPullRequestResult;
}) {
  const label = `${pullRequest.agentType[0].toUpperCase()}${pullRequest.agentType.slice(1)} agent`;
  return (
    <li className="rounded-lg border border-border/70 bg-elevated/35 p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold text-foreground">{label}</p>
          {pullRequest.url ? (
            <a
              href={pullRequest.url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-flex max-w-full items-center gap-1 truncate text-xs font-medium text-success underline-offset-4 hover:underline"
            >
              <span className="truncate">PR #{pullRequest.number}: {pullRequest.title}</span>
              <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
            </a>
          ) : (
            <p className="mt-1 text-xs text-destructive">{pullRequest.error ?? "PR failed."}</p>
          )}
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase",
            pullRequest.devinReviewRequested
              ? "border-success/25 bg-success/10 text-success"
              : pullRequest.url
                ? "border-warning/25 bg-warning/10 text-warning"
                : "border-destructive/25 bg-destructive/10 text-destructive",
          )}
        >
          {pullRequest.devinReviewRequested
            ? "Devin requested"
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
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "absolute min-h-[84px] w-[124px] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-xl border bg-panel p-2.5 text-left shadow-sm outline-none transition-all hover:border-accent/30 focus-visible:ring-2 focus-visible:ring-ring",
        nodeTone(node.status).border,
        selected && "ring-2 ring-accent/25",
        current && node.status === "active" && "shadow-glow",
      )}
      style={{ left: position.x, top: position.y }}
    >
      {current && node.status === "active" ? (
        <span className="absolute inset-x-0 top-0 h-0.5 animate-pulse bg-accent" />
      ) : null}
      <span className="flex min-w-0 items-center gap-2">
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
      <span className="mt-2 block truncate text-[10px] leading-4 text-muted-foreground">
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
