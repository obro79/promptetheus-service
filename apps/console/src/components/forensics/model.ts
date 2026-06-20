import type {
  AnalysisResult,
  ReplayArtifact,
  SessionModality,
  TraceEvent,
  TraceSession,
  VoiceMessageMetadata,
} from "@/lib/types";

export interface ConsoleSelection {
  selectedSeq: number | null;
  currentMs: number;
  followLive: boolean;
  inspectorTab: "summary" | "io" | "state" | "metadata";
}

export type SelectionAction =
  | { type: "select"; seq: number; currentMs: number }
  | { type: "scrub"; currentMs: number }
  | { type: "tick"; seq: number | null; currentMs: number }
  | { type: "go-live"; seq: number | null; currentMs: number }
  | { type: "tab"; tab: ConsoleSelection["inspectorTab"] };

export function selectionReducer(
  state: ConsoleSelection,
  action: SelectionAction,
): ConsoleSelection {
  switch (action.type) {
    case "select":
      return { ...state, selectedSeq: action.seq, currentMs: action.currentMs, followLive: false };
    case "scrub":
      return { ...state, currentMs: Math.max(0, action.currentMs), followLive: false };
    case "tick":
      return { ...state, selectedSeq: action.seq, currentMs: Math.max(0, action.currentMs) };
    case "go-live":
      return { ...state, selectedSeq: action.seq, currentMs: action.currentMs, followLive: true };
    case "tab":
      return { ...state, inspectorTab: action.tab };
  }
}

export function inferModality(
  session: TraceSession,
  artifacts: ReplayArtifact[],
): SessionModality {
  const explicit = session.metadata.modality;
  if (typeof explicit === "string" && ["browser", "voice", "support", "workflow", "coding"].includes(explicit)) {
    return explicit as SessionModality;
  }
  if (artifacts.some((artifact) => artifact.kind === "audio") || session.tags.includes("voice")) return "voice";
  if (session.tags.includes("browser") || artifacts.some((artifact) => artifact.kind === "video")) return "browser";
  if ((session.agent ?? "").includes("coding")) return "coding";
  if ((session.agent ?? "").includes("support")) return "support";
  return "workflow";
}

export function voiceMetadata(event: TraceEvent): VoiceMessageMetadata | null {
  const metadata = (event.payload as Record<string, unknown>).metadata;
  if (!metadata || typeof metadata !== "object") return null;
  const candidate = metadata as Partial<VoiceMessageMetadata>;
  if (candidate.channel !== "voice" || typeof candidate.start_ms !== "number" || typeof candidate.end_ms !== "number") return null;
  return candidate as VoiceMessageMetadata;
}

export function offsetForEvent(event: TraceEvent, artifact?: ReplayArtifact): number {
  const mappedSeconds = artifact?.event_time_map[String(event.seq)];
  return typeof mappedSeconds === "number" ? mappedSeconds * 1000 : event.t_offset_ms;
}

export function evidenceSeqs(analysis?: AnalysisResult): number[] {
  if (!analysis) return [];
  return [...new Set(analysis.detections.flatMap((detection) => detection.evidence_refs))];
}

export function eventSummary(event: TraceEvent): string {
  const payload = event.payload as Record<string, unknown>;
  if (event.type === "user_message" || event.type === "agent_message") return String(payload.content ?? "Message");
  if (event.type === "tool_call") return `${String(payload.tool_name ?? "tool")}(${Object.keys((payload.arguments as object | undefined) ?? {}).join(", ")})`;
  if (event.type === "tool_result") return payload.error ? String(payload.error) : JSON.stringify(payload.result ?? "ok");
  if (event.type === "goal_check") return payload.passed === false ? `Failed: ${String((payload.mismatches as string[] | undefined)?.[0] ?? "goal mismatch")}` : "Goal achieved";
  if (event.type === "state_change") return `${String(payload.name ?? "state")} changed`;
  if (event.type === "score") return `${String(payload.name ?? "score")}: ${String(payload.value ?? "")}`;
  if (event.type === "browser_action") return `${String(payload.action ?? "action")} ${String(payload.target ?? payload.url ?? "")}`.trim();
  if (event.type === "dom_snapshot") return String(payload.visible_text ?? payload.url ?? "DOM snapshot");
  if (event.type === "error") return String(payload.message ?? payload.error_type ?? "Error");
  return event.type.replaceAll("_", " ");
}

export function failureMismatch(events: TraceEvent[]): string | null {
  const goal = [...events].reverse().find((event) => event.type === "goal_check");
  const mismatches = (goal?.payload as { mismatches?: string[] } | undefined)?.mismatches;
  return mismatches?.[0] ?? null;
}
