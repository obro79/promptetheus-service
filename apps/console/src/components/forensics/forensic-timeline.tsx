"use client";

import * as React from "react";

import type { SessionModality, TraceEvent } from "@/lib/types";
import { cn, fmtDuration } from "@/lib/utils";
import { voiceMetadata } from "./model";

const BARS = [35, 62, 44, 79, 51, 88, 38, 66, 91, 57, 42, 73, 48, 82, 61, 32, 69, 53, 86, 46, 74, 39, 64, 84, 55, 36, 77, 49, 68, 43, 80, 59, 33, 71, 52, 89, 45, 65, 37, 76, 58, 83, 41, 70, 50, 87, 34, 63, 47, 78, 56, 40, 72, 54, 85, 31];

export function ForensicTimeline({
  events,
  durationMs,
  currentMs,
  selectedSeq,
  criticalSeq,
  evidence,
  modality,
  onSelect,
  onScrub,
}: {
  events: TraceEvent[];
  durationMs: number;
  currentMs: number;
  selectedSeq: number | null;
  criticalSeq: number | null;
  evidence: number[];
  modality: SessionModality;
  onSelect: (seq: number) => void;
  onScrub: (ms: number) => void;
}) {
  const span = Math.max(1, durationMs);
  const playhead = Math.max(0, Math.min(100, (currentMs / span) * 100));
  const evidenceSet = React.useMemo(() => new Set(evidence), [evidence]);
  const messages = events.filter((event) => event.type === "user_message" || event.type === "agent_message");
  const sentiment = messages.filter((event) => typeof voiceMetadata(event)?.sentiment === "number");

  const scrubFromPointer = (event: React.PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    onScrub(Math.max(0, Math.min(span, ((event.clientX - rect.left) / rect.width) * span)));
  };

  return (
    <section className="surface mx-3 mb-3 overflow-hidden rounded-2xl" aria-label="Synchronized forensic timeline">
      <div className="flex min-h-11 items-center justify-between border-b border-border/70 px-4"><p className="micro">Forensic timeline</p><p className="mono text-[11px] tabular-nums text-muted-foreground">{fmtDuration(currentMs)} / {fmtDuration(durationMs)}</p></div>
      <div className="grid grid-cols-[72px_minmax(0,1fr)] text-[10px]">
        {modality === "voice" ? <Track label="Audio"><div className="absolute inset-x-0 inset-y-1 flex items-center gap-px">{BARS.map((height, index) => <i key={index} className={cn("min-w-0 flex-1", (index / BARS.length) * 100 <= playhead ? "bg-accent/60" : "bg-border-strong")} style={{ height: `${height}%` }} />)}</div></Track> : null}
        <Track label="Transcript"><MarkerTrack events={messages} durationMs={span} selectedSeq={selectedSeq} criticalSeq={criticalSeq} evidence={evidenceSet} onSelect={onSelect} shape="wide" /></Track>
        <Track label="Trace"><MarkerTrack events={events} durationMs={span} selectedSeq={selectedSeq} criticalSeq={criticalSeq} evidence={evidenceSet} onSelect={onSelect} /></Track>
        <Track label="Sentiment"><div className="absolute inset-x-0 top-1/2 h-px bg-border" />{sentiment.length ? sentiment.map((event) => { const score = voiceMetadata(event)?.sentiment ?? 0; return <button key={event.seq} type="button" aria-label={`Sentiment ${score} at ${fmtDuration(event.t_offset_ms)}`} onClick={() => onSelect(event.seq)} className={cn("absolute size-2 -translate-x-1/2 rounded-full border border-canvas", score < -0.2 ? "bg-warning" : "bg-accent")} style={{ left: `${(event.t_offset_ms / span) * 100}%`, top: `${50 - score * 28}%` }} />; }) : <span className="absolute inset-0 flex items-center text-[10px] text-muted-foreground/60">No sentiment signal</span>}</Track>
        <Track label="Failure"><div className="absolute inset-x-0 top-1/2 h-px bg-border" />{criticalSeq !== null ? events.filter((event) => event.seq === criticalSeq).map((event) => <button key={event.seq} type="button" onClick={() => onSelect(event.seq)} aria-label={`Critical failure at ${fmtDuration(event.t_offset_ms)}`} className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45 border border-warning bg-warning/20" style={{ left: `${(event.t_offset_ms / span) * 100}%` }} />) : null}</Track>
      </div>
      <div className="grid grid-cols-[72px_minmax(0,1fr)] border-t border-border"><span className="border-r border-border px-2 py-2 text-[9px] uppercase tracking-wider text-muted-foreground">Scrub</span><div className="relative h-8 cursor-crosshair" onPointerDown={scrubFromPointer}><div className="absolute inset-x-0 top-1/2 h-px bg-border" /><span className="pointer-events-none absolute inset-y-0 z-20 w-px bg-foreground" style={{ left: `${playhead}%` }}><i className="absolute left-1/2 top-1 size-1.5 -translate-x-1/2 rotate-45 bg-foreground" /></span><span className="mono absolute bottom-1 left-1 text-[9px] text-muted-foreground">00:00</span><span className="mono absolute bottom-1 right-1 text-[9px] text-muted-foreground">{fmtDuration(durationMs)}</span></div></div>
    </section>
  );
}

function Track({ label, children }: { label: string; children: React.ReactNode }) {
  return <><div className="flex h-7 items-center border-b border-r border-border/70 px-2 text-[10px] font-medium text-muted-foreground">{label}</div><div className="relative h-7 overflow-hidden border-b border-border/70 px-2">{children}</div></>;
}

function MarkerTrack({ events, durationMs, selectedSeq, criticalSeq, evidence, onSelect, shape = "dot" }: { events: TraceEvent[]; durationMs: number; selectedSeq: number | null; criticalSeq: number | null; evidence: Set<number>; onSelect: (seq: number) => void; shape?: "dot" | "wide" }) {
  return <><div className="absolute inset-x-0 top-1/2 h-px bg-border" />{events.map((event) => { const critical = event.seq === criticalSeq; const selected = event.seq === selectedSeq; return <button key={event.seq} type="button" onClick={() => onSelect(event.seq)} aria-label={`Select ${event.type} ${event.seq}`} className={cn("absolute top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-sm border border-canvas transition-transform hover:scale-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", shape === "wide" ? "h-2 w-4" : "size-2", critical ? "bg-warning" : evidence.has(event.seq) ? "bg-accent" : "bg-muted-foreground", selected && "scale-150 ring-1 ring-foreground")} style={{ left: `${Math.max(0, Math.min(100, (event.t_offset_ms / durationMs) * 100))}%` }} />; })}</>;
}
