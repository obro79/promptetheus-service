"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight, Clock, Hash } from "lucide-react";

import { EvidenceChip, type EvidenceKind } from "@/components/common/evidence-chip";
import { JsonViewer } from "@/components/common/json-viewer";
import type { ReplayArtifact, TraceEvent } from "@/lib/types";
import { cn, fmtDuration, fmtTime } from "@/lib/utils";

import { eventMeta } from "./event-list";

export interface EventInspectorProps {
  event: TraceEvent | undefined;
  /** all artifacts for the session; we surface ones mapped to this event. */
  artifacts: ReplayArtifact[];
  /** true when this event is the analysis critical step. */
  isCritical?: boolean;
  /** analysis evidence seqs (to badge the event). */
  isEvidence?: boolean;
  hasPrev: boolean;
  hasNext: boolean;
  onPrev: () => void;
  onNext: () => void;
}

function artifactKind(a: ReplayArtifact): EvidenceKind {
  if (a.kind === "video") return "video";
  if (a.kind === "audio") return "audio";
  if (a.kind === "screenshot") return "screenshot";
  return "dom_snapshot";
}

export function EventInspector({
  event,
  artifacts,
  isCritical = false,
  isEvidence = false,
  hasPrev,
  hasNext,
  onPrev,
  onNext,
}: EventInspectorProps) {
  const relatedArtifacts = React.useMemo(() => {
    if (!event) return [];
    return artifacts.filter(
      (a) => Object.prototype.hasOwnProperty.call(a.event_time_map, String(event.seq)),
    );
  }, [artifacts, event]);

  return (
    <div className="surface flex h-full flex-col overflow-hidden rounded-2xl">
      {/* header */}
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <span className="mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Inspector
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onPrev}
            disabled={!hasPrev}
            aria-label="Previous event"
            className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors duration-150 hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-30"
          >
            <ChevronLeft className="size-4" />
          </button>
          <button
            type="button"
            onClick={onNext}
            disabled={!hasNext}
            aria-label="Next event"
            className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors duration-150 hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-30"
          >
            <ChevronRight className="size-4" />
          </button>
        </div>
      </div>

      {!event ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <p className="text-balance text-center text-xs text-muted-foreground">
            Select an event on the timeline or list to inspect its payload.
          </p>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto overscroll-contain p-3 [scrollbar-gutter:stable]">
          {/* type + flags */}
          <div className="flex flex-wrap items-center gap-2">
            <TypeBadge type={event.type} />
            {isCritical ? (
              <span className="mono inline-flex items-center rounded border border-accent/40 bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-accent">
                critical step
              </span>
            ) : null}
            {isEvidence && !isCritical ? (
              <span className="mono inline-flex items-center rounded border border-warning/40 bg-warning/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-warning">
                evidence
              </span>
            ) : null}
          </div>

          {/* meta grid */}
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
            <dt className="flex items-center gap-1 text-muted-foreground">
              <Hash className="size-3" /> seq
            </dt>
            <dd className="mono tabular-nums text-foreground">{event.seq}</dd>

            <dt className="flex items-center gap-1 text-muted-foreground">
              <Clock className="size-3" /> offset
            </dt>
            <dd className="mono tabular-nums text-foreground">
              {fmtDuration(event.t_offset_ms)}
            </dd>

            <dt className="text-muted-foreground">timestamp</dt>
            <dd className="mono tabular-nums text-foreground">
              {fmtTime(event.timestamp)}
            </dd>

            {event.span_id ? (
              <>
                <dt className="text-muted-foreground">span</dt>
                <dd className="mono truncate text-muted-foreground">{event.span_id}</dd>
              </>
            ) : null}
          </dl>

          {/* evidence / artifacts */}
          {relatedArtifacts.length > 0 ? (
            <div className="mt-3">
              <p className="mb-1.5 text-[11px] uppercase tracking-widest text-muted-foreground">
                Captured artifacts
              </p>
              <div className="flex flex-wrap gap-1.5">
                {relatedArtifacts.map((a) => (
                  <EvidenceChip
                    key={a.artifact_id}
                    kind={artifactKind(a)}
                    label={a.storage_path.split("/").pop() ?? a.artifact_id}
                  />
                ))}
              </div>
            </div>
          ) : null}

          {/* payload */}
          <div className="mt-3">
            <p className="mb-1.5 text-[11px] uppercase tracking-widest text-muted-foreground">
              Payload
            </p>
            <JsonViewer data={event.payload} collapseDepth={3} />
          </div>

          {/* metadata */}
          {event.metadata && Object.keys(event.metadata).length > 0 ? (
            <div className="mt-3">
              <p className="mb-1.5 text-[11px] uppercase tracking-widest text-muted-foreground">
                Metadata
              </p>
              <JsonViewer data={event.metadata} collapseDepth={2} />
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function TypeBadge({ type }: { type: TraceEvent["type"] }) {
  const Icon = eventMeta.EVENT_ICON[type];
  const isError = type === "error";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium",
        isError
          ? "border-destructive/30 bg-destructive/10 text-destructive"
          : "border-accent/30 bg-accent/10 text-accent",
      )}
    >
      <Icon className="size-3.5" />
      {eventMeta.EVENT_LABEL[type]}
      <span className="mono text-[10px] text-muted-foreground">{type}</span>
    </span>
  );
}
