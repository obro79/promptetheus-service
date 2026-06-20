"use client";

import * as React from "react";
import {
  Bot,
  Check,
  FileCode2,
  Loader2,
  Sparkles,
  TestTube2,
  Wand2,
  Wrench,
} from "lucide-react";

import type { FixAgentResult } from "@/lib/types";
import { cn, pct } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { DiffViewer } from "@/components/common/diff-viewer";

export interface FixBundleCardProps {
  /** existing fix bundle, or null if not yet generated. */
  fix: FixAgentResult | null;
  className?: string;
}

const RUNNER_LABEL: Record<FixAgentResult["runner"], string> = {
  deterministic: "deterministic",
  claude: "Claude",
  codex: "Codex",
};

export function FixBundleCard({ fix, className }: FixBundleCardProps) {
  const [generated, setGenerated] = React.useState<FixAgentResult | null>(fix);
  const [phase, setPhase] = React.useState<"idle" | "running">("idle");

  const handleGenerate = React.useCallback(() => {
    if (!fix) return; // mock: re-use the bundled result as the "generated" payload
    setPhase("running");
    const t = setTimeout(() => {
      setGenerated(fix);
      setPhase("idle");
    }, 1400);
    return () => clearTimeout(t);
  }, [fix]);

  // No bundle available at all — nothing to generate from in mock mode.
  if (!generated && !fix) {
    return (
      <div
        className={cn(
          "rounded-lg border border-dashed border-border bg-panel/40 px-4 py-6 text-center",
          className,
        )}
      >
        <Wrench className="mx-auto mb-2 size-5 text-muted-foreground" />
        <p className="text-xs text-muted-foreground">
          No fix bundle generated yet for this incident.
        </p>
      </div>
    );
  }

  // Bundle exists but not "generated" in this session — show the Fix CTA.
  if (!generated) {
    return (
      <div
        className={cn(
          "flex flex-col items-center gap-3 rounded-lg border border-accent/30 bg-gradient-to-b from-accent-muted/20 to-transparent px-4 py-6 text-center",
          className,
        )}
      >
        <div className="flex size-10 items-center justify-center rounded-lg border border-accent/30 bg-accent-muted/30 text-accent">
          <Wand2 className="size-5" />
        </div>
        <div className="flex flex-col gap-1">
          <p className="text-sm font-semibold text-foreground">
            Ready to generate a fix
          </p>
          <p className="text-balance text-xs leading-relaxed text-muted-foreground">
            Replay the failing step into a coding agent and package a diff,
            regression test, and PR.
          </p>
        </div>
        <Button
          type="button"
          onClick={handleGenerate}
          disabled={phase === "running"}
          className="w-full"
        >
          {phase === "running" ? (
            <>
              <Loader2 className="animate-spin" />
              Generating fix…
            </>
          ) : (
            <>
              <Wand2 />
              Generate fix
            </>
          )}
        </Button>
      </div>
    );
  }

  const f = generated;

  return (
    <div
      className={cn(
        "animate-in fade-in slide-in-from-bottom-1 overflow-hidden rounded-lg border border-accent/30 bg-panel duration-300",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-border bg-accent-muted/15 px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-accent" />
          <span className="text-sm font-semibold text-foreground">
            Fix bundle
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="mono inline-flex items-center gap-1 rounded border border-accent/30 bg-accent-muted/30 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-accent">
            <Bot className="size-3" />
            {RUNNER_LABEL[f.runner]}
          </span>
          {f.fallback ? (
            <span className="mono rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-warning">
              fallback
            </span>
          ) : null}
          <span className="mono rounded border border-border bg-elevated px-1.5 py-0.5 text-[10px] tabular-nums text-muted-foreground">
            {pct(f.confidence)}
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-4 px-4 py-3.5">
        {f.summary ? (
          <p className="text-xs leading-relaxed text-foreground/90">
            {f.summary}
          </p>
        ) : null}

        {f.plan.length ? (
          <div className="flex flex-col gap-2">
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Plan
            </span>
            <ol className="flex flex-col gap-1.5">
              {f.plan.map((step, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="mono mt-px flex size-4 shrink-0 items-center justify-center rounded-full border border-accent/30 bg-accent-muted/30 text-[10px] tabular-nums text-accent">
                    {i + 1}
                  </span>
                  <span className="text-xs leading-relaxed text-foreground/90">
                    {step}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ) : null}

        {f.changed_files.length ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Changed files
              <span className="mono ml-1.5 tabular-nums text-muted-foreground/60">
                {f.changed_files.length}
              </span>
            </span>
            <ul className="flex flex-col gap-1">
              {f.changed_files.map((file) => (
                <li
                  key={file}
                  className="flex items-center gap-1.5 rounded border border-border bg-canvas px-2 py-1"
                >
                  <FileCode2 className="size-3 shrink-0 text-accent" />
                  <span className="mono truncate text-[11px] text-muted-foreground">
                    {file}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {f.regression_test ? (
          <div className="flex items-start gap-2 rounded-md border border-success/25 bg-success/5 px-2.5 py-2">
            <TestTube2 className="mt-px size-3.5 shrink-0 text-success" />
            <div className="flex flex-col gap-0.5">
              <span className="text-[11px] font-medium uppercase tracking-wide text-success">
                Regression test added
              </span>
              <span className="mono text-[11px] leading-relaxed text-foreground/90">
                {f.regression_test}
              </span>
            </div>
          </div>
        ) : null}

        {f.diff ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Proposed diff
            </span>
            <DiffViewer diff={f.diff} className="max-h-72" />
          </div>
        ) : null}

        <div className="flex items-center gap-1.5 text-[11px] text-success">
          <Check className="size-3.5" />
          <span>Fix bundle ready to open as a pull request</span>
        </div>
      </div>
    </div>
  );
}
