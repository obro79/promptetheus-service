"use client";

import * as React from "react";
import { CheckCircle2, Loader2, Play, ShieldCheck, XCircle } from "lucide-react";

import type { RegressionRun } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export interface RegressionResultProps {
  /** latest regression run for the incident, or undefined if never run. */
  run: RegressionRun | undefined;
  className?: string;
}

function PassBar({
  label,
  pass,
  total,
  tone,
}: {
  label: string;
  pass: number;
  total: number;
  tone: "before" | "after";
}) {
  const ratio = total > 0 ? pass / total : 0;
  const allPass = total > 0 && pass === total;
  const barColor =
    tone === "before"
      ? "bg-destructive"
      : allPass
        ? "bg-success"
        : "bg-warning";
  const textColor =
    tone === "before"
      ? "text-destructive"
      : allPass
        ? "text-success"
        : "text-warning";

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        <span className={cn("mono text-xs font-medium tabular-nums", textColor)}>
          {pass}/{total} pass
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all duration-500", barColor)}
          style={{ width: `${Math.max(ratio * 100, total > 0 ? 4 : 0)}%` }}
        />
      </div>
    </div>
  );
}

export function RegressionResult({ run, className }: RegressionResultProps) {
  const [phase, setPhase] = React.useState<"idle" | "running">("idle");
  const [visibleRun, setVisibleRun] = React.useState<RegressionRun | undefined>(
    run,
  );

  const handleRun = React.useCallback(() => {
    setPhase("running");
    const t = setTimeout(() => {
      setVisibleRun(run);
      setPhase("idle");
    }, 1600);
    return () => clearTimeout(t);
  }, [run]);

  const r = visibleRun;
  const cleared = r ? r.after_pass - r.before_pass : 0;

  return (
    <div
      className={cn(
        "surface overflow-hidden rounded-2xl",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <ShieldCheck className="size-4 text-accent" />
          <span className="text-sm font-semibold text-foreground">
            Regression check
          </span>
        </div>
        {r?.fallback ? (
          <span className="mono rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-warning">
            fallback
          </span>
        ) : null}
      </div>

      <div className="flex flex-col gap-3.5 px-4 py-3.5">
        {r ? (
          <>
            <PassBar
              label="Before fix"
              pass={r.before_pass}
              total={r.before_total}
              tone="before"
            />
            <PassBar
              label="After fix"
              pass={r.after_pass}
              total={r.after_total}
              tone="after"
            />

            <div className="flex items-center gap-1.5 rounded-md border border-success/25 bg-success/5 px-2.5 py-2">
              {cleared > 0 ? (
                <>
                  <CheckCircle2 className="size-3.5 shrink-0 text-success" />
                  <span className="text-xs text-foreground/90">
                    Fix cleared{" "}
                    <span className="mono font-medium tabular-nums text-success">
                      {cleared}
                    </span>{" "}
                    failing{" "}
                    {cleared === 1 ? "test" : "tests"}
                    {r.after_pass < r.after_total ? (
                      <>
                        {" "}
                        ·{" "}
                        <span className="mono tabular-nums text-warning">
                          {r.after_total - r.after_pass}
                        </span>{" "}
                        still failing
                      </>
                    ) : (
                      " · suite green"
                    )}
                  </span>
                </>
              ) : (
                <>
                  <XCircle className="size-3.5 shrink-0 text-destructive" />
                  <span className="text-xs text-foreground/90">
                    No improvement detected yet.
                  </span>
                </>
              )}
            </div>
          </>
        ) : (
          <p className="text-xs leading-relaxed text-muted-foreground">
            Run the failing-session suite against the proposed fix to confirm it
            resolves the incident without regressions.
          </p>
        )}

        <Button
          type="button"
          variant={r ? "secondary" : "default"}
          size="sm"
          onClick={handleRun}
          disabled={phase === "running"}
          className="w-full"
        >
          {phase === "running" ? (
            <>
              <Loader2 className="animate-spin" />
              Running regression…
            </>
          ) : (
            <>
              <Play />
              {r ? "Re-run regression" : "Run regression"}
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
