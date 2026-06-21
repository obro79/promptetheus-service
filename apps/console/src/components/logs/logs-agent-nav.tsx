"use client";

import * as React from "react";
import {
  Activity,
  AlertCircle,
  Bot,
  Coins,
  Gauge,
  Timer,
  type LucideIcon,
} from "lucide-react";

import { cn, fmtDuration, pct } from "@/lib/utils";
import type { AgentGroup, LogMetrics } from "./model";
import { numberFormat } from "./logs-shared";

export interface LogsAgentNavProps {
  agentGroups: AgentGroup[];
  selectedAgentId: string | null;
  onAgentSelect: (id: string | null) => void;
  metrics: LogMetrics;
  environments: string[];
  tags: string[];
  selectedEnvs: string[];
  selectedTags: string[];
  onEnvironmentToggle: (env: string) => void;
  onTagToggle: (tag: string) => void;
  onClearFilters: () => void;
}

export function LogsAgentNav({
  agentGroups,
  selectedAgentId,
  onAgentSelect,
  metrics,
  environments,
  tags,
  selectedEnvs,
  selectedTags,
  onEnvironmentToggle,
  onTagToggle,
  onClearFilters,
}: LogsAgentNavProps) {
  const totalRuns = agentGroups.reduce((sum, group) => sum + group.totalRuns, 0);
  const hasFilterChips = selectedEnvs.length > 0 || selectedTags.length > 0;

  return (
    <div className="flex flex-col gap-2 lg:contents">
      <div className="flex gap-2 overflow-x-auto pb-1 lg:hidden" aria-label="Agent strip">
        <AgentPill
          label="All agents"
          count={totalRuns}
          selected={selectedAgentId === null}
          onClick={() => onAgentSelect(null)}
        />
        {agentGroups.map((group) => (
          <AgentPill
            key={group.projectId}
            label={group.label}
            count={group.totalRuns}
            failedCount={group.failedRuns}
            selected={selectedAgentId === group.projectId}
            onClick={() => onAgentSelect(group.projectId)}
          />
        ))}
      </div>

      <aside
        className="hidden w-[240px] shrink-0 flex-col lg:flex"
        aria-label="Agent navigation"
      >
        <div className="landing-framed-surface flex min-h-0 flex-1 flex-col overflow-hidden">
          <nav aria-label="Agent list" className="flex min-h-0 flex-col">
            <div className="console-panel-pad border-b border-border/40 py-3">
              <h2 className="flex items-center gap-2 text-xs font-semibold text-foreground">
                <Bot className="size-3.5" />
                Agents
              </h2>
            </div>
            <ul className="max-h-[220px] flex-1 overflow-auto console-panel-pad py-2">
              <li>
                <AgentListButton
                  label="All agents"
                  count={totalRuns}
                  selected={selectedAgentId === null}
                  onClick={() => onAgentSelect(null)}
                />
              </li>
              {agentGroups.map((group) => (
                <li key={group.projectId}>
                  <AgentListButton
                    label={group.label}
                    count={group.totalRuns}
                    failedCount={group.failedRuns}
                    selected={selectedAgentId === group.projectId}
                    onClick={() => onAgentSelect(group.projectId)}
                  />
                </li>
              ))}
            </ul>
          </nav>

          <div className="border-t border-border/40">
            <div className="console-panel-pad flex items-center justify-between py-2.5">
              <h2 className="text-xs font-semibold text-foreground">Metrics</h2>
              <span className="text-[10px] text-muted-foreground">filtered</span>
            </div>
            <dl className="console-panel-pad grid grid-cols-2 gap-2 pb-3">
              <MetricTile label="Runs" value={String(metrics.totalRuns)} Icon={Activity} />
              <MetricTile label="Failures" value={String(metrics.failedRuns)} Icon={AlertCircle} />
              <MetricTile label="Error rate" value={pct(metrics.errorRate)} Icon={Gauge} />
              <MetricTile label="P50" value={fmtDuration(metrics.p50LatencyMs)} Icon={Timer} />
              <MetricTile label="P99" value={fmtDuration(metrics.p99LatencyMs)} Icon={Gauge} />
              <MetricTile label="Tokens" value={numberFormat(metrics.totalTokens)} Icon={Coins} />
            </dl>
          </div>

          {(environments.length > 0 || tags.length > 0) && (
            <div className="border-t border-border/40 console-panel-pad py-3">
              <div className="mb-2.5 flex items-center justify-between">
                <span className="text-[11px] font-medium text-muted-foreground">Filters</span>
                {hasFilterChips ? (
                  <button
                    type="button"
                    onClick={onClearFilters}
                    className="text-[11px] text-accent transition-colors hover:text-accent-bright focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    Clear
                  </button>
                ) : null}
              </div>
              {environments.length > 0 ? (
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {environments.map((env) => (
                    <ToggleChip
                      key={env}
                      label={env}
                      active={selectedEnvs.includes(env)}
                      onClick={() => onEnvironmentToggle(env)}
                    />
                  ))}
                </div>
              ) : null}
              {tags.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {tags.map((tag) => (
                    <ToggleChip
                      key={tag}
                      label={tag}
                      active={selectedTags.includes(tag)}
                      onClick={() => onTagToggle(tag)}
                    />
                  ))}
                </div>
              ) : null}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function AgentPill({
  label,
  count,
  failedCount,
  selected,
  onClick,
}: {
  label: string;
  count: number;
  failedCount?: number;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "border-accent/30 bg-accent/10 text-accent"
          : "border-border bg-panel text-muted-foreground hover:text-foreground",
      )}
    >
      <span className="max-w-[120px] truncate">{label}</span>
      <span className="mono text-[10px]">
        {failedCount && failedCount > 0 && !selected ? `${failedCount}/${count}` : count}
      </span>
    </button>
  );
}

function AgentListButton({
  label,
  count,
  failedCount,
  selected,
  onClick,
}: {
  label: string;
  count: number;
  failedCount?: number;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        "flex w-full items-center justify-between rounded-xl px-2.5 py-2.5 text-[12px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "bg-accent/10 font-medium text-accent"
          : "text-muted-foreground hover:bg-elevated hover:text-foreground",
      )}
    >
      <span className="truncate">{label}</span>
      <span
        className={cn(
          "mono ml-1.5 shrink-0 rounded-full px-2 py-0.5 text-[10px]",
          selected
            ? "bg-accent/15 text-accent"
            : "bg-elevated text-muted-foreground",
          failedCount && failedCount > 0 && !selected && "bg-warning/10 text-warning",
        )}
      >
        {failedCount && failedCount > 0 ? `${failedCount}/${count}` : count}
      </span>
    </button>
  );
}

function MetricTile({
  label,
  value,
  Icon,
}: {
  label: string;
  value: string;
  Icon: LucideIcon;
}) {
  return (
    <div className="rounded-xl border border-border/50 bg-elevated/50 px-3 py-2.5">
      <dt className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
        <Icon className="size-3" />
        {label}
      </dt>
      <dd className="mono mt-1 truncate text-sm font-medium text-foreground">{value}</dd>
    </div>
  );
}

function ToggleChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "mono inline-flex min-h-6 items-center rounded-full border px-2 py-0.5 text-[9px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-accent/30 bg-accent/10 text-accent"
          : "border-border bg-elevated text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
}
