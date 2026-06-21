"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  FileJson,
  Gauge,
  MessageSquare,
  Minimize2,
  Sparkles,
  Terminal,
  UnfoldVertical,
  type LucideIcon,
} from "lucide-react";

import { JsonViewer } from "@/components/common/json-viewer";
import { LabelTag } from "@/components/common/label-tag";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { TraceEvent } from "@/lib/types";
import { cn, fmtDuration } from "@/lib/utils";
import { costEstimate, eventLatency, isFailedRun, numberFormat } from "./logs-shared";
import {
  allExpandable,
  buildTraceTree,
  eventTitle,
  flattenTraceTree,
  type LogRun,
  type TraceNode,
  type VisibleTraceNode,
} from "./model";
import type { LogDetailTab } from "./use-logs-selection";

const EVENT_ICON: Partial<Record<TraceEvent["type"], LucideIcon>> = {
  user_message: MessageSquare,
  agent_message: Bot,
  llm_call: Sparkles,
  tool_call: Terminal,
  tool_result: Terminal,
  browser_action: CircleDot,
  goal_check: CheckCircle2,
  error: AlertCircle,
  metric: Gauge,
  score: Gauge,
};

export interface TracePanelProps {
  run: LogRun | undefined;
  traceTree: TraceNode[];
  visibleTrace: VisibleTraceNode[];
  expanded: Set<string>;
  onExpandedChange: (value: Set<string>) => void;
  selectedEvent: TraceEvent | undefined;
  onEventSelect: (event: TraceEvent) => void;
  detailTab: LogDetailTab;
  onDetailTabChange: (tab: LogDetailTab) => void;
  onClose?: () => void;
  traceScrollRef?: React.RefObject<HTMLElement | null>;
}

export function TracePanel({
  run,
  traceTree,
  visibleTrace,
  expanded,
  onExpandedChange,
  selectedEvent,
  onEventSelect,
  detailTab,
  onDetailTabChange,
  onClose,
  traceScrollRef,
}: TracePanelProps) {
  if (!run) {
    return null;
  }

  return (
    <section className="flex h-full min-h-0 flex-1 flex-col gap-3" aria-label="Trace detail">
      {isFailedRun(run) ? <FailureSummaryStrip run={run} /> : null}

      <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row lg:gap-4">
        <TraceWaterfall
          run={run}
          traceTree={traceTree}
          visibleTrace={visibleTrace}
          expanded={expanded}
          onExpandedChange={onExpandedChange}
          selectedEvent={selectedEvent}
          onEventSelect={onEventSelect}
          onClose={onClose}
          traceScrollRef={traceScrollRef}
          className="lg:min-h-0 lg:flex-1"
        />
        <RunInspector
          run={run}
          event={selectedEvent}
          tab={detailTab}
          onTabChange={onDetailTabChange}
          onEvidenceSelect={(seq) => {
            const match = run.events.find((candidate) => candidate.seq === seq);
            if (match) onEventSelect(match);
          }}
          className="lg:min-h-0 lg:flex-1"
        />
      </div>
    </section>
  );
}

function FailureSummaryStrip({ run }: { run: LogRun }) {
  const rootCause =
    run.analysis?.root_cause ?? run.errorPreview ?? "Run failed without a recorded root cause.";

  return (
    <div className="landing-framed-surface console-panel-pad flex items-center gap-3 border-warning/25 bg-warning/[0.04] py-3">
      <AlertCircle className="size-4 shrink-0 text-warning" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-warning">Failure summary</p>
        <p className="mt-1 text-sm leading-relaxed text-foreground/90">{rootCause}</p>
      </div>
      {run.incident ? (
        <Link
          href={`/incidents/${run.incident.id}`}
          className="shrink-0 self-center text-xs font-medium text-accent transition-colors hover:text-accent-bright focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          View incident →
        </Link>
      ) : null}
    </div>
  );
}

