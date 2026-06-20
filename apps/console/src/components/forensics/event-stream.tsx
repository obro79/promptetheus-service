"use client";

import * as React from "react";
import { Filter, Search } from "lucide-react";

import { eventMeta } from "@/components/replay/event-list";
import type { TraceEvent } from "@/lib/types";
import { cn, fmtDuration } from "@/lib/utils";
import { eventSummary } from "./model";

const ROW_HEIGHT = 52;
const OVERSCAN = 6;

export function EventStream({
  events,
  selectedSeq,
  criticalSeq,
  evidence,
  onSelect,
}: {
  events: TraceEvent[];
  selectedSeq: number | null;
  criticalSeq: number | null;
  evidence: number[];
  onSelect: (seq: number) => void;
}) {
  const [query, setQuery] = React.useState("");
  const [failuresOnly, setFailuresOnly] = React.useState(false);
  const [scrollTop, setScrollTop] = React.useState(0);
  const viewportRef = React.useRef<HTMLDivElement>(null);
  const evidenceSet = React.useMemo(() => new Set(evidence), [evidence]);

  const filtered = React.useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return events.filter((event) => {
      const failureRelated = event.seq === criticalSeq || evidenceSet.has(event.seq) || event.type === "error" || (event.type === "goal_check" && (event.payload as { passed?: boolean }).passed === false);
      if (failuresOnly && !failureRelated) return false;
      if (!normalized) return true;
      return `${event.type} ${eventSummary(event)} ${JSON.stringify(event.payload)}`.toLowerCase().includes(normalized);
    });
  }, [events, evidenceSet, failuresOnly, criticalSeq, query]);

  React.useEffect(() => {
    if (selectedSeq === null) return;
    const index = filtered.findIndex((event) => event.seq === selectedSeq);
    const viewport = viewportRef.current;
    if (index < 0 || !viewport) return;
    const top = index * ROW_HEIGHT;
    if (top < viewport.scrollTop || top + ROW_HEIGHT > viewport.scrollTop + viewport.clientHeight) {
      const target = Math.max(0, top - viewport.clientHeight / 2);
      if (typeof viewport.scrollTo === "function") viewport.scrollTo({ top: target, behavior: "smooth" });
      else viewport.scrollTop = target;
    }
  }, [selectedSeq, filtered]);

  const viewportHeight = viewportRef.current?.clientHeight ?? 520;
  const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const end = Math.min(filtered.length, Math.ceil((scrollTop + viewportHeight) / ROW_HEIGHT) + OVERSCAN);
  const visible = filtered.slice(start, end);

  return (
    <section className="instrument-panel flex h-full flex-col overflow-hidden" aria-label="Trace event stream">
      <div className="instrument-header">
        <div><p className="micro">Trace / event stream</p><p className="mono mt-1 text-[10px] text-muted-foreground">{filtered.length} of {events.length} events</p></div>
        <button
          type="button"
          aria-pressed={failuresOnly}
          onClick={() => setFailuresOnly((value) => !value)}
          className={cn("flex size-9 items-center justify-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", failuresOnly ? "bg-accent/[0.12] text-accent" : "text-muted-foreground hover:bg-elevated hover:text-foreground")}
          aria-label="Show failure-related events only"
        ><Filter className="size-3.5" /></button>
      </div>
      <label className="relative border-b border-border p-2">
        <span className="sr-only">Filter events</span>
        <Search className="absolute left-5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter events, tools, payloads…" className="h-10 w-full rounded-md border border-transparent bg-elevated pl-9 pr-3 text-xs text-foreground outline-none placeholder:text-muted-foreground/60 hover:bg-muted focus:border-accent/50 focus:ring-2 focus:ring-ring/30" />
      </label>
      <div className="grid grid-cols-[64px_minmax(120px,0.7fr)_minmax(0,1fr)] border-b border-border/70 px-3 py-2 text-[11px] font-medium text-muted-foreground">
        <span>Time</span><span>Event</span><span>Details</span>
      </div>
      <div ref={viewportRef} onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)} className="min-h-0 flex-1 overflow-auto overscroll-contain" style={{ contain: "strict" }}>
        <div className="relative" style={{ height: filtered.length * ROW_HEIGHT }}>
          {visible.map((event, visibleIndex) => {
            const Icon = eventMeta.EVENT_ICON[event.type];
            const selected = event.seq === selectedSeq;
            const critical = event.seq === criticalSeq;
            const isEvidence = evidenceSet.has(event.seq);
            const failed = event.type === "error" || (event.type === "goal_check" && (event.payload as { passed?: boolean }).passed === false);
            return (
              <button
                key={event.seq}
                type="button"
                onClick={() => onSelect(event.seq)}
                className={cn("absolute left-0 grid w-full grid-cols-[64px_minmax(120px,0.7fr)_minmax(0,1fr)] items-center border-b border-border/60 px-3 text-left text-xs transition-colors focus-visible:z-20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring", selected ? "border-l-2 border-l-accent bg-accent/10" : "border-l-2 border-l-transparent hover:bg-elevated/70", critical && !selected && "border-l-warning bg-warning/5")}
                style={{ height: ROW_HEIGHT, transform: `translateY(${(start + visibleIndex) * ROW_HEIGHT}px)` }}
                aria-current={selected ? "true" : undefined}
              >
                <span className="mono tabular-nums text-muted-foreground">{fmtDuration(event.t_offset_ms)}</span>
                <span className="flex min-w-0 items-center gap-2 pr-2"><Icon className={cn("size-3.5 shrink-0", critical ? "text-accent" : failed ? "text-warning" : "text-muted-foreground")} /><span className="mono truncate text-foreground">{event.type}</span></span>
                <span className="flex min-w-0 items-center gap-2"><span className="truncate text-muted-foreground">{eventSummary(event)}</span>{critical ? <Mark label="critical" tone="bg-accent/10 text-accent" /> : isEvidence ? <Mark label="evidence" tone="bg-warning/10 text-warning" /> : null}</span>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function Mark({ label, tone }: { label: string; tone: string }) {
  return <span className={cn("ml-auto shrink-0 rounded-md px-1.5 py-1 text-[10px] font-medium", tone)}>{label}</span>;
}
