"use client";

import * as React from "react";
import {
  Brain,
  CheckCircle2,
  GitPullRequest,
  Loader2,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";

import { ConfidenceMeter } from "@/components/common/confidence-meter";
import { LabelTag } from "@/components/common/label-tag";
import { healIncident } from "@/lib/promptetheus-api";
import type { HealAttempt, HealReport, HealWarmStart } from "@/lib/types";
import { cn } from "@/lib/utils";

type Phase = "idle" | "running" | "done" | "error" | "disabled";

/**
 * The visible payoff: a "Self-heal" button that runs the bounded loop
 * (diagnose -> critique + regression -> PR) and renders the per-attempt trail,
 * the red->green regression flip, the agnostic source tag, and the final PR.
 *
 * Degrades to a disabled "Connect API" state when the API isn't configured, so
 * the static demo still renders.
 */
export function SelfHealPanel({ incidentId }: { incidentId: string }) {
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [report, setReport] = React.useState<HealReport | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const run = React.useCallback(async () => {
    setPhase("running");
    setError(null);
    try {
      const result = await healIncident(incidentId);
      if (result === null) {
        setPhase("disabled");
        return;
      }
      setReport(result);
      setPhase("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("error");
    }
  }, [incidentId]);

  return (
    <section className="surface mx-3 mb-3 overflow-hidden rounded-2xl" aria-label="Self-heal">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-accent" />
          <span className="text-sm font-semibold">Self-heal</span>
          <span className="micro text-muted-foreground">diagnose → verify → PR · human merges</span>
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
          {phase === "running" ? "Healing…" : report ? "Re-run self-heal" : "Self-heal incident"}
        </button>
      </div>

      <div className="p-4">
        {phase === "idle" ? (
          <p className="text-xs text-muted-foreground">
            Run the loop to generate a fix, verify it with a second Claude critique and a regression
            re-run, and open a pull request for a human to merge.
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

        {report ? <HealReportView report={report} /> : null}
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

      {report.warm_start ? <WarmStartBanner warm={report.warm_start} /> : null}

      <ol className="space-y-2">
        {report.trail.map((attempt) => (
          <AttemptRow key={attempt.attempt} attempt={attempt} />
        ))}
      </ol>

      {report.pr ? <PrCard pr={report.pr} /> : null}
    </div>
  );
}

/**
 * The data-flywheel "money shot": the Redis fix-memory matched a prior verified
 * fix and warm-started this heal from it. This is the one thing a read-only
 * observability tool structurally can't do — the agent reused what it learned.
 */
function WarmStartBanner({ warm }: { warm: HealWarmStart }) {
  const pct =
    typeof warm.score === "number" ? `${Math.round(warm.score * 100)}%` : null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-accent/40 bg-accent/10 px-3 py-2">
      <Brain className="size-4 shrink-0 text-accent" />
      <span className="text-xs font-semibold text-accent">Memory reuse</span>
      <span className="text-[11px] text-muted-foreground">
        warm-started from a prior verified fix
        {warm.label ? (
          <>
            {" "}— <span className="font-medium text-foreground">{warm.label}</span>
          </>
        ) : null}
        {warm.from_incident_id ? (
          <span className="mono ml-1 text-[10px] text-muted-foreground">
            ({warm.from_incident_id})
          </span>
        ) : null}
      </span>
      {pct ? (
        <span className="ml-auto inline-flex items-center gap-1 rounded-md bg-accent/15 px-2 py-0.5 text-[11px] font-semibold text-accent">
          {pct} match
        </span>
      ) : null}
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
