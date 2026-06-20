import Link from "next/link";
import { Bot, ChevronRight, Layers, ShieldCheck, Zap } from "lucide-react";

import { getSessions } from "@/lib/data";
import {
  ConsolePage,
  ConsolePageContent,
  ConsolePageHeader,
  ConsoleEyebrow,
  MetricReadout,
  SignalChip,
} from "@/components/common/console-primitives";
import { StatusPill } from "@/components/common/status-pill";

export default function AgentsPage() {
  const sessions = getSessions();
  const agents = Array.from(
    new Set(sessions.map((session) => session.agent ?? "unknown")),
  ).map((name) => {
    const runs = sessions.filter(
      (session) => (session.agent ?? "unknown") === name,
    );
    const failed = runs.filter(
      (session) =>
        session.status === "failed" || session.status === "error",
    );
    return { name, runs, failed };
  });

  const degradedCount = agents.filter((a) => a.failed.length > 0).length;
  const healthyCount = agents.length - degradedCount;

  return (
    <ConsolePage>
      <ConsolePageHeader>
        <div className="min-w-0">
          <ConsoleEyebrow icon={<Bot className="size-3.5" strokeWidth={1.8} aria-hidden />}>
            Fleet health
          </ConsoleEyebrow>
          <h1 className="display max-w-4xl text-5xl leading-[0.92] text-foreground sm:text-6xl lg:text-7xl">
            Production agents
          </h1>
          <p className="mt-5 max-w-2xl text-sm leading-6 text-muted-foreground">
            Production agents ordered by observed runs and unresolved failure
            pressure. Click any row to open the most recent representative
            session.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-2.5 text-[11px] font-medium text-muted-foreground">
            <SignalChip Icon={ShieldCheck} label="Regression coverage tracked" />
            <SignalChip Icon={Zap} label="Live failure pressure" />
            <SignalChip Icon={Layers} label="Per-agent session history" />
          </div>
        </div>
        <dl className="grid w-full grid-cols-3 gap-3 lg:w-auto">
          <MetricReadout label="Agents" value={agents.length} />
          <MetricReadout label="Degraded" value={degradedCount} tone="warning" />
          <MetricReadout label="Healthy" value={healthyCount} tone="signal" />
        </dl>
      </ConsolePageHeader>

      <ConsolePageContent>
        <div className="surface overflow-hidden rounded-2xl">
          <div className="grid grid-cols-[minmax(0,1fr)_100px_100px_120px_36px] border-b border-border/50 bg-muted/35 px-4 py-2.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
            <span>Agent</span>
            <span>Runs</span>
            <span>Failures</span>
            <span>State</span>
            <span />
          </div>
          {agents.map((agent) => {
            const representative = agent.failed[0] ?? agent.runs[0];
            const degraded = agent.failed.length > 0;
            return (
              <Link
                key={agent.name}
                href={
                  representative
                    ? `/sessions/${representative.id}`
                    : "/sessions"
                }
                className="surface-hover grid min-h-16 grid-cols-[minmax(0,1fr)_100px_100px_120px_36px] items-center border-b border-border/40 px-4 text-xs transition-colors last:border-b-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
              >
                <span className="flex min-w-0 items-center gap-2.5">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-accent/20 bg-accent-muted text-accent">
                    <Bot className="size-4" strokeWidth={1.6} />
                  </span>
                  <span className="mono truncate text-foreground">
                    {agent.name}
                  </span>
                </span>
                <span className="mono tabular-nums text-muted-foreground">
                  {agent.runs.length}
                </span>
                <span className="mono tabular-nums text-warning">
                  {agent.failed.length}
                </span>
                <StatusPill status={degraded ? "failed" : "passed"} />
                <ChevronRight className="size-4 text-muted-foreground" />
              </Link>
            );
          })}
        </div>
      </ConsolePageContent>
    </ConsolePage>
  );
}
