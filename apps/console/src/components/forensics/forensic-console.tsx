"use client";

import * as React from "react";
import {
  Activity,
  Crosshair,
  Gauge,
  PanelRightOpen,
  Radio,
  ShieldCheck,
  TrendingDown,
} from "lucide-react";

import { ConfidenceMeter } from "@/components/common/confidence-meter";
import {
  Eyebrow,
  LandingAppContent,
  LandingAppShell,
} from "@/components/landing/landing-primitives";
import { MonoId } from "@/components/common/mono-id";
import { StatusPill } from "@/components/common/status-pill";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type {
  AnalysisResult,
  Incident,
  RegressionRun,
  ReplayArtifact,
  TraceEvent,
  TraceSession,
} from "@/lib/types";
import { cn, fmtDuration, pct } from "@/lib/utils";
import { CaseDock } from "./case-dock";
import { EventStream } from "./event-stream";
import { ForensicTimeline } from "./forensic-timeline";
import {
  evidenceSeqs,
  inferModality,
  offsetForEvent,
  selectionReducer,
  voiceMetadata,
  type ConsoleSelection,
} from "./model";
import { ReplayViewport } from "./replay-viewport";
import { StepInspector } from "./step-inspector";

export function ForensicConsole({
  session,
  events,
  analysis,
  artifacts,
  incident,
  regressionRuns = [],
}: {
  session: TraceSession;
  events: TraceEvent[];
  analysis?: AnalysisResult;
  artifacts: ReplayArtifact[];
  incident?: Incident;
  regressionRuns?: RegressionRun[];
}) {
  const ordered = React.useMemo(() => [...events].sort((a, b) => a.seq - b.seq), [events]);
  const media = artifacts.find((artifact) => artifact.kind === "video" || artifact.kind === "audio");
  const durationMs = Math.max(1, (media?.duration_s ?? session.duration_ms / 1000) * 1000);
  const criticalSeq = incident?.critical_step_seq ?? analysis?.critical_step_seq ?? null;
  const evidence = React.useMemo(() => evidenceSeqs(analysis), [analysis]);
  const modality = inferModality(session, artifacts);
  const firstSeq = criticalSeq ?? ordered[0]?.seq ?? null;
  const firstEvent = ordered.find((event) => event.seq === firstSeq);

  const [selection, dispatch] = React.useReducer(selectionReducer, {
    selectedSeq: firstSeq,
    currentMs: firstEvent ? offsetForEvent(firstEvent, media) : 0,
    followLive: session.status === "running",
    inspectorTab: "summary",
  });
  const [playing, setPlaying] = React.useState(false);
  const [inspectorOpen, setInspectorOpen] = React.useState(false);
  const [mobilePane, setMobilePane] = React.useState("replay");
  const [paneWidths, setPaneWidths] = React.useState<[number, number, number]>([34, 40, 26]);
  const currentMsRef = React.useRef(selection.currentMs);
  const selectedSeqRef = React.useRef(selection.selectedSeq);

  React.useEffect(() => {
    currentMsRef.current = selection.currentMs;
    selectedSeqRef.current = selection.selectedSeq;
  }, [selection.currentMs, selection.selectedSeq]);

  React.useEffect(() => {
    const saved = window.localStorage.getItem("promptetheus.forensic-pane-widths");
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as [number, number, number];
        if (parsed.length === 3 && parsed.every((value) => typeof value === "number")) setPaneWidths(parsed);
      } catch { /* ignore invalid user preference */ }
    }
    const params = new URLSearchParams(window.location.search);
    const seq = Number(params.get("seq"));
    const at = Number(params.get("at"));
    const tab = params.get("tab") as ConsoleSelection["inspectorTab"] | null;
    if (Number.isFinite(seq) && ordered.some((event) => event.seq === seq)) {
      const event = ordered.find((candidate) => candidate.seq === seq)!;
      dispatch({ type: "select", seq, currentMs: Number.isFinite(at) ? at : offsetForEvent(event, media) });
    }
    if (tab && ["summary", "io", "state", "metadata"].includes(tab)) dispatch({ type: "tab", tab });
  }, [media, ordered]);

  React.useEffect(() => {
    if (playing) return;
    const params = new URLSearchParams(window.location.search);
    if (selection.selectedSeq !== null) params.set("seq", String(selection.selectedSeq));
    params.set("at", String(Math.round(selection.currentMs)));
    params.set("tab", selection.inspectorTab);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, [playing, selection.selectedSeq, selection.currentMs, selection.inspectorTab]);

  React.useEffect(() => {
    if (!playing) return;
    let frame = 0;
    let previous = performance.now();
    const tick = (now: number) => {
      const next = Math.min(durationMs, currentMsRef.current + (now - previous));
      previous = now;
      const active = [...ordered].reverse().find((event) => offsetForEvent(event, media) <= next);
      currentMsRef.current = next;
      selectedSeqRef.current = active?.seq ?? selectedSeqRef.current;
      dispatch({ type: "tick", seq: selectedSeqRef.current, currentMs: next });
      if (next >= durationMs) setPlaying(false);
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, durationMs, media, ordered]);

  React.useEffect(() => {
    if (!selection.followLive || session.status !== "running") return;
    const last = ordered.at(-1);
    if (!last || last.seq === selection.selectedSeq) return;
    dispatch({ type: "go-live", seq: last.seq, currentMs: offsetForEvent(last, media) });
  }, [media, ordered, selection.followLive, selection.selectedSeq, session.status]);

  const selectEvent = React.useCallback((seq: number) => {
    const event = ordered.find((candidate) => candidate.seq === seq);
    if (!event) return;
    dispatch({ type: "select", seq, currentMs: offsetForEvent(event, media) });
  }, [media, ordered]);

  const selectedIndex = ordered.findIndex((event) => event.seq === selection.selectedSeq);
  const selectedEvent = selectedIndex >= 0 ? ordered[selectedIndex] : undefined;
  const prev = React.useCallback(() => { if (selectedIndex > 0) selectEvent(ordered[selectedIndex - 1].seq); }, [ordered, selectEvent, selectedIndex]);
  const next = React.useCallback(() => { if (selectedIndex >= 0 && selectedIndex < ordered.length - 1) selectEvent(ordered[selectedIndex + 1].seq); }, [ordered, selectEvent, selectedIndex]);

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement)?.tagName;
      if (["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(tag)) return;
      if (event.key === "j" || event.key === "ArrowDown") { event.preventDefault(); next(); }
      if (event.key === "k" || event.key === "ArrowUp") { event.preventDefault(); prev(); }
      if (event.key === " ") { event.preventDefault(); setPlaying((value) => !value); }
      if (event.key.toLowerCase() === "f" && criticalSeq !== null) { event.preventDefault(); selectEvent(criticalSeq); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [criticalSeq, next, prev, selectEvent]);

  const goLive = () => {
    const last = ordered.at(-1);
    dispatch({ type: "go-live", seq: last?.seq ?? null, currentMs: last ? offsetForEvent(last, media) : durationMs });
  };

  const sentiment = ordered.map(voiceMetadata).filter((value): value is NonNullable<typeof value> => value !== null && typeof value.sentiment === "number");
  const latestRegression = regressionRuns.at(-1);
  const regressionCovered = Boolean(incident?.fix_agent_result?.regression_test || latestRegression?.status === "complete");

  return (
    <LandingAppShell className="flex flex-col overflow-hidden">
      <header className="relative z-10 shrink-0 px-4 py-5 sm:px-6 lg:px-8">
        <div className="landing-container landing-use-case-container flex flex-col gap-5 px-0 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0 flex-1">
            <Eyebrow className="mb-4">
              <MonoId id={incident?.id ?? session.id} />
              <StatusPill status={incident?.status ?? session.status} />
              <span>{(incident?.label ?? analysis?.labels[0] ?? "session trace").replaceAll("_", " ")}</span>
            </Eyebrow>
            <h1 className="landing-display-lg line-clamp-2 max-w-5xl xl:line-clamp-1">{incident?.title ?? session.user_goal ?? "Untitled agent run"}</h1>
            <dl className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2">
              <Metric label="Agent" value={session.agent ?? "unknown"} />
              <Metric label="Environment" value={session.environment ?? "unknown"} />
              <Metric label="Confidence" value={analysis ? pct(analysis.confidence) : "pending"} Icon={Gauge} />
              <Metric label="Duration" value={fmtDuration(session.duration_ms)} Icon={Activity} />
              <Metric label="Sentiment" value={sentiment.length ? `${sentiment.at(-1)!.sentiment!.toFixed(2)} declining` : "not measured"} Icon={TrendingDown} tone={sentiment.at(-1)?.sentiment !== undefined && sentiment.at(-1)!.sentiment! < -0.2 ? "warning" : undefined} />
              <Metric label="Regression" value={regressionCovered ? "covered" : "not covered"} Icon={ShieldCheck} tone={regressionCovered ? "signal" : "warning"} />
            </dl>
          </div>
          <div className="flex flex-wrap items-center gap-1.5 xl:justify-end">
            {criticalSeq !== null ? <HeaderAction onClick={() => selectEvent(criticalSeq)} Icon={Crosshair} label="Jump to failure" /> : null}
            <HeaderAction onClick={() => setInspectorOpen((value) => !value)} Icon={PanelRightOpen} label="Inspector" />
            {session.status === "running" ? <HeaderAction onClick={goLive} Icon={Radio} label={selection.followLive ? "Following live" : "Go live"} active={selection.followLive} /> : null}
            <span className="mono ml-2 hidden text-[10px] text-muted-foreground lg:block">J/K step · Space play · F failure</span>
          </div>
        </div>
      </header>

      <LandingAppContent className="flex min-h-0 flex-1 flex-col px-4 pb-3 sm:px-6 lg:px-8">
      <div className="forensic-panes min-h-[430px] flex-1 gap-0" style={{ "--replay-pane": `${paneWidths[0]}fr`, "--events-pane": `${paneWidths[1]}fr`, "--inspector-pane": `${paneWidths[2]}fr` } as React.CSSProperties}>
        <ReplayViewport session={session} events={ordered} artifacts={artifacts} modality={modality} selectedSeq={selection.selectedSeq} currentMs={selection.currentMs} durationMs={durationMs} playing={playing} criticalSeq={criticalSeq} onSelect={selectEvent} onSeek={(currentMs) => dispatch({ type: "scrub", currentMs })} onTogglePlayback={() => setPlaying((value) => !value)} />
        <PaneDivider label="Resize replay and events panes" index={0} widths={paneWidths} onChange={setPaneWidths} />
        <EventStream events={ordered} selectedSeq={selection.selectedSeq} criticalSeq={criticalSeq} evidence={evidence} onSelect={(seq) => { selectEvent(seq); setInspectorOpen(true); }} />
        <PaneDivider label="Resize events and inspector panes" index={1} widths={paneWidths} onChange={setPaneWidths} />
        <div className="forensic-inspector-pane min-h-0" data-open={inspectorOpen}><StepInspector session={session} event={selectedEvent} events={ordered} analysis={analysis} evidence={evidence} criticalSeq={criticalSeq} tab={selection.inspectorTab} hasPrev={selectedIndex > 0} hasNext={selectedIndex >= 0 && selectedIndex < ordered.length - 1} onTabChange={(tab) => dispatch({ type: "tab", tab })} onSelect={selectEvent} onPrev={prev} onNext={next} /></div>
      </div>

      <div className="forensic-mobile min-h-[460px] p-2">
        <Tabs value={mobilePane} onValueChange={setMobilePane} className="flex min-h-[460px] flex-col"><TabsList className="grid grid-cols-3"><TabsTrigger value="replay">Replay</TabsTrigger><TabsTrigger value="events">Events</TabsTrigger><TabsTrigger value="inspector">Inspector</TabsTrigger></TabsList><TabsContent value="replay" className="min-h-0 flex-1"><ReplayViewport session={session} events={ordered} artifacts={artifacts} modality={modality} selectedSeq={selection.selectedSeq} currentMs={selection.currentMs} durationMs={durationMs} playing={playing} criticalSeq={criticalSeq} onSelect={selectEvent} onSeek={(currentMs) => dispatch({ type: "scrub", currentMs })} onTogglePlayback={() => setPlaying((value) => !value)} /></TabsContent><TabsContent value="events" className="min-h-[420px] flex-1"><EventStream events={ordered} selectedSeq={selection.selectedSeq} criticalSeq={criticalSeq} evidence={evidence} onSelect={selectEvent} /></TabsContent><TabsContent value="inspector" className="min-h-[420px] flex-1"><StepInspector session={session} event={selectedEvent} events={ordered} analysis={analysis} evidence={evidence} criticalSeq={criticalSeq} tab={selection.inspectorTab} hasPrev={selectedIndex > 0} hasNext={selectedIndex >= 0 && selectedIndex < ordered.length - 1} onTabChange={(tab) => dispatch({ type: "tab", tab })} onSelect={selectEvent} onPrev={prev} onNext={next} /></TabsContent></Tabs>
      </div>

      <ForensicTimeline events={ordered} durationMs={durationMs} currentMs={selection.currentMs} selectedSeq={selection.selectedSeq} criticalSeq={criticalSeq} evidence={evidence} modality={modality} onSelect={selectEvent} onScrub={(currentMs) => dispatch({ type: "scrub", currentMs })} />
      <CaseDock session={session} events={ordered} analysis={analysis} incident={incident} evidence={evidence} criticalSeq={criticalSeq} onSelect={selectEvent} />
      </LandingAppContent>
    </LandingAppShell>
  );
}

function Metric({ label, value, Icon, tone }: { label: string; value: string; Icon?: React.ComponentType<{ className?: string }>; tone?: "signal" | "warning" }) { return <div className="flex min-w-0 items-center gap-1.5"><dt className="flex items-center gap-1 text-[11px] text-muted-foreground">{Icon ? <Icon className="size-3" /> : null}{label}</dt><dd className={cn("mono truncate text-[11px] text-foreground", tone === "signal" && "text-accent", tone === "warning" && "text-warning")}>{value}</dd></div>; }

function HeaderAction({ onClick, Icon, label, active }: { onClick: () => void; Icon: React.ComponentType<{ className?: string }>; label: string; active?: boolean }) { return <button type="button" onClick={onClick} className={cn("flex min-h-10 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", active ? "border-accent/25 bg-accent-muted text-accent shadow-glow-sm" : "border-transparent text-muted-foreground hover:bg-elevated/70 hover:text-foreground")}><Icon className="size-3.5" />{label}</button>; }

function PaneDivider({ label, index, widths, onChange }: { label: string; index: 0 | 1; widths: [number, number, number]; onChange: (widths: [number, number, number]) => void }) {
  const adjust = React.useCallback((delta: number) => {
    const next = [...widths] as [number, number, number];
    const left = index;
    const right = index + 1;
    if (next[left] + delta < 20 || next[right] - delta < 20) return;
    next[left] += delta;
    next[right] -= delta;
    onChange(next);
    window.localStorage.setItem("promptetheus.forensic-pane-widths", JSON.stringify(next));
  }, [index, onChange, widths]);

  const onPointerDown = (event: React.PointerEvent<HTMLButtonElement>) => {
    const start = event.clientX;
    const base = [...widths] as [number, number, number];
    const move = (pointer: PointerEvent) => {
      const delta = ((pointer.clientX - start) / window.innerWidth) * 100;
      const next = [...base] as [number, number, number];
      if (next[index] + delta < 20 || next[index + 1] - delta < 20) return;
      next[index] += delta;
      next[index + 1] -= delta;
      onChange(next);
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return <button type="button" aria-label={label} className="pane-divider group cursor-col-resize items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onPointerDown={onPointerDown} onKeyDown={(event) => { if (event.key === "ArrowLeft") adjust(-2); if (event.key === "ArrowRight") adjust(2); }}><span className="h-10 w-px bg-border-strong transition-colors group-hover:bg-accent" /></button>;
}
