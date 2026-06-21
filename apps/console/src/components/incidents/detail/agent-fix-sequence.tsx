"use client";

import * as React from "react";
import {
  Bot,
  CheckCircle2,
  FileCode2,
  GitBranch,
  GitPullRequest,
  Loader2,
  Search,
  TestTube2,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import type { HealReport } from "@/lib/types";
import { cn } from "@/lib/utils";

export type CodingAgent = "claude-code" | "devin";

export const CODING_AGENTS: { id: CodingAgent; label: string }[] = [
  { id: "claude-code", label: "Claude Code" },
  { id: "devin", label: "Devin" },
];

const AGENT_LABEL: Record<CodingAgent, string> = {
  "claude-code": "Claude Code",
  devin: "Devin",
};

interface Step {
  Icon: LucideIcon;
  label: string;
  detail: string;
}

function buildSteps(report: HealReport, agent: CodingAgent): Step[] {
  const attempt = report.trail[0];
  const file = report.pr?.changed_files?.[0] ?? "agents/agent.py";
  const branch = report.pr?.branch ?? `promptetheus/${report.incident_id}-fix`;
  const beforeFail = attempt?.regression?.before_fail ?? 3;
  const prTitle = report.pr?.title ?? "Fix incident";

  return [
    { Icon: Bot, label: `Dispatched to ${AGENT_LABEL[agent]}`, detail: `incident ${report.incident_id}` },
    { Icon: GitBranch, label: "Checked out branch", detail: branch },
    { Icon: Search, label: "Read trace bundle", detail: "root cause + redacted evidence" },
    { Icon: Wrench, label: "Located root cause", detail: file },
    { Icon: FileCode2, label: `Edited ${file}`, detail: "+ post-action goal-verification guard" },
    { Icon: TestTube2, label: "Ran regression replay", detail: `${beforeFail} failing → 0 failing` },
    { Icon: GitPullRequest, label: "Opened pull request", detail: prTitle },
  ];
}

export interface AgentFixSequenceProps {
  report: HealReport;
  agent?: CodingAgent;
  onComplete?: () => void;
  className?: string;
}

/**
 * Streams a coding agent (Claude Code / Devin) being dispatched and working the
 * fix — checkout, read bundle, locate root cause, edit, run regression, open
 * the PR — one step at a time on a deterministic timer. Calls `onComplete` once
 * the last step lands, so the panel can reveal the verified report.
 */
export function AgentFixSequence({
  report,
  agent = "claude-code",
  onComplete,
  className,
}: AgentFixSequenceProps) {
  const steps = React.useMemo(() => buildSteps(report, agent), [report, agent]);
  const [current, setCurrent] = React.useState(0);
  const done = React.useRef(false);

  React.useEffect(() => {
    if (current >= steps.length) {
      if (!done.current) {
        done.current = true;
        onComplete?.();
      }
      return;
    }
    const delay = current === 0 ? 600 : 720;
    const timer = setTimeout(() => setCurrent((value) => value + 1), delay);
    return () => clearTimeout(timer);
  }, [current, steps.length, onComplete]);

  return (
    <div className={cn("rounded-xl border border-accent/25 bg-accent-muted/20 p-3", className)}>
      <div className="flex items-center gap-2">
        <span className="flex size-7 items-center justify-center rounded-md border border-accent/30 bg-accent-muted/50 text-accent">
          <Bot className="size-4" />
        </span>
        <div className="min-w-0">
          <p className="text-xs font-semibold text-foreground">
            {AGENT_LABEL[agent]} is fixing this incident
          </p>
          <p className="micro text-muted-foreground">agent dispatched · working in a sandbox branch</p>
        </div>
        <Loader2 className="ml-auto size-3.5 animate-spin text-accent" />
      </div>

      <ol className="mt-3 space-y-1.5">
        {steps.slice(0, current + 1).map((step, index) => {
          const isRunning = index === current;
          const Icon = step.Icon;
          return (
            <li
              key={step.label}
              className="flex items-center gap-2 rounded-md bg-canvas/60 px-2 py-1.5 text-[11px] animate-in fade-in slide-in-from-bottom-1 duration-300"
            >
              <span
                className={cn(
                  "flex size-5 shrink-0 items-center justify-center rounded",
                  isRunning ? "text-accent" : "text-success",
                )}
              >
                {isRunning ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="size-3.5" />
                )}
              </span>
              <Icon className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="font-medium text-foreground">{step.label}</span>
              <span className="mono ml-auto truncate pl-2 text-[10px] text-muted-foreground" title={step.detail}>
                {step.detail}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
