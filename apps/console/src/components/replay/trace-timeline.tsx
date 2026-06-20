"use client";

import * as React from "react";

import type { TraceEvent } from "@/lib/types";
import { cn, fmtDuration } from "@/lib/utils";

export interface TraceTimelineProps {
  events: TraceEvent[];
  /** total session duration in ms (drives marker positions). */
  durationMs: number;
  /** current playhead position in ms. */
  currentMs: number;
  /** currently selected event seq, if any. */
  selectedSeq: number | null;
  /** the analysis-flagged critical step seq. */
  criticalSeq: number | null;
  /** seqs flagged as evidence by the analysis. */
  evidenceSeqs?: number[];
  /** seq -> playback seconds, for sync from the artifact. */
  onSelect: (seq: number) => void;
  /** scrub the playhead to an absolute ms position. */
  onScrub: (ms: number) => void;
}

function eventTone(
  ev: TraceEvent,
  opts: { critical: boolean; evidence: boolean },
): { dot: string; ring: string } {
  if (opts.critical) {
    return { dot: "bg-accent", ring: "ring-accent" };
  }
  if (ev.type === "error") {
    return { dot: "bg-destructive", ring: "ring-destructive" };
  }
  if (ev.type === "goal_check") {
    const passed = (ev.payload as { passed?: boolean }).passed;
    return passed === false
      ? { dot: "bg-destructive", ring: "ring-destructive" }
      : { dot: "bg-success", ring: "ring-success" };
  }
  if (opts.evidence) {
    return { dot: "bg-warning", ring: "ring-warning" };
  }
  return { dot: "bg-muted-foreground", ring: "ring-muted-foreground" };
}

export function TraceTimeline({
  events,
  durationMs,
  currentMs,
  selectedSeq,
  criticalSeq,
  evidenceSeqs = [],
  onSelect,
  onScrub,
}: TraceTimelineProps) {
  const trackRef = React.useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = React.useState(false);
  const span = Math.max(1, durationMs);
  const evidence = React.useMemo(() => new Set(evidenceSeqs), [evidenceSeqs]);

  const playheadPct = Math.max(0, Math.min(1, currentMs / span)) * 100;

  const posFromClientX = React.useCallback(
    (clientX: number) => {
      const el = trackRef.current;
      if (!el) return 0;
      const rect = el.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      return ratio * span;
    },
    [span],
  );

  const handlePointerDown = React.useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.currentTarget.setPointerCapture(e.pointerId);
      setDragging(true);
      onScrub(posFromClientX(e.clientX));
    },
    [onScrub, posFromClientX],
  );

  const handlePointerMove = React.useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging) return;
      onScrub(posFromClientX(e.clientX));
    },
    [dragging, onScrub, posFromClientX],
  );

  const handlePointerUp = React.useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      setDragging(false);
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        /* no-op */
      }
    },
    [],
  );

  // axis ticks (start, 25/50/75%, end)
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div className="surface flex flex-col gap-2 rounded-2xl p-3">
      <div className="flex items-center justify-between">
        <span className="mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Trace timeline
        </span>
        <span className="mono text-[11px] tabular-nums text-muted-foreground">
          {fmtDuration(currentMs)}
          <span className="text-muted-foreground/50"> / {fmtDuration(durationMs)}</span>
        </span>
      </div>

      {/* scrub track */}
      <div className="relative pt-3">
        <div
          ref={trackRef}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          className="relative h-12 cursor-pointer touch-none select-none"
        >
          {/* baseline */}
          <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-border" />
          {/* elapsed fill */}
          <div
            className="absolute top-1/2 left-0 h-px -translate-y-1/2 bg-accent/60"
            style={{ width: `${playheadPct}%` }}
          />

          {/* event markers */}
          {events.map((ev) => {
            const isCritical = ev.seq === criticalSeq;
            const isSelected = ev.seq === selectedSeq;
            const tone = eventTone(ev, {
              critical: isCritical,
              evidence: evidence.has(ev.seq),
            });
            const left = Math.max(0, Math.min(1, ev.t_offset_ms / span)) * 100;
            return (
              <button
                key={ev.seq}
                type="button"
                title={`#${ev.seq} ${ev.type} · ${fmtDuration(ev.t_offset_ms)}`}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(ev.seq);
                }}
                className="group absolute top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 p-1.5 outline-none"
                style={{ left: `${left}%` }}
              >
                <span
                  className={cn(
                    "block rounded-full ring-2 ring-canvas transition-all duration-150 group-hover:scale-150",
                    tone.dot,
                    isCritical ? "size-3" : "size-2",
                    isSelected &&
                      cn("scale-150 ring-offset-1 ring-offset-canvas", tone.ring),
                  )}
                />
                {isCritical ? (
                  <span className="pointer-events-none absolute left-1/2 top-1/2 -z-10 size-5 -translate-x-1/2 -translate-y-1/2 animate-ping rounded-full bg-accent/40" />
                ) : null}
              </button>
            );
          })}

          {/* playhead */}
          <div
            className="pointer-events-none absolute top-0 bottom-0 z-20 w-px bg-foreground/80"
            style={{ left: `${playheadPct}%` }}
          >
            <span className="absolute -top-0.5 left-1/2 size-2 -translate-x-1/2 rotate-45 rounded-[2px] bg-foreground" />
          </div>
        </div>

        {/* axis labels */}
        <div className="relative mt-1 h-3">
          {ticks.map((t) => (
            <span
              key={t}
              className={cn(
                "mono absolute top-0 text-[10px] tabular-nums text-muted-foreground/60",
                t === 0 && "left-0",
                t === 1 && "right-0",
                t !== 0 && t !== 1 && "-translate-x-1/2",
              )}
              style={t !== 0 && t !== 1 ? { left: `${t * 100}%` } : undefined}
            >
              {fmtDuration(t * durationMs)}
            </span>
          ))}
        </div>
      </div>

      {/* legend */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border/60 pt-2">
        <LegendDot className="bg-accent" label="Critical step" />
        <LegendDot className="bg-destructive" label="Error / failed check" />
        <LegendDot className="bg-warning" label="Evidence" />
        <LegendDot className="bg-success" label="Passed check" />
        <LegendDot className="bg-muted-foreground" label="Event" />
      </div>
    </div>
  );
}

function LegendDot({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("size-1.5 rounded-full", className)} />
      <span className="text-[11px] text-muted-foreground">{label}</span>
    </span>
  );
}