function TraceWaterfall({
  run,
  traceTree,
  visibleTrace,
  expanded,
  onExpandedChange,
  selectedEvent,
  onEventSelect,
  onClose,
  traceScrollRef,
  className,
}: {
  run: LogRun;
  traceTree: TraceNode[];
  visibleTrace: VisibleTraceNode[];
  expanded: Set<string>;
  onExpandedChange: (value: Set<string>) => void;
  selectedEvent: TraceEvent | undefined;
  onEventSelect: (event: TraceEvent) => void;
  onClose?: () => void;
  traceScrollRef?: React.RefObject<HTMLElement | null>;
  className?: string;
}) {
  return (
    <div
      className={cn("instrument-panel flex min-h-0 flex-1 flex-col overflow-hidden", className)}
      aria-label="Trace waterfall"
    >
      <div className="instrument-header">
        <div className="min-w-0">
          <p className="micro">Trace waterfall</p>
          <p className="mono mt-0.5 text-[10px] text-muted-foreground">
            {run.events.length} events · {traceTree.length} roots
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => onExpandedChange(allExpandable(traceTree))}
            className="flex size-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Expand all trace nodes"
          >
            <UnfoldVertical className="size-3.5" />
          </button>
          {onClose ? (
            <Button variant="outline" size="sm" type="button" onClick={onClose}>
              <Minimize2 className="size-3.5" />
              Exit full view
            </Button>
          ) : null}
        </div>
      </div>
      <ol
        ref={traceScrollRef as React.RefObject<HTMLOListElement>}
        className="min-h-0 flex-1 overflow-auto py-1.5"
      >
        {visibleTrace.map(({ node, depth }) => {
          const event = node.event;
          const selected = selectedEvent?.seq === event.seq;
          const Icon = EVENT_ICON[event.type] ?? FileJson;
          const hasChildren = node.children.length > 0;
          const failed =
            event.type === "error" ||
            (event.type === "goal_check" &&
              (event.payload as { passed?: boolean }).passed === false);

          return (
            <li key={node.id} data-trace-seq={event.seq}>
              <div
                className={cn(
                  "grid min-h-10 w-full grid-cols-[minmax(0,1fr)_auto] items-center border-l-2 pr-3 text-left text-xs transition-colors",
                  selected
                    ? "border-l-accent bg-accent/10 text-foreground"
                    : "border-l-transparent text-muted-foreground hover:bg-elevated/70",
                )}
                style={{ paddingLeft: 8 + depth * 18 }}
                aria-current={selected ? "true" : undefined}
              >
                <span className="flex min-w-0 items-center gap-2">
                  {hasChildren ? (
                    <button
                      type="button"
                      onClick={() => {
                        const next = new Set(expanded);
                        if (next.has(node.id)) next.delete(node.id);
                        else next.add(node.id);
                        onExpandedChange(next);
                      }}
                      className="flex size-4 items-center justify-center rounded hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      aria-label={
                        expanded.has(node.id) ? "Collapse trace node" : "Expand trace node"
                      }
                    >
                      <ChevronRight
                        className={cn(
                          "size-3 transition-transform",
                          expanded.has(node.id) && "rotate-90",
                        )}
                      />
                    </button>
                  ) : (
                    <span className="size-4" />
                  )}
                  <button
                    type="button"
                    onClick={() => onEventSelect(event)}
                    className="flex min-w-0 flex-1 items-center gap-2 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <Icon
                      className={cn(
                        "size-3.5 shrink-0",
                        failed
                          ? "text-warning"
                          : event.type === "llm_call"
                            ? "text-accent"
                            : "text-muted-foreground",
                      )}
                    />
                    <span className="truncate text-foreground">{eventTitle(event)}</span>
                    {event.type === "llm_call" ? (
                      <LabelTag
                        label={String(
                          (event.payload as Record<string, unknown>).model ?? "model",
                        )}
                        className="hidden sm:inline-flex"
                      />
                    ) : null}
                  </button>
                </span>
                <span className="mono ml-2 shrink-0 rounded-full bg-elevated px-2 py-0.5 text-[10px] text-muted-foreground">
                  {fmtDuration(eventLatency(event))}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function RunInspector({
  run,
  event,
  tab,
  onTabChange,
  onEvidenceSelect,
  className,
}: {
  run: LogRun;
  event: TraceEvent | undefined;
  tab: LogDetailTab;
  onTabChange: (tab: LogDetailTab) => void;
  onEvidenceSelect: (seq: number) => void;
  className?: string;
}) {
  const eventPayload = event?.payload ?? {};
  const eventMetadata = event?.metadata ?? null;

  return (
    <div
      className={cn("instrument-panel flex min-h-0 flex-1 flex-col overflow-hidden", className)}
      aria-label="Run inspector"
    >
      <div className="instrument-header">
        <div className="min-w-0 flex-1">
          <p className="micro">Run inspector</p>
          <h2 className="truncate text-sm font-semibold text-foreground">
            {event ? eventTitle(event) : (run.session.user_goal ?? run.session.id)}
          </h2>
          <p className="mono truncate text-[10px] text-muted-foreground">
            {run.session.id}
            {event ? ` · seq ${event.seq}` : ""}
          </p>
        </div>
        <span className="mono ml-3 shrink-0 self-center rounded-full border border-border/60 bg-elevated px-3 py-1.5 text-[10px] text-muted-foreground">
          {costEstimate(run.totalTokens)}
        </span>
      </div>

      <Tabs
        value={tab}
        onValueChange={(value) => onTabChange(value as LogDetailTab)}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="console-panel-pad mt-2 flex w-auto self-start">
          <TabsTrigger value="run">Run</TabsTrigger>
          <TabsTrigger value="feedback">Feedback</TabsTrigger>
          <TabsTrigger value="metadata">Metadata</TabsTrigger>
        </TabsList>

        <div className="console-panel-pad min-h-0 flex-1 overflow-auto pb-4 pt-1">
          <TabsContent value="run" className="mt-2 space-y-5">
            <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
              <Readout label="Status" value={run.session.status} />
              <Readout label="Latency" value={fmtDuration(run.latencyMs)} />
              <Readout label="Tokens" value={numberFormat(run.totalTokens)} />
              <Readout label="Events" value={String(run.events.length)} />
            </div>
            <InspectorSection title="Input" defaultOpen>
              <CodeBlock>{run.inputPreview || "No input recorded."}</CodeBlock>
            </InspectorSection>
            <InspectorSection title="Output" defaultOpen>
              <CodeBlock>{run.outputPreview || "No output recorded."}</CodeBlock>
            </InspectorSection>
            {run.errorPreview ? (
              <InspectorSection title="Error" defaultOpen>
                <CodeBlock tone="error">{run.errorPreview}</CodeBlock>
              </InspectorSection>
            ) : null}
            <InspectorSection title="Selected event payload">
              <JsonViewer data={eventPayload} collapseDepth={2} />
            </InspectorSection>
          </TabsContent>

          <TabsContent value="feedback" className="mt-2 space-y-5">
            <div className="grid grid-cols-2 gap-2.5">
              <Readout
                label="Confidence"
                value={run.confidence !== null ? `${Math.round(run.confidence * 100)}%` : "pending"}
              />
              <Readout label="Signals" value={String(run.feedbackCount)} />
            </div>
            <InspectorSection title="Root cause" defaultOpen>
              <p className="text-sm leading-6 text-foreground/90">
                {run.analysis?.root_cause ?? "No analysis result has been attached."}
              </p>
            </InspectorSection>
            <InspectorSection title="Labels" defaultOpen>
              <div className="flex flex-wrap gap-1.5">
                {(run.analysis?.labels ?? run.session.tags).map((label) => (
                  <LabelTag key={label} label={label.replaceAll("_", " ")} />
                ))}
              </div>
            </InspectorSection>
            <InspectorSection title="Evidence refs" defaultOpen>
              <div className="flex flex-wrap gap-1.5">
                {run.analysis?.detections.flatMap((detection) => detection.evidence_refs).length ? (
                  Array.from(
                    new Set(run.analysis.detections.flatMap((detection) => detection.evidence_refs)),
                  ).map((seq) => (
                    <button
                      key={seq}
                      type="button"
                      onClick={() => onEvidenceSelect(seq)}
                      className="mono min-h-8 rounded-full border border-border bg-elevated px-2.5 text-[11px] text-accent transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      seq {seq}
                    </button>
                  ))
                ) : (
                  <span className="text-sm text-muted-foreground">No evidence refs attached.</span>
                )}
              </div>
            </InspectorSection>
          </TabsContent>

          <TabsContent value="metadata" className="mt-2 space-y-5">
            <InspectorSection title="Run metadata" defaultOpen>
              <JsonViewer
                data={{
                  session: run.session,
                  project: run.project,
                  incident: run.incident,
                  analysis: run.analysis,
                }}
                collapseDepth={2}
              />
            </InspectorSection>
            <InspectorSection title="Event envelope" defaultOpen>
              <JsonViewer
                data={
                  event
                    ? {
                        type: event.type,
                        seq: event.seq,
                        timestamp: event.timestamp,
                        span_id: event.span_id,
                        parent_id: event.parent_id,
                        metadata: eventMetadata,
                      }
                    : {}
                }
                collapseDepth={2}
              />
            </InspectorSection>
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border/60 bg-elevated px-3.5 py-2.5">
      <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className="mono mt-1.5 truncate text-xs font-medium text-foreground">{value}</dd>
    </div>
  );
}

function InspectorSection({
  title,
  children,
  defaultOpen,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details open={defaultOpen} className="group rounded-xl border border-border/60 bg-panel/40">
      <summary className="flex min-h-10 cursor-pointer list-none items-center justify-between px-3.5 text-xs font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {title}
        <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-border/50 p-3.5">{children}</div>
    </details>
  );
}

function CodeBlock({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: "error";
}) {
  return (
    <pre
      className={cn(
        "max-h-52 overflow-auto whitespace-pre-wrap rounded-xl border border-border/60 bg-canvas p-3.5 text-xs leading-6",
        tone === "error" ? "text-warning" : "text-foreground/90",
      )}
    >
      {children}
    </pre>
  );
}

// Re-export helpers used by orchestrator
export { buildTraceTree, flattenTraceTree };
