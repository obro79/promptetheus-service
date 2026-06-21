"use client";

import * as React from "react";
import {
  CheckCircle2,
  Gauge,
  GitPullRequest,
  Loader2,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";

import { ConfidenceMeter } from "@/components/common/confidence-meter";
import { LabelTag } from "@/components/common/label-tag";
import { healIncident } from "@/lib/promptetheus-api";
import { buildSampleHealReport } from "@/lib/sample-heal";
import type { HealAttempt, HealReport } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  AgentFixSequence,
  CODING_AGENTS,
  type CodingAgent,
} from "./agent-fix-sequence";

type Phase = "idle" | "running" | "done" | "error" | "disabled";

/**
 * The visible payoff: a "Self-heal" button that runs the bounded loop
 * (diagnose -> critique + regression -> PR) and renders the per-attempt trail,
 * the red->green regression flip, the agnostic source tag, and the final PR.
 *
 * Degrades to a disabled "Connect API" state when the API isn't configured, so
 * the static demo still renders.
 */
export function SelfHealPanel({
  incidentId,
  className,
}: {
  incidentId: string;
  className?: string;
}) {
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [report, setReport] = React.useState<HealReport | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [agent, setAgent] = React.useState<CodingAgent>("claude-code");

  const run = React.useCallback(async () => {
    setPhase("running");
    setError(null);
    setReport(null);
    try {
      // Resolve the report first (live API, or a representative one when the
      // API isn't connected), then stream the coding-agent fix sequence; the
      // sequence's onComplete flips to the verified report.
      const live = await healIncident(incidentId);
      setReport(live ?? buildSampleHealReport(incidentId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("error");
    }
  }, [incidentId]);

  const revealReport = React.useCallback(() => setPhase("done"), []);

  return (
    <section
      className={cn("surface overflow-hidden rounded-2xl", className ?? "mx-3 mb-3")}
      aria-label="Self-heal"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-accent" />
          <span className="text-sm font-semibold">Self-heal</span>
          <span className="micro text-muted-foreground">diagnose → verify → PR · human merges</span>
        </div>
        <div className="flex items-center gap-2">
          <div
            className="flex items-center rounded-md border border-border/70 bg-elevated p-0.5"
            role="group"
            aria-label="Coding agent"
          >
            {CODING_AGENTS.map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => setAgent(option.id)}
                disabled={phase === "running"}
                aria-pressed={agent === option.id}
                className={cn(
                  "rounded px-2 py-1 text-[11px] font-medium transition-colors disabled:opacity-60",
                  agent === option.id
                    ? "bg-accent-muted text-accent"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={run}
            disabled={phase === "running"}
            className="flex min-h-9 items-center gap-2 rounded-md bg-accent px-3 text-xs font-semibold text-accent-foreground transition-colors hover:bg-accent-bright focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
          >
            {phase === "running" ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <ShieldCheck className="size-3.5" />
            )}
            {phase === "running" ? "Dispatching…" : phase === "done" ? "Re-run self-heal" : "Self-heal incident"}
          </button>
        </div>
      </div>

      <div className="p-4">
        {phase === "idle" ? (
          <p className="text-xs text-muted-foreground">
            Run the loop to generate a fix, verify it with an LLM-as-judge eval (before → after), a
            second Claude critique, and a regression re-run, then open a pull request for a human to
            merge.
          </p>
        ) : null}

        {phase === "disabled" ? (
          <p className="text-xs text-warning">
            Connect the Promptetheus API (set <code className="mono">NEXT_PUBLIC_PROMPTETHEUS_API_URL</code>
            ) to run the self-healing loop.
          </p>
        ) : null}

        {phase === "error" ? (
          <p className="text-xs text-destructive">Heal failed: {error}</p>
        ) : null}

        {phase === "running" ? (
          report ? (
            <AgentFixSequence report={report} agent={agent} onComplete={revealReport} />
          ) : (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin text-accent" />
              Dispatching the fix to the coding agent…
            </p>
          )
        ) : null}

        {phase === "done" && report ? <HealReportView report={report} /> : null}
      </div>
    </section>
  );
}

function HealReportView({ report }: { report: HealReport }) {
  const opened = report.status === "pr_opened";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-semibold",
            opened ? "bg-success/15 text-success" : "bg-warning/15 text-warning",
          )}
        >
          {opened ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}
          {opened ? "PR opened — ready for human merge" : `Escalated · ${report.reason ?? "unverified"}`}
        </span>
        <LabelTag label={`source: ${report.source}`} />
        <LabelTag label={`${report.attempts} attempt${report.attempts === 1 ? "" : "s"}`} />
        <LabelTag label={`orchestrator: ${report.orchestrator}`} />
        {report.workflow_run_id ? (
          <LabelTag label={`workflow: ${report.workflow_run_id}`} />
        ) : null}
      </div>

      <ol className="space-y-2">
        {report.trail.map((attempt) => (
          <AttemptRow key={attempt.attempt} attempt={attempt} />
        ))}
      </ol>

      {report.pr ? <PrCard pr={report.pr} /> : null}
    </div>
  );
}

