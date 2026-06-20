"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

import { JsonViewer } from "@/components/common/json-viewer";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { AnalysisResult, TraceEvent, TraceSession } from "@/lib/types";
import { cn, fmtDuration } from "@/lib/utils";
import { eventSummary, failureMismatch, type ConsoleSelection } from "./model";

export function StepInspector({
  session,
  event,
  events,
  analysis,
  evidence,
  criticalSeq,
  tab,
  hasPrev,
  hasNext,
  onTabChange,
  onSelect,
  onPrev,
  onNext,
  onClose,
}: {
  session: TraceSession;
  event?: TraceEvent;
  events: TraceEvent[];
  analysis?: AnalysisResult;
  evidence: number[];
  criticalSeq: number | null;
  tab: ConsoleSelection["inspectorTab"];
  hasPrev: boolean;
  hasNext: boolean;
  onTabChange: (tab: ConsoleSelection["inspectorTab"]) => void;
  onSelect: (seq: number) => void;
  onPrev: () => void;
  onNext: () => void;
  onClose?: () => void;
}) {
  const mismatch = failureMismatch(events);
  const critical = event?.seq === criticalSeq;
  const evidenceEvent = event ? evidence.includes(event.seq) : false;
  const priorAgentMessage = event
    ? [...events].reverse().find((candidate) => candidate.seq < event.seq && candidate.type === "agent_message")
    : undefined;

  return (
    <section className="instrument-panel flex h-full flex-col overflow-hidden" aria-label="Step inspector">
      <div className="instrument-header">
        <div><p className="micro">Step inspector</p>{event ? <p className="mono mt-1 text-[10px] text-muted-foreground">seq {event.seq} · {fmtDuration(event.t_offset_ms)}</p> : null}</div>
        <div className="flex items-center gap-1">
          <IconButton label="Previous event" disabled={!hasPrev} onClick={onPrev}><ChevronLeft className="size-4" /></IconButton>
          <IconButton label="Next event" disabled={!hasNext} onClick={onNext}><ChevronRight className="size-4" /></IconButton>
          {onClose ? <IconButton label="Close inspector" onClick={onClose}><X className="size-4" /></IconButton> : null}
        </div>
      </div>

      {!event ? <div className="flex flex-1 items-center justify-center p-6 text-center text-xs text-muted-foreground">Select an event to inspect its meaning and evidence.</div> : (
        <Tabs value={tab} onValueChange={(value) => onTabChange(value as ConsoleSelection["inspectorTab"])} className="flex min-h-0 flex-1 flex-col">
          <TabsList className="mx-3 mt-1 flex"><TabsTrigger value="summary">Summary</TabsTrigger><TabsTrigger value="io">I/O</TabsTrigger><TabsTrigger value="state">State</TabsTrigger><TabsTrigger value="metadata">Metadata</TabsTrigger></TabsList>
          <div className="min-h-0 flex-1 overflow-auto px-4 pb-4">
            <TabsContent value="summary" className="mt-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="mono rounded-md bg-elevated px-2 py-1 text-[11px] text-foreground">{event.type}</span>
                {critical ? <Flag label="critical cause" className="bg-accent/10 text-accent" /> : null}
                {evidenceEvent ? <Flag label="evidence" className="bg-warning/10 text-warning" /> : null}
              </div>
              <Section title="What happened"><p>{eventSummary(event)}</p></Section>
              <Section title="Agent believed"><p>{priorAgentMessage ? eventSummary(priorAgentMessage) : "The selected action would advance the current task."}</p></Section>
              <Section title="Actual user goal"><p>{session.user_goal ?? "No explicit goal was captured."}</p></Section>
              {mismatch ? <Section title="Observed mismatch" tone="warning"><p>{mismatch}</p></Section> : null}
              {analysis?.root_cause ? <Section title="Root cause"><p>{analysis.root_cause}</p></Section> : null}
              <Section title="Evidence">
                <div className="flex flex-wrap gap-1.5">{evidence.length ? evidence.map((seq) => <button key={seq} type="button" onClick={() => onSelect(seq)} className={cn("mono min-h-8 rounded-md px-2 text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", seq === event.seq ? "bg-accent/[0.12] text-accent" : "bg-elevated text-muted-foreground hover:bg-muted hover:text-foreground")}>seq {seq}</button>) : <span className="text-xs text-muted-foreground">No evidence refs were attached.</span>}</div>
              </Section>
            </TabsContent>
            <TabsContent value="io" className="mt-3 space-y-3"><Section title="Event payload"><JsonViewer data={event.payload} collapseDepth={3} /></Section>{event.type === "tool_call" || event.type === "tool_result" ? <p className="text-[11px] leading-relaxed text-muted-foreground">Tool input and output remain paired by call ID in the trace.</p> : null}</TabsContent>
            <TabsContent value="state" className="mt-3 space-y-3"><Section title="Goal state"><p>{mismatch ?? "No explicit goal mismatch was reported for this step."}</p></Section>{analysis?.observed_final_state ? <Section title="Observed final state" tone="warning"><p>{analysis.observed_final_state}</p></Section> : null}<Section title="Detection labels"><div className="flex flex-wrap gap-1.5">{analysis?.labels.map((label) => <Flag key={label} label={label.replaceAll("_", " ")} className="border-border text-muted-foreground" />) ?? <span className="text-xs text-muted-foreground">Not analyzed</span>}</div></Section></TabsContent>
            <TabsContent value="metadata" className="mt-3 space-y-3"><Section title="Envelope"><JsonViewer data={{ seq: event.seq, timestamp: event.timestamp, span_id: event.span_id, parent_id: event.parent_id, t_offset_ms: event.t_offset_ms }} collapseDepth={2} /></Section>{event.metadata ? <Section title="Metadata"><JsonViewer data={event.metadata} collapseDepth={2} /></Section> : null}</TabsContent>
          </div>
        </Tabs>
      )}
    </section>
  );
}

function Section({ title, children, tone }: { title: string; children: React.ReactNode; tone?: "warning" }) {
  return <section className={cn("mt-4 border-t border-border/70 pt-4", tone === "warning" && "-mx-2 rounded-md border-l-2 border-l-warning bg-warning/5 px-3 pb-3")}><h3 className={cn("mb-2 text-xs font-medium text-muted-foreground", tone === "warning" && "text-warning")}>{title}</h3><div className="text-[13px] leading-relaxed text-foreground/90">{children}</div></section>;
}

function Flag({ label, className }: { label: string; className?: string }) {
  return <span className={cn("rounded-md px-2 py-1 text-[10px] font-medium", className)}>{label}</span>;
}

function IconButton({ label, disabled, onClick, children }: { label: string; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" aria-label={label} disabled={disabled} onClick={onClick} className="flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-35">{children}</button>;
}
