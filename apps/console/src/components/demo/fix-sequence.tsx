"use client";

import * as React from "react";
import {
  ArrowUpRight,
  CheckCircle2,
  FileCode2,
  GitPullRequest,
  Loader2,
  TestTube2,
} from "lucide-react";

import type { IncidentContext } from "@/lib/types";
import { cn, pct } from "@/lib/utils";
import { DiffViewer } from "@/components/common/diff-viewer";

export interface FixSequenceProps {
  context: IncidentContext;
  className?: string;
}

type Stage = "bundle" | "pr" | "regression";
const STAGE_ORDER: Stage[] = ["bundle", "pr", "regression"];

/** Reveal each stage on a timer once mounted (mount = Fix pressed). */
function useStagedReveal() {
  const [stage, setStage] = React.useState(0);
  React.useEffect(() => {
    const timers = [
      setTimeout(() => setStage(1), 900),
      setTimeout(() => setStage(2), 2200),
      setTimeout(() => setStage(3), 3600),
    ];
    return () => timers.forEach(clearTimeout);
  }, []);
  return stage; // 0 = packaging, 1 = bundle, 2 = +pr, 3 = +regression
}

function StageHeader({
  index,
  active,
  done,
  Icon,
  title,
  pending,
}: {
  index: number;
  active: boolean;
  done: boolean;
  Icon: React.ComponentType<{ className?: string }>;
  title: string;
  pending: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={cn(
          "inline-flex size-6 shrink-0 items-center justify-center rounded-md border text-[10px] font-semibold transition-colors duration-300",
          done
            ? "border-success/30 bg-success/10 text-success"
            : active
              ? "border-accent/40 bg-accent-muted/30 text-accent"
              : "border-border bg-elevated text-muted-foreground/50",
        )}
      >
        {done ? <CheckCircle2 className="size-3.5" /> : index}
      </span>
      <Icon
        className={cn(
          "size-3.5",
          done || active ? "text-foreground" : "text-muted-foreground/50",
        )}
      />
      <span
        className={cn(
          "text-xs font-medium",
          done || active ? "text-foreground" : "text-muted-foreground/50",
        )}
      >
        {title}
      </span>
      {active && !done ? (
        <span className="mono ml-auto inline-flex items-center gap-1 text-[10px] text-accent">
          <Loader2 className="size-3 animate-spin" />
          {pending}
        </span>
      ) : null}
    </div>
  );
}