function AttemptRow({ attempt }: { attempt: HealAttempt }) {
  const critique = attempt.critique;
  const reg = attempt.regression;
  const beforeFail = reg?.before_fail ?? null;
  const afterFail = reg?.after_fail ?? null;
  return (
    <li className="rounded-lg border border-border/70 bg-elevated p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">
          Attempt {attempt.attempt}
          <span className="ml-2 mono text-[10px] text-accent">{attempt.runner ?? "runner"}</span>
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-1 text-[11px] font-semibold",
            attempt.passed ? "text-success" : "text-warning",
          )}
        >
          {attempt.passed ? <CheckCircle2 className="size-3" /> : <XCircle className="size-3" />}
          {attempt.passed ? "verified" : "rejected"}
        </span>
      </div>

      {attempt.diagnosis ? (
        <p className="mt-1.5 text-[11px] text-muted-foreground">{attempt.diagnosis}</p>
      ) : null}

      <EvalGate eval={attempt.eval} />

      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {critique ? (
          <div className="rounded-md bg-canvas p-2">
            <div className="micro text-muted-foreground">Claude critique gate</div>
            <div className="mt-1 flex items-center gap-2">
              <span className={cn("text-[11px] font-semibold", critique.approved ? "text-success" : "text-warning")}>
                {critique.approved ? "approved" : "rejected"}
              </span>
              <ConfidenceMeter value={critique.confidence} showLabel={false} className="w-16" />
            </div>
            <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">{critique.reason}</p>
          </div>
        ) : null}

        {reg ? (
          <div className="rounded-md bg-canvas p-2">
            <div className="micro text-muted-foreground">Regression replay</div>
            <div className="mt-1 flex items-center gap-2 text-[11px]">
              {beforeFail !== null ? (
                <span className="text-destructive">{beforeFail} failing</span>
              ) : null}
              <span className="text-muted-foreground">→</span>
              <span className={afterFail === 0 ? "text-success" : "text-warning"}>
                {afterFail ?? "?"} failing
              </span>
            </div>
          </div>
        ) : null}
      </div>
    </li>
  );
}

/**
 * The headline gate: the LLM-as-judge fix-quality eval. A fix only ships when
 * the agent's BEFORE output fails the violated assertion and the AFTER output
 * passes it — shown as a red→green before/after flip with the judge's
 * confidence. Renders nothing for older attempts without an eval, and tags the
 * deterministic fallback (no judge / no key) so the verdict is never misread.
 */
function EvalGate({ eval: report }: { eval: HealAttempt["eval"] }) {
  if (!report || !report.meaningful) return null;
  const head = report.cases[0];
  const beforePassed = head ? head.before_passed : report.before_fail === 0;
  const afterPassed = head ? head.after_passed : report.after_fail === 0;

  return (
    <div className="mt-2 rounded-lg border border-accent/30 bg-accent-muted/30 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <Gauge className="size-3.5 text-accent" />
          <span className="text-[11px] font-semibold text-foreground">Fix-quality eval</span>
          <span className="micro text-muted-foreground">LLM-as-judge · before → after</span>
        </div>
        {report.fallback ? <LabelTag label="deterministic" /> : null}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <EvalVerdict passed={beforePassed} label="before" />
        <span className="text-muted-foreground">→</span>
        <EvalVerdict passed={afterPassed} label="after" />
        {!report.fallback && head ? (
          <div className="ml-auto flex items-center gap-1.5">
            <span className="micro text-muted-foreground">judge</span>
            <ConfidenceMeter value={head.confidence} showLabel={false} className="w-16" />
          </div>
        ) : null}
      </div>

      {head?.reason ? (
        <p className="mt-1.5 text-[10px] leading-relaxed text-muted-foreground">{head.reason}</p>
      ) : null}
    </div>
  );
}

function EvalVerdict({ passed, label }: { passed: boolean; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-semibold",
        passed ? "bg-success/15 text-success" : "bg-destructive/15 text-destructive",
      )}
    >
      {passed ? <CheckCircle2 className="size-3" /> : <XCircle className="size-3" />}
      {label}: {passed ? "PASS" : "FAIL"}
    </span>
  );
}

function PrCard({ pr }: { pr: NonNullable<HealReport["pr"]> }) {
  return (
    <div className="rounded-lg border border-border/70 p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-semibold">
          <GitPullRequest className="size-3.5 text-accent" />
          {pr.title ?? "Pull request"}
        </div>
        {pr.fallback ? (
          <LabelTag label="preview (GitHub disabled)" />
        ) : pr.pr_url ? (
          <a
            href={pr.pr_url}
            target="_blank"
            rel="noreferrer"
            className="text-[11px] font-semibold text-accent hover:underline"
          >
            Open PR ↗
          </a>
        ) : null}
      </div>
      {pr.branch ? (
        <div className="mt-1 mono text-[10px] text-muted-foreground">{pr.branch}</div>
      ) : null}
      {pr.changed_files && pr.changed_files.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {pr.changed_files.map((file) => (
            <LabelTag key={file} label={file} />
          ))}
        </div>
      ) : null}
      {pr.body ? (
        <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-canvas p-2.5 text-[10px] leading-relaxed whitespace-pre-wrap text-muted-foreground">
          {pr.body}
        </pre>
      ) : null}
    </div>
  );
}
