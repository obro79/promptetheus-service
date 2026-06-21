"use client";

import * as React from "react";
import { Suspense } from "react";

import type {
  AnalysisResult,
  Incident,
  Project,
  TraceEvent,
  TraceSession,
} from "@/lib/types";
import { LogsAgentNav } from "./logs-agent-nav";
import { LogsRunsPanel } from "./logs-runs-panel";
import { TracePanel, buildTraceTree, flattenTraceTree } from "./logs-trace-panel";
import { agentScopedRuns, statusCounts, toggleValue, uniqueSorted } from "./logs-shared";
import {
  DEFAULT_COLUMNS,
  buildLogRuns,
  deriveLogMetrics,
  filterLogRuns,
  groupRunsByAgent,
  sortLogRuns,
  type LogColumn,
  type LogFilters,
  type LogSortKey,
  type LogTimeRange,
} from "./model";
import { useLogsSelection } from "./use-logs-selection";

interface LogsDashboardProps {
  sessions: TraceSession[];
  projects: Project[];
  incidents: Incident[];
  eventsBySession: Record<string, TraceEvent[]>;
  analysesBySession: Record<string, AnalysisResult | undefined>;
}

export function LogsDashboard(props: LogsDashboardProps) {
  return (
    <Suspense fallback={<LogsDashboardSkeleton />}>
      <LogsDashboardInner {...props} />
    </Suspense>
  );
}

function LogsDashboardSkeleton() {
  return (
    <div className="logs-console-grid animate-pulse">
      <div className="hidden rounded-2xl bg-muted/40 lg:block" />
      <div className="rounded-2xl bg-muted/40" />
      <div className="rounded-2xl bg-muted/40" />
    </div>
  );
}

