"use client";

import * as React from "react";
import {
  AlertTriangle,
  Bot,
  Camera,
  CheckCircle2,
  Code2,
  Cpu,
  FileCode2,
  Flag,
  Gauge,
  MessageSquare,
  MousePointerClick,
  Network,
  Search,
  Square,
  Terminal,
  Wrench,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import type { PromptetheusEvent, TraceEvent } from "@/lib/types";
import { cn, fmtDuration } from "@/lib/utils";

type EventType = PromptetheusEvent["type"];

const EVENT_ICON: Record<EventType, LucideIcon> = {
  user_message: MessageSquare,
  agent_message: Bot,
  tool_call: Wrench,
  tool_result: Terminal,
  retrieval: Search,
  browser_action: MousePointerClick,
  dom_snapshot: Code2,
  screenshot: Camera,
  replay_artifact: FileCode2,
  goal_check: Flag,
  state_change: Cpu,
  session_end: Square,
  llm_call: Network,
  score: Gauge,
  error: AlertTriangle,
  metric: Gauge,
};

const EVENT_LABEL: Record<EventType, string> = {
  user_message: "User",
  agent_message: "Agent",
  tool_call: "Tool call",
  tool_result: "Tool result",
  retrieval: "Retrieval",
  browser_action: "Browser",
  dom_snapshot: "DOM snapshot",
  screenshot: "Screenshot",
  replay_artifact: "Replay artifact",
  goal_check: "Goal check",
  state_change: "State change",
  session_end: "Session end",
  llm_call: "LLM call",
  score: "Score",
  error: "Error",
  metric: "Metric",
};

/** A one-line human summary derived from the event payload. */
function summarize(ev: TraceEvent): string {
  const p = ev.payload as Record<string, unknown>;
  switch (ev.type) {
    case "user_message":
    case "agent_message":
      return String(p.content ?? "");
    case "tool_call":
      return `${String(p.tool_name ?? "tool")}(${
        p.arguments && typeof p.arguments === "object"
          ? Object.keys(p.arguments as object).join(", ")
          : ""
      })`;
    case "tool_result":
      if (p.error) return `error: ${String(p.error)}`;
      return p.result !== undefined ? JSON.stringify(p.result) : "ok";
    case "browser_action":
      return `${String(p.action ?? "")} → ${String(p.target ?? p.url ?? "")}`;
    case "dom_snapshot":
      return String(p.visible_text ?? p.url ?? "snapshot");
    case "screenshot":
      return String(p.source ?? "captured");
    case "retrieval":
      return String(p.query ?? "query");
    case "llm_call":
      return `${String(p.model ?? "model")} · ${String(p.input_tokens ?? "?")}→${String(
        p.output_tokens ?? "?",
      )} tok`;
    case "goal_check":
      return p.passed === false
        ? `failed — ${
            Array.isArray(p.mismatches) ? (p.mismatches as string[])[0] : "mismatch"
          }`
        : "passed";
    case "error":
      return String(p.message ?? p.error_type ?? "error");
    case "state_change":
      return String(p.name ?? "state changed");
    case "session_end":
      return `status: ${String(p.status ?? "—")}`;
    case "score":
      return `${String(p.name ?? "score")} = ${String(p.value ?? "")}`;
    case "metric":
      return `${String(p.name ?? "metric")} = ${String(p.value ?? "")}${String(
        p.unit ?? "",
      )}`;
    default:
      return ev.type;
  }
}

export const eventMeta = { EVENT_ICON, EVENT_LABEL, summarize };

export interface EventListProps {
  events: TraceEvent[];
  selectedSeq: number | null;
  criticalSeq: number | null;
  evidenceSeqs?: number[];
  onSelect: (seq: number) => void;
}

export function EventList({
  events,
  selectedSeq,
  criticalSeq,
  evidenceSeqs = [],
  onSelect,
}: EventListProps) {
  const itemRefs = React.useRef<Map<number, HTMLButtonElement>>(new Map());
  const evidence = React.useMemo(() => new Set(evidenceSeqs), [evidenceSeqs]);

  // keep the active row visible as selection moves (e.g. while scrubbing).
  React.useEffect(() => {
    if (selectedSeq === null) return;
    const el = itemRefs.current.get(selectedSeq);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedSeq]);

  return (
    <div className="surface flex h-full flex-col overflow-hidden rounded-2xl">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Events
        </span>
        <span className="mono text-[11px] tabular-nums text-muted-foreground">
          {events.length}
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto overscroll-contain [scrollbar-gutter:stable]">
        <ol>
          {events.map((ev) => {
            const Icon = EVENT_ICON[ev.type];
            const isSelected = ev.seq === selectedSeq;
            const isCritical = ev.seq === criticalSeq;
            const isEvidence = evidence.has(ev.seq);
            const isError =
              ev.type === "error" ||
              (ev.type === "goal_check" &&
                (ev.payload as { passed?: boolean }).passed === false);

            return (
              <li key={ev.seq}>
                <button
                  ref={(node) => {
                    if (node) itemRefs.current.set(ev.seq, node);
                    else itemRefs.current.delete(ev.seq);
                  }}
                  type="button"
                  onClick={() => onSelect(ev.seq)}
                  className={cn(
                    "group flex w-full items-start gap-2.5 border-l-2 border-transparent px-3 py-2 text-left transition-colors duration-150",
                    "hover:bg-elevated",
                    isSelected && "border-l-accent bg-elevated",
                    isCritical && !isSelected && "border-l-accent/50",
                  )}
                >
                  <span className="mono mt-0.5 w-6 shrink-0 text-right text-[11px] tabular-nums text-muted-foreground/60">
                    {ev.seq}
                  </span>
                  <span
                    className={cn(
                      "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded border",
                      isError
                        ? "border-destructive/30 bg-destructive/10 text-destructive"
                        : isCritical
                          ? "border-accent/30 bg-accent/10 text-accent"
                          : "border-border bg-canvas text-muted-foreground",
                    )}
                  >
                    <Icon className="size-3" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                      <span
                        className={cn(
                          "text-xs font-medium",
                          isSelected ? "text-foreground" : "text-foreground/90",
                        )}
                      >
                        {EVENT_LABEL[ev.type]}
                      </span>
                      {isCritical ? (
                        <span className="mono rounded bg-accent/15 px-1 text-[10px] font-medium uppercase tracking-wide text-accent">
                          critical
                        </span>
                      ) : null}
                      {isEvidence && !isCritical ? (
                        <span className="mono rounded bg-warning/15 px-1 text-[10px] font-medium uppercase tracking-wide text-warning">
                          evidence
                        </span>
                      ) : null}
                    </span>
                    <span className="mt-0.5 line-clamp-1 block text-[11px] leading-snug text-muted-foreground">
                      {summarize(ev)}
                    </span>
                  </span>
                  <span className="mono mt-0.5 shrink-0 text-[10px] tabular-nums text-muted-foreground/50">
                    {fmtDuration(ev.t_offset_ms)}
                  </span>
                  {isError ? (
                    <XCircle className="mt-0.5 size-3 shrink-0 text-destructive" />
                  ) : ev.type === "goal_check" ? (
                    <CheckCircle2 className="mt-0.5 size-3 shrink-0 text-success" />
                  ) : null}
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
