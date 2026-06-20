import * as React from "react";
import { Camera, Code2, Crosshair } from "lucide-react";

import type { ReplayArtifact, TraceEvent } from "@/lib/types";
import { cn, fmtDuration } from "@/lib/utils";

export interface CriticalStepCardProps {
  /** the failing event at critical_step_seq, if found. */
  event: TraceEvent | undefined;
  criticalSeq: number | null;
  artifacts: ReplayArtifact[];
  className?: string;
}

/** Compact, human-readable summary line for a trace event payload. */
function summarize(event: TraceEvent): { headline: string; detail?: string } {
  const p = (event.payload ?? {}) as Record<string, unknown>;
  const str = (v: unknown) => (typeof v === "string" ? v : undefined);

  switch (event.type) {
    case "tool_call": {
      const args = (p.arguments ?? {}) as Record<string, unknown>;
      const argText = str(args.text) ?? str(args.selector);
      return {
        headline: `${str(p.tool_name) ?? "tool"}(…)`,
        detail: argText
          ? `${str(args.selector) ?? ""}${args.text ? `  →  "${str(args.text)}"` : ""}`.trim()
          : undefined,
      };
    }
    case "browser_action":
      return {
        headline: `${str(p.action) ?? "action"} ${str(p.target) ?? ""}`.trim(),
        detail: str(p.url),
      };
    case "dom_snapshot":
      return {
        headline: str(p.url) ?? "dom snapshot",
        detail: str(p.visible_text),
      };
    case "agent_message":
      return { headline: "agent message", detail: str(p.content) };
    case "user_message":
      return { headline: "user message", detail: str(p.content) };
    case "tool_result":
      return {
        headline: `result ${str(p.call_id) ?? ""}`.trim(),
        detail: str(p.error) ?? str(p.result) ?? JSON.stringify(p.result),
      };
    case "goal_check":
      return {
        headline: p.passed ? "goal check passed" : "goal check FAILED",
        detail: Array.isArray(p.mismatches)
          ? (p.mismatches as string[]).join("  •  ")
          : undefined,
      };
    case "screenshot":
      return { headline: "screenshot captured" };
    default:
      return { headline: event.type.replace(/_/g, " ") };
  }
}

/** Find the evidence artifact (screenshot/dom) closest to the critical seq. */
function evidenceFor(
  seq: number | null,
  artifacts: ReplayArtifact[],
): ReplayArtifact | undefined {
  if (seq === null) return undefined;
  // exact event_time_map hit first
  const exact = artifacts.find(
    (a) => a.kind !== "video" && String(seq) in a.event_time_map,
  );
  if (exact) return exact;
  return artifacts.find((a) => a.kind === "screenshot" || a.kind === "dom_snapshot");
}

export function CriticalStepCard({
  event,
  criticalSeq,
  artifacts,
  className,
}: CriticalStepCardProps) {
  if (!event) {
    return (
      <div
        className={cn(
          "rounded-lg border border-dashed border-border bg-panel/40 px-4 py-6 text-center",
          className,
        )}
      >
        <p className="text-xs text-muted-foreground">
          No critical step was isolated for this incident.
        </p>
      </div>
    );
  }

  const { headline, detail } = summarize(event);
  const evidence = evidenceFor(criticalSeq, artifacts);

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-lg border border-destructive/30 bg-panel",
        className,
      )}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 left-0 w-0.5 bg-destructive"
      />
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-gradient-to-r from-destructive/[0.06] to-transparent"
      />

      <div className="relative flex flex-col gap-3 px-4 py-3.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-md border border-destructive/30 bg-destructive/10 px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide text-destructive">
            <Crosshair className="size-3" />
            Critical step
          </span>
          <span className="mono rounded border border-border bg-elevated px-1.5 py-0.5 text-[11px] tabular-nums text-foreground">
            seq {event.seq}
          </span>
          <span className="mono rounded border border-accent/30 bg-accent-muted/30 px-1.5 py-0.5 text-[11px] text-accent">
            {event.type}
          </span>
          <span className="mono ml-auto text-[11px] tabular-nums text-muted-foreground">
            +{fmtDuration(event.t_offset_ms)}
          </span>
        </div>

        <div className="flex flex-col gap-1">
          <span className="mono text-sm font-medium text-foreground">
            {headline}
          </span>
          {detail ? (
            <p className="mono text-xs leading-relaxed text-muted-foreground">
              {detail}
            </p>
          ) : null}
        </div>

        {evidence ? (
          <div className="flex items-center gap-2 rounded-md border border-border bg-canvas px-2 py-1.5">
            {evidence.kind === "dom_snapshot" ? (
              <Code2 className="size-3.5 shrink-0 text-accent" />
            ) : (
              <Camera className="size-3.5 shrink-0 text-accent" />
            )}
            <span className="mono truncate text-[11px] text-muted-foreground">
              {evidence.storage_path.split("/").pop()}
            </span>
            <span className="mono ml-auto shrink-0 rounded bg-elevated px-1 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground/70">
              {evidence.kind.replace("_", " ")}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
