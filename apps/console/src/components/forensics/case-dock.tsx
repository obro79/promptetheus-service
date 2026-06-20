"use client";

import * as React from "react";
import { Check, ChevronDown, ChevronUp, Loader2, ShieldCheck } from "lucide-react";

import type { AnalysisResult, Incident, TraceEvent, TraceSession } from "@/lib/types";
import { cn } from "@/lib/utils";
import { eventSummary, failureMismatch } from "./model";

export function CaseDock({ session, events, analysis, incident, evidence, criticalSeq, onSelect }: { session: TraceSession; events: TraceEvent[]; analysis?: AnalysisResult; incident?: Incident; evidence: number[]; criticalSeq: number | null; onSelect: (seq: number) => void }) {
  const [expanded, setExpanded] = React.useState(true);
  const [generation, setGeneration] = React.useState<"idle" | "running" | "complete">(incident?.fix_agent_result?.regression_test ? "complete" : "idle");
  const timerRef = React.useRef<number | null>(null);
  const critical = events.find((event) => event.seq === criticalSeq);
  const mismatch = failureMismatch(events);
  const regression = incident?.fix_agent_result?.regression_test ?? `test("agent must verify the user goal before reporting success", async () => {\n  const run = await replayScenario("${session.id}");\n  expect(run.goal.status).not.toBe("achieved_without_evidence");\n});`;

  const generate = () => {
    setGeneration("running");
    timerRef.current = window.setTimeout(() => setGeneration("complete"), 900);
  };

  React.useEffect(() => () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
  }, []);

  return (
    <section className="surface mx-3 mb-3 overflow-hidden rounded-2xl" aria-label="Incident case summary">
      <button type="button" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded} className="flex min-h-11 w-full items-center justify-between px-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"><span className="micro">Case summary · attribute → prevent</span>{expanded ? <ChevronDown className="size-3.5 text-muted-foreground" /> : <ChevronUp className="size-3.5 text-muted-foreground" />}</button>
      {expanded ? <div className="grid border-t border-border/70 xl:grid-cols-[1.2fr_1fr_340px]">
        <div className="border-b border-border/70 p-4 xl:border-b-0 xl:border-r"><DockTitle>causal chain</DockTitle><ol className="mt-3 space-y-2 text-xs text-foreground/90"><Chain text={session.user_goal ?? "User supplied a task"} /><Chain text={critical ? eventSummary(critical) : "Agent diverged from the goal"} tone="signal" /><Chain text={mismatch ?? analysis?.root_cause ?? "Observed result did not satisfy the goal"} tone="warning" /><Chain text="Agent outcome was classified and packaged for prevention" /></ol></div>
        <div className="border-b border-border/70 p-4 xl:border-b-0 xl:border-r"><DockTitle>evidence stack</DockTitle><div className="mt-3 flex flex-wrap gap-1.5">{evidence.map((seq) => { const event = events.find((candidate) => candidate.seq === seq); return <button key={seq} type="button" onClick={() => onSelect(seq)} className="group min-h-9 rounded-md bg-elevated px-2.5 text-left transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><span className="mono text-[10px] text-accent">seq {seq}</span><span className="ml-2 text-[11px] text-muted-foreground group-hover:text-foreground">{event?.type ?? "event"}</span></button>; })}</div></div>
        <div className="p-4"><DockTitle>recommended action</DockTitle>{generation === "complete" ? <div className="mt-3"><div className="flex items-center gap-2 text-xs font-medium text-success"><Check className="size-3.5" />Regression test ready</div><pre className="mt-2 max-h-24 overflow-auto rounded-md bg-canvas p-2.5 text-[10px] leading-relaxed text-muted-foreground">{regression}</pre></div> : <button type="button" disabled={generation === "running"} onClick={generate} className="mt-3 flex min-h-10 w-full items-center justify-center gap-2 rounded-md bg-accent px-3 text-xs font-semibold text-accent-foreground transition-colors hover:bg-accent-bright focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">{generation === "running" ? <Loader2 className="size-3.5 animate-spin" /> : <ShieldCheck className="size-3.5" />}{generation === "running" ? "Generating regression…" : "Generate regression test"}</button>}</div>
      </div> : null}
    </section>
  );
}

function DockTitle({ children }: { children: React.ReactNode }) { return <h3 className="text-xs font-medium text-muted-foreground">{children}</h3>; }

function Chain({ text, tone }: { text: string; tone?: "signal" | "warning" }) { return <li className="flex items-start gap-2"><span className={cn("mt-1 size-1.5 shrink-0 rounded-full bg-muted-foreground", tone === "signal" && "bg-accent", tone === "warning" && "bg-warning")} /><span className={cn(tone === "signal" && "text-accent", tone === "warning" && "text-warning")}>{text}</span></li>; }
