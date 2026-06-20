"use client";

import * as React from "react";
import Image from "next/image";
import {
  AlertTriangle,
  Bot,
  Code2,
  Globe2,
  Mic2,
  Pause,
  Play,
  RotateCcw,
  User,
} from "lucide-react";

import type { ReplayArtifact, SessionModality, TraceEvent, TraceSession } from "@/lib/types";
import { cn, fmtDuration } from "@/lib/utils";
import { eventSummary, voiceMetadata } from "./model";

const WAVEFORM = [22, 42, 31, 62, 78, 39, 54, 84, 66, 28, 46, 72, 91, 55, 34, 68, 82, 48, 27, 58, 74, 44, 88, 61, 36, 69, 52, 79, 32, 57, 70, 41, 64, 86, 49, 25, 60, 77, 43, 67, 35, 71, 53, 81, 47, 63, 29, 75];

export function ReplayViewport({
  session,
  events,
  artifacts,
  modality,
  selectedSeq,
  currentMs,
  durationMs,
  playing,
  criticalSeq,
  onSelect,
  onSeek,
  onTogglePlayback,
}: {
  session: TraceSession;
  events: TraceEvent[];
  artifacts: ReplayArtifact[];
  modality: SessionModality;
  selectedSeq: number | null;
  currentMs: number;
  durationMs: number;
  playing: boolean;
  criticalSeq: number | null;
  onSelect: (seq: number) => void;
  onSeek: (ms: number) => void;
  onTogglePlayback: () => void;
}) {
  return (
    <section className="instrument-panel flex h-full flex-col overflow-hidden" aria-label={`${modality} replay`}>
      <div className="instrument-header">
        <div className="flex min-w-0 items-center gap-2">
          {modality === "voice" ? <Mic2 className="size-3.5 text-accent" /> : modality === "browser" ? <Globe2 className="size-3.5 text-accent" /> : <Code2 className="size-3.5 text-accent" />}
          <div className="min-w-0"><p className="micro">{modality} replay</p><p className="mono mt-1 truncate text-[10px] text-muted-foreground">{artifacts[0]?.storage_path ?? "trace reconstruction"}</p></div>
        </div>
        <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><i className="size-1.5 rounded-full bg-accent" />Synced</span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {modality === "voice" ? (
          <VoiceReplay events={events} selectedSeq={selectedSeq} criticalSeq={criticalSeq} currentMs={currentMs} durationMs={durationMs} onSelect={onSelect} />
        ) : modality === "browser" ? (
          <BrowserReplay session={session} events={events} selectedSeq={selectedSeq} criticalSeq={criticalSeq} currentMs={currentMs} durationMs={durationMs} onSelect={onSelect} />
        ) : (
          <GenericReplay session={session} events={events} selectedSeq={selectedSeq} onSelect={onSelect} />
        )}
      </div>

      <Transport currentMs={currentMs} durationMs={durationMs} playing={playing} onSeek={onSeek} onTogglePlayback={onTogglePlayback} />
    </section>
  );
}