function LogsDashboardInner({
  sessions,
  projects,
  incidents,
  eventsBySession,
  analysesBySession,
}: LogsDashboardProps) {
  const runs = React.useMemo(
    () =>
      buildLogRuns({
        sessions,
        projects,
        incidents,
        eventsBySession,
        analysesBySession,
      }),
    [analysesBySession, eventsBySession, incidents, projects, sessions],
  );

  const agentGroups = React.useMemo(() => groupRunsByAgent(runs, projects), [runs, projects]);

  const [query, setQuery] = React.useState("");
  const [status, setStatus] = React.useState<LogFilters["status"]>("all");
  const [timeRange, setTimeRange] = React.useState<LogTimeRange>("7d");
  const [selectedEnvironments, setSelectedEnvironments] = React.useState<string[]>([]);
  const [selectedTags, setSelectedTags] = React.useState<string[]>([]);
  const [visibleColumns, setVisibleColumns] = React.useState<LogColumn[]>(DEFAULT_COLUMNS);
  const [sortKey, setSortKey] = React.useState<LogSortKey>("start_time");
  const [sortDirection, setSortDirection] = React.useState<"asc" | "desc">("desc");

  const traceScrollRef = React.useRef<HTMLElement>(null);
  const runRowRefs = React.useRef(new Map<string, HTMLTableRowElement>());

  const baseFilters = React.useMemo<Omit<LogFilters, "projects">>(
    () => ({
      query,
      status,
      failedOnly: false,
      timeRange,
      environments: selectedEnvironments,
      tags: selectedTags,
    }),
    [query, selectedEnvironments, selectedTags, status, timeRange],
  );

  const selectionRuns = React.useMemo(
    () =>
      sortLogRuns(
        filterLogRuns(runs, { ...baseFilters, projects: [] }),
        sortKey,
        sortDirection,
      ),
    [baseFilters, runs, sortDirection, sortKey],
  );

  const selection = useLogsSelection({
    runs,
    filteredRuns: selectionRuns,
    traceScrollRef,
    runRowRefs,
  });

  const displayFilters = React.useMemo<LogFilters>(
    () => ({
      ...baseFilters,
      projects: selection.selectedAgentId ? [selection.selectedAgentId] : [],
    }),
    [baseFilters, selection.selectedAgentId],
  );

  const displayRuns = React.useMemo(
    () => sortLogRuns(filterLogRuns(runs, displayFilters), sortKey, sortDirection),
    [displayFilters, runs, sortDirection, sortKey],
  );

  const runsForStatusCounts = React.useMemo(
    () => filterLogRuns(runs, { ...displayFilters, status: "all" }),
    [displayFilters, runs],
  );
  const counts = React.useMemo(() => statusCounts(runsForStatusCounts), [runsForStatusCounts]);
  const metrics = React.useMemo(() => deriveLogMetrics(displayRuns), [displayRuns]);

  const scopedRuns = React.useMemo(
    () => agentScopedRuns(runs, selection.selectedAgentId),
    [runs, selection.selectedAgentId],
  );
  const environments = React.useMemo(
    () => uniqueSorted(scopedRuns.map((run) => run.session.environment)),
    [scopedRuns],
  );
  const tags = React.useMemo(
    () => uniqueSorted(scopedRuns.flatMap((run) => run.session.tags)),
    [scopedRuns],
  );

  const traceTree = React.useMemo(
    () => buildTraceTree(selection.selectedRun?.events ?? []),
    [selection.selectedRun],
  );
  const visibleTrace = React.useMemo(
    () => flattenTraceTree(traceTree, selection.expanded),
    [selection.expanded, traceTree],
  );

  const hasFilters =
    Boolean(query) ||
    status !== "all" ||
    timeRange !== "7d" ||
    selectedEnvironments.length > 0 ||
    selectedTags.length > 0;

  const clearAllFilters = () => {
    setQuery("");
    setStatus("all");
    setSelectedEnvironments([]);
    setSelectedTags([]);
  };

  const onSort = (key: LogSortKey) => {
    if (sortKey === key) setSortDirection((direction) => (direction === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDirection(key === "run" || key === "status" ? "asc" : "desc");
    }
  };

  const handleAgentSelect = (agentId: string | null) => {
    selection.selectAgent(agentId);
    setSelectedEnvironments([]);
    setSelectedTags([]);
  };

  const tracePanel = (
    <TracePanel
      run={selection.selectedRun}
      traceTree={traceTree}
      visibleTrace={visibleTrace}
      expanded={selection.expanded}
      onExpandedChange={selection.setExpanded}
      selectedEvent={selection.selectedEvent}
      onEventSelect={selection.selectEvent}
      detailTab={selection.detailTab}
      onDetailTabChange={selection.setDetailTab}
      isFullView={selection.traceExpanded}
      onFullViewToggle={() => selection.setTraceExpanded((value) => !value)}
      traceScrollRef={traceScrollRef}
    />
  );

  return (
    <>
      <div className="logs-console-grid">
        <LogsAgentNav
          agentGroups={agentGroups}
          selectedAgentId={selection.selectedAgentId}
          onAgentSelect={handleAgentSelect}
          metrics={metrics}
          environments={environments}
          tags={tags}
          selectedEnvs={selectedEnvironments}
          selectedTags={selectedTags}
          onEnvironmentToggle={(env) =>
            setSelectedEnvironments((values) => toggleValue(values, env))
          }
          onTagToggle={(tag) => setSelectedTags((values) => toggleValue(values, tag))}
          onClearFilters={() => {
            setSelectedEnvironments([]);
            setSelectedTags([]);
          }}
        />

        <LogsRunsPanel
          runs={displayRuns}
          statusCounts={counts}
          selectedRunId={selection.selectedRun?.session.id}
          query={query}
          onQueryChange={setQuery}
          status={status}
          onStatusChange={setStatus}
          timeRange={timeRange}
          onTimeRangeChange={setTimeRange}
          visibleColumns={visibleColumns}
          onVisibleColumnsChange={setVisibleColumns}
          sortKey={sortKey}
          sortDirection={sortDirection}
          onSort={onSort}
          onSelectRun={selection.selectRun}
          runRowRefs={runRowRefs}
          hasFilters={hasFilters}
          onClearFilters={clearAllFilters}
        />

        <div className="flex min-h-0 flex-col overflow-hidden">{tracePanel}</div>
      </div>

      {selection.traceExpanded && selection.selectedRun ? (
        <div
          className="fixed inset-0 z-50 flex flex-col bg-canvas/95 backdrop-blur-sm"
          role="dialog"
          aria-label="Expanded trace view"
          aria-modal="true"
        >
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4">{tracePanel}</div>
        </div>
      ) : null}
    </>
  );
}
