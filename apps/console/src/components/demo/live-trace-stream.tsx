"use client";

import * as React from "react";
import { Radio, Zap } from "lucide-react";

import type { TraceEvent } from "@/lib/types";
import { cn, fmtDuration } from "@/lib/utils";

export interface LiveTraceStreamProps {
  events: TraceEvent[];
  /** highest seq played so far. -1 before start. */
  activeSeq: number;
  /** seqs flagged as evidence by analysis (highlight + flag). */
  evidenceSeqs: number[];
  /** the single critical step seq. */
  criticalSeq: number | null;
  /** true once analysis has run — enables evidence highlighting. */
  analyzed: boolean;
  playing: boolean;
  className?: string;
}

/** Map an event type to a source lane label, mirroring the demo plan. */
function sourceOf(type: string): { label: string; tone: string } {
  switch (type) {
    case "browser_action":
    case "dom_snapshot":
    case "screenshot":
      return { label: "browser", tone: "text-accent" };
    case "goal_check":
      return { label: "detector", tone: "text-warning" };
    case "llm_call":
    case "tool_call":
    case "tool_result":
      return { label: "sdk", tone: "text-muted-foreground" };
    default:
      return { label: "sdk", tone: "text-muted-foreground" };
  }
}

const TYPE_TONE: Record<string, string> = {
  user_message: "text-foreground",
  agent_message: "text-foreground",
  llm_call: "text-muted-foreground",
  tool_call: "text-accent",
  tool_result: "text-muted-foreground",
  browser_action: "text-accent",
  dom_snapshot: "text-accent",
  screenshot: "text-accent",
  goal_check: "text-destructive",
};

/** A compact one-line preview of an event payload. */
function preview(ev: TraceEvent): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>;
  switch (ev.type) {
    case "user_message":
    case "agent_message":
      return String(p.content ?? "");
    case "llm_call":
      return `${String(p.model ?? "model")} · ${String(p.prompt_ref ?? "")}`;
    case "tool_call":
      return `${String(p.tool_name ?? "")}(${JSON.stringify(p.arguments ?? {}).slice(0, 48)})`;
    case "tool_result": {
      const r = p.result as Record<string, unknown> | undefined;
      if (r && typeof r === "object")
        return `→ ${r.display ?? JSON.stringify(r).slice(0, 48)}`;
      return `→ ${JSON.stringify(p.result ?? p.error ?? "")}`.slice(0, 60);
    }
    case "browser_action":
      return `${String(p.action ?? "")} ${String(p.target ?? "")}`.trim();
    case "dom_snapshot":
      return String(p.visible_text ?? "");
    case "screenshot":
      return String(p.source ?? "");
    case "goal_check": {
      const ms = (p.mismatches as string[] | undefined) ?? [];
      return p.passed ? "passed" : `failed · ${ms[0] ?? ""}`;
    }
    default:
      return JSON.stringify(p).slice(0, 60);
  }
}

export function LiveTraceStream({
  events,
  activeSeq,
  evidenceSeqs,
  criticalSeq,
  analyzed,
  playing,
  className,
}: LiveTraceStreamProps) {
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const visible = events.filter((e) => e.seq <= activeSeq);

  React.useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [activeSeq]);

  return (
    <div
      className={cn(
        "surface flex h-full flex-col overflow-hidden rounded-2xl",
        className,
      )}
    >
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <Radio
            className={cn(
              "size-3.5",
              playing ? "animate-pulse text-success" : "text-muted-foreground",
            )}
          />
          <span className="text-xs font-medium text-foreground">
            Live trace stream
          </span>
        </div>
        <span className="mono text-[11px] tabular-nums text-muted-foreground">
          {visible.length}/{events.length} events
        </span>
      </div>

      {/* Stream */}
      <div ref={scrollRef} className="flex-1 overflow-auto">
        {visible.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-muted-foreground/50">
            Awaiting first event…
          </div>
        ) : (
          <ul className="divide-y divide-border/50">
            {visible.map((ev) => {
              const src = sourceOf(ev.type);
              const isEvidence = analyzed && evidenceSeqs.includes(ev.seq);
              const isCritical = analyzed && ev.seq === criticalSeq;
              return (
                <li
                  key={ev.seq}
                  className={cn(
                    "flex animate-slide-in items-start gap-2 px-3 py-1.5 transition-colors duration-150",
                    isCritical
                      ? "bg-destructive/10"
                      : isEvidence
                        ? "bg-warning/[0.06]"
                        : "hover:bg-elevated/40",
                  )}
                >
                  <span className="mono mt-0.5 w-6 shrink-0 text-right text-[10px] tabular-nums text-muted-foreground/50">
                    {ev.seq}
                  </span>
                  <span className="mono mt-0.5 w-12 shrink-0 text-[10px] tabular-nums text-muted-foreground/50">
                    +{fmtDuration(ev.t_offset_ms)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={cn(
                          "mono text-[11px] font-medium",
                          TYPE_TONE[ev.type] ?? "text-foreground",
                        )}
                      >
                        {ev.type}
                      </span>
                      <span
                        className={cn(
                          "mono text-[9px] uppercase tracking-wide opacity-70",
                          src.tone,
                        )}
                      >
                        {src.label}
                      </span>
                      {isCritical ? (
                        <span className="mono inline-flex items-center gap-0.5 rounded border border-destructive/30 bg-destructive/15 px-1 py-px text-[9px] leading-none text-destructive">
                          <Zap className="size-2.5" />
                          critical
                        </span>
                      ) : isEvidence ? (
                        <span className="mono rounded border border-warning/30 bg-warning/10 px-1 py-px text-[9px] leading-none text-warning">
                          evidence
                        </span>
                      ) : null}
                    </div>
                    <p className="mono mt-0.5 truncate text-[11px] text-muted-foreground">
                      {preview(ev)}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