function VoiceReplay({ events, selectedSeq, criticalSeq, currentMs, durationMs, onSelect }: { events: TraceEvent[]; selectedSeq: number | null; criticalSeq: number | null; currentMs: number; durationMs: number; onSelect: (seq: number) => void }) {
  const messages = events.filter((event) => event.type === "user_message" || event.type === "agent_message");
  const playhead = Math.max(0, Math.min(100, (currentMs / Math.max(1, durationMs)) * 100));

  return (
    <div className="flex min-h-full flex-col">
      <div className="border-b border-border/70 px-4 py-5">
        <div className="relative flex h-20 items-center gap-1 overflow-hidden" role="img" aria-label="Audio waveform showing speech activity across the call">
          {WAVEFORM.map((height, index) => {
            const elapsed = (index / WAVEFORM.length) * 100 <= playhead;
            return <span key={index} className={cn("min-w-0 flex-1 rounded-[1px]", elapsed ? "bg-accent/75" : "bg-border-strong")} style={{ height: `${height}%` }} />;
          })}
          <span className="pointer-events-none absolute inset-y-0 w-px bg-foreground" style={{ left: `${playhead}%` }} />
        </div>
        <div className="mt-2 flex justify-between"><span className="mono text-[10px] text-muted-foreground">00:00</span><span className="mono text-[10px] text-muted-foreground">{fmtDuration(durationMs)}</span></div>
      </div>
      <div className="p-2">
        <p className="micro px-1 py-2">Synchronized transcript</p>
        <ol className="space-y-1">
          {messages.map((event) => {
            const meta = voiceMetadata(event);
            const user = event.type === "user_message";
            const selected = selectedSeq === event.seq;
            const critical = criticalSeq === event.seq;
            return (
              <li key={event.seq}>
                <button type="button" onClick={() => onSelect(event.seq)} className={cn("w-full rounded-md px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", selected ? "bg-accent/10" : critical ? "bg-warning/5" : "hover:bg-elevated/70")}>
                  <span className="flex items-center gap-2">
                    <span className={cn("flex size-7 items-center justify-center rounded-md", user ? "bg-muted text-foreground" : "bg-accent/10 text-accent")}>{user ? <User className="size-3.5" /> : <Bot className="size-3.5" />}</span>
                    <span className="text-xs font-medium text-foreground">{user ? "User" : "Agent"}</span>
                    <span className="mono ml-auto text-[10px] tabular-nums text-muted-foreground">{fmtDuration(meta?.start_ms ?? event.t_offset_ms)}</span>
                  </span>
                  <span className="mt-1.5 block text-[13px] leading-relaxed text-foreground/90">{eventSummary(event)}</span>
                  <span className="mt-1.5 flex flex-wrap gap-1.5">
                    {meta?.interrupted ? <Signal label="interrupted" tone="bg-warning/10 text-warning" /> : null}
                    {typeof meta?.sentiment === "number" ? <Signal label={`sentiment ${meta.sentiment.toFixed(2)}`} tone={meta.sentiment < -0.2 ? "bg-warning/10 text-warning" : "bg-muted text-muted-foreground"} /> : null}
                    {critical ? <Signal label="intent drift" tone="bg-accent/10 text-accent" /> : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

function BrowserReplay({ session, events, selectedSeq, criticalSeq, currentMs, durationMs, onSelect }: { session: TraceSession; events: TraceEvent[]; selectedSeq: number | null; criticalSeq: number | null; currentMs: number; durationMs: number; onSelect: (seq: number) => void }) {
  const selected = events.find((event) => event.seq === selectedSeq) ?? events[0];
  const browserEvents = events.filter((event) => ["browser_action", "dom_snapshot", "screenshot", "tool_call", "tool_result"].includes(event.type));
  return (
    <div className="flex min-h-full flex-col">
      <div className="m-4 overflow-hidden rounded-lg border border-border bg-canvas">
        <div className="flex h-9 items-center gap-2 border-b border-border px-2"><span className="flex gap-1"><i className="size-1.5 rounded-full bg-muted-foreground/40" /><i className="size-1.5 rounded-full bg-muted-foreground/40" /><i className="size-1.5 rounded-full bg-muted-foreground/40" /></span><span className="mono flex-1 truncate rounded-sm border border-border bg-panel px-2 py-1 text-[9px] text-muted-foreground">replay://{session.agent ?? "agent"}/{session.id}</span></div>
        <div className="flex aspect-video flex-col items-center justify-center p-5 text-center">
          {selected?.seq === criticalSeq ? <AlertTriangle className="mb-3 size-7 text-warning" /> : <Globe2 className="mb-3 size-7 text-accent" />}
          <p className="mono text-[10px] uppercase tracking-wider text-muted-foreground">External world at {fmtDuration(currentMs)}</p>
          <p className="mt-2 max-w-sm text-sm font-medium leading-relaxed text-foreground">{selected ? eventSummary(selected) : "No browser state captured"}</p>
        </div>
      </div>
      <div className="px-4 pb-4"><p className="micro mb-2">Browser actions</p><ol className="divide-y divide-border/70">{browserEvents.map((event) => <li key={event.seq}><button type="button" onClick={() => onSelect(event.seq)} className={cn("grid w-full grid-cols-[44px_minmax(118px,0.8fr)_minmax(0,1.2fr)] items-center gap-2 px-2 py-3 text-left text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring", event.seq === selectedSeq ? "bg-accent/10" : "hover:bg-elevated/70")}><span className="mono text-muted-foreground">#{event.seq}</span><span className="mono truncate text-foreground">{event.type}</span><span className="truncate text-muted-foreground">{eventSummary(event)}</span></button></li>)}</ol></div>
      <span className="sr-only">Replay duration {fmtDuration(durationMs)}</span>
    </div>
  );
}

function GenericReplay({ session, events, selectedSeq, onSelect }: { session: TraceSession; events: TraceEvent[]; selectedSeq: number | null; onSelect: (seq: number) => void }) {
  return <div className="p-4"><div className="flex flex-col items-center rounded-lg bg-elevated/[0.55] px-5 py-6 text-center"><Image src="/illustrations/missing-artifact.webp" width={224} height={149} sizes="224px" alt="" aria-hidden="true" className="h-auto w-56 max-w-full object-contain" /><p className="mt-4 text-sm font-semibold">Trace reconstruction</p><p className="mt-1 max-w-sm text-[13px] leading-relaxed text-muted-foreground">This {String(session.metadata.modality ?? "agent")} run has no media artifact. Tool calls, messages, state, and goal checks remain fully inspectable.</p></div><ol className="mt-4 divide-y divide-border/70">{events.filter((event) => ["user_message", "agent_message", "tool_call", "tool_result", "goal_check"].includes(event.type)).map((event) => <li key={event.seq}><button type="button" onClick={() => onSelect(event.seq)} className={cn("w-full px-2 py-3 text-left text-xs transition-colors", event.seq === selectedSeq ? "bg-accent/10 text-foreground" : "hover:bg-elevated")}><span className="mono mr-2 text-muted-foreground">#{event.seq}</span>{eventSummary(event)}</button></li>)}</ol></div>;
}

function Transport({ currentMs, durationMs, playing, onSeek, onTogglePlayback }: { currentMs: number; durationMs: number; playing: boolean; onSeek: (ms: number) => void; onTogglePlayback: () => void }) {
  return (
    <div className="flex min-h-12 items-center gap-2 border-t border-border px-2">
      <button type="button" onClick={onTogglePlayback} aria-label={playing ? "Pause replay" : "Play replay"} className="flex size-9 items-center justify-center rounded-md bg-accent text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{playing ? <Pause className="size-4" /> : <Play className="size-4 translate-x-px" />}</button>
      <button type="button" onClick={() => onSeek(0)} aria-label="Restart replay" className="flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><RotateCcw className="size-3.5" /></button>
      <input type="range" min={0} max={Math.max(1, durationMs)} value={Math.min(currentMs, durationMs)} step={20} onChange={(event) => onSeek(Number(event.target.value))} aria-label="Seek replay" className="h-9 min-w-0 flex-1 accent-[hsl(var(--accent))]" />
      <span className="mono shrink-0 text-[10px] tabular-nums text-muted-foreground">{fmtDuration(currentMs)} / {fmtDuration(durationMs)}</span>
    </div>
  );
}

function Signal({ label, tone }: { label: string; tone: string }) {
  return <span className={cn("rounded-md px-1.5 py-1 text-[10px] font-medium", tone)}>{label}</span>;
}
