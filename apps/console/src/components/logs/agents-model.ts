import type { SessionStatus } from "@/lib/types";
import type { LogRun } from "./model";

export interface AgentRow {
  id: string;
  name: string;
  version: string;
  runs: LogRun[];
  /** Status of the most recent run — drives the row status pill. */
  status: SessionStatus;
  lastRunAt: string;
  runCount: number;
  failedCount: number;
  successRate: number;
  avgLatencyMs: number;
  totalTokens: number;
  totalCost: number;
  environments: string[];
}

/** Per-1k-token blended estimate, matching the dashboard cost readout. */
const COST_PER_1K_TOKENS = 0.0015;

export function estimateCost(tokens: number): number {
  return (tokens / 1000) * COST_PER_1K_TOKENS;
}

function splitAgent(agent: string | null): { name: string; version: string } {
  if (!agent) return { name: "unknown-agent", version: "—" };
  const at = agent.lastIndexOf("@");
  if (at === -1) return { name: agent, version: "—" };
  return { name: agent.slice(0, at), version: agent.slice(at + 1) };
}

function average(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

/** Group runs into agents keyed by `agent` (name@version), newest run first. */
export function buildAgents(runs: LogRun[]): AgentRow[] {
  const groups = new Map<string, LogRun[]>();
  for (const run of runs) {
    const key = run.session.agent ?? "unknown-agent";
    const bucket = groups.get(key);
    if (bucket) bucket.push(run);
    else groups.set(key, [run]);
  }

  const rows: AgentRow[] = [];
  for (const [key, groupRuns] of groups) {
    const sorted = [...groupRuns].sort((a, b) =>
      b.session.started_at.localeCompare(a.session.started_at),
    );
    const { name, version } = splitAgent(key);
    const failedCount = sorted.filter((run) =>
      ["failed", "error"].includes(run.session.status),
    ).length;
    const totalTokens = sorted.reduce((sum, run) => sum + run.totalTokens, 0);
    rows.push({
      id: key,
      name,
      version,
      runs: sorted,
      status: sorted[0].session.status,
      lastRunAt: sorted[0].session.started_at,
      runCount: sorted.length,
      failedCount,
      successRate: sorted.length ? (sorted.length - failedCount) / sorted.length : 0,
      avgLatencyMs: average(sorted.map((run) => run.latencyMs)),
      totalTokens,
      totalCost: estimateCost(totalTokens),
      environments: Array.from(
        new Set(sorted.map((run) => run.session.environment).filter(Boolean) as string[]),
      ),
    });
  }

  return rows.sort((a, b) => b.lastRunAt.localeCompare(a.lastRunAt));
}