export function FixSequence({ context, className }: FixSequenceProps) {
  const stage = useStagedReveal();
  const fix = context.incident.fix_agent_result;
  const reg = context.regression_runs[0];
  const prUrl = context.incident.pr_url;

  const idx = (s: Stage) => STAGE_ORDER.indexOf(s) + 1;

  return (
    <div className={cn("animate-slide-in space-y-3", className)}>
      <div className="flex items-center gap-2 px-0.5">
        <span className="mono text-[11px] uppercase tracking-widest text-accent">
          Fix pipeline
        </span>
        <div className="h-px flex-1 bg-border" />
        <span className="mono text-[10px] text-muted-foreground">
          runner: {fix?.runner ?? "claude"}
        </span>
      </div>

      {/* Stage 1 — fix bundle */}
      <div className="surface rounded-2xl p-3">
        <StageHeader
          index={idx("bundle")}
          active={stage >= 1}
          done={stage >= 2}
          Icon={FileCode2}
          title="Fix bundle packaged"
          pending="generating"
        />
        {stage >= 1 && fix ? (
          <div className="mt-3 animate-fade-in space-y-3">
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              {fix.summary}
            </p>
            <ol className="space-y-1">
              {fix.plan.map((step, i) => (
                <li
                  key={i}
                  className="flex gap-2 text-[11px] leading-snug text-muted-foreground"
                >
                  <span className="mono shrink-0 text-accent">{i + 1}.</span>
                  <span>{step}</span>
                </li>
              ))}
            </ol>
            <div className="flex flex-wrap gap-1.5">
              {fix.changed_files.map((f) => (
                <span
                  key={f}
                  className="mono inline-flex items-center gap-1 rounded border border-border bg-elevated px-1.5 py-0.5 text-[10px] leading-none text-muted-foreground"
                >
                  <FileCode2 className="size-3 text-accent" />
                  {f}
                </span>
              ))}
            </div>
            {fix.diff ? (
              <DiffViewer diff={fix.diff} className="max-h-56" />
            ) : null}
            {fix.regression_test ? (
              <div className="overflow-hidden rounded-md border border-border bg-canvas">
                <div className="flex items-center gap-1.5 border-b border-border bg-panel/60 px-3 py-1.5">
                  <TestTube2 className="size-3 text-success" />
                  <span className="mono text-[10px] uppercase tracking-wide text-muted-foreground">
                    regression test
                  </span>
                </div>
                <pre className="overflow-x-auto px-3 py-2 text-[11px] leading-relaxed">
                  <code className="mono text-foreground/90">
                    {fix.regression_test}
                  </code>
                </pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* Stage 2 — PR card */}
      <div className="surface rounded-2xl p-3">
        <StageHeader
          index={idx("pr")}
          active={stage >= 2}
          done={stage >= 3}
          Icon={GitPullRequest}
          title="Pull request opened"
          pending="opening PR"
        />
        {stage >= 2 && prUrl ? (
          <a
            href={prUrl}
            className="group mt-3 flex animate-fade-in items-center gap-3 rounded-md border border-border bg-canvas px-3 py-2.5 transition-colors duration-150 hover:border-accent/40"
          >
            <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-success/25 bg-success/10 text-success">
              <GitPullRequest className="size-4" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-foreground">
                {context.incident.title}
              </p>
              <p className="mono mt-0.5 truncate text-[10px] text-muted-foreground">
                {prUrl.replace("https://github.com/", "")}
              </p>
            </div>
            <span className="mono inline-flex shrink-0 items-center gap-0.5 rounded border border-success/25 bg-success/10 px-1.5 py-0.5 text-[10px] leading-none text-success">
              open
            </span>
            <ArrowUpRight className="size-3.5 shrink-0 text-muted-foreground transition-colors duration-150 group-hover:text-accent" />
          </a>
        ) : null}
      </div>

      {/* Stage 3 — regression replay */}
      <div className="surface rounded-2xl p-3">
        <StageHeader
          index={idx("regression")}
          active={stage >= 3}
          done={stage >= 3 && reg?.status === "complete"}
          Icon={TestTube2}
          title="Regression replay"
          pending="replaying"
        />
        {stage >= 3 && reg ? (
          <div className="mt-3 grid animate-fade-in grid-cols-2 gap-2.5">
            <RegressionCard
              label="Before fix"
              pass={reg.before_pass}
              total={reg.before_total}
              tone="destructive"
            />
            <RegressionCard
              label="After fix"
              pass={reg.after_pass}
              total={reg.after_total}
              tone="success"
            />
            <p className="col-span-2 text-[11px] leading-snug text-muted-foreground">
              <span className="mono text-success">
                {reg.after_pass}/{reg.after_total}
              </span>{" "}
              booking runs now pass goal verification.{" "}
              {reg.after_total - reg.after_pass > 0 ? (
                <>
                  <span className="mono text-warning">
                    {reg.after_total - reg.after_pass}
                  </span>{" "}
                  pause for user confirmation on the ambiguous UI.
                </>
              ) : null}
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function RegressionCard({
  label,
  pass,
  total,
  tone,
}: {
  label: string;
  pass: number;
  total: number;
  tone: "destructive" | "success";
}) {
  const ratio = total > 0 ? pass / total : 0;
  const toneClasses =
    tone === "success"
      ? { text: "text-success", bar: "bg-success", border: "border-success/25" }
      : {
          text: "text-destructive",
          bar: "bg-destructive",
          border: "border-destructive/25",
        };
  return (
    <div className={cn("rounded-md border bg-canvas p-2.5", toneClasses.border)}>
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] text-muted-foreground">{label}</span>
        <span className={cn("mono text-sm font-semibold tabular-nums", toneClasses.text)}>
          {pass}/{total}
        </span>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all duration-700", toneClasses.bar)}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
      <p className="mono mt-1 text-[10px] text-muted-foreground/70">
        {pct(ratio)} pass rate
      </p>
    </div>
  );
}
