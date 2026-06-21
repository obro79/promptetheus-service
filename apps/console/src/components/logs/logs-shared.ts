import type { TraceEvent } from "@/lib/types";
import { fmtDuration } from "@/lib/utils";
import type { LogRun } from "./model";

export function toggleValue(values: string[], value: string): string[] {
  return values.includes(value)
    ? values.filter((candidate) => candidate !== value)
    : [...values, value];
}

export function uniqueSorted(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value)))).sort();
}

export function numberFormat(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

export function costEstimate(tokens: number): string {
  if (!tokens) return "$0.0000";
  return `$${((tokens / 1000) * 0.0015).toFixed(4)}`;
}

export function eventLatency(event: TraceEvent): number {
  const payload = event.payload as Record<string, unknown>;
  return Number(payload.latency_ms ?? payload.duration_ms ?? event.t_offset_ms ?? 0);
}

export function isFailedRun(run: LogRun): boolean {
  return ["failed", "error"].includes(run.session.status);
}

export function statusCounts(runs: LogRun[]) {
  return {
    all: runs.length,
    running: runs.filter((r) => r.session.status === "running").length,
    passed: runs.filter((r) => r.session.status === "passed").length,
    failed: runs.filter((r) => r.session.status === "failed").length,
    error: runs.filter((r) => r.session.status === "error").length,
  };
}

export function formatLatencyBadge(ms: number): { slow: boolean; label: string } {
  return { slow: ms >= 12000, label: fmtDuration(ms) };
}

export function agentScopedRuns(runs: LogRun[], agentId: string | null): LogRun[] {
  if (!agentId) return runs;
  return runs.filter((run) => run.session.project_id === agentId);
}
