"use client";

import * as React from "react";
import {
  Activity,
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Columns3,
  Expand,
  FileJson,
  Filter,
  Gauge,
  ListFilter,
  MessageSquare,
  Minimize2,
  PanelRight,
  RotateCcw,
  Search,
  Sparkles,
  Tags,
  Terminal,
  Timer,
  X,
  type LucideIcon,
} from "lucide-react";

import { JsonViewer } from "@/components/common/json-viewer";
import { LabelTag } from "@/components/common/label-tag";
import { StatusPill } from "@/components/common/status-pill";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type {
  AnalysisResult,
  Incident,
  Project,
  TraceEvent,
  TraceSession,
} from "@/lib/types";
import { cn, fmtDuration, fmtRelative, pct, shortId } from "@/lib/utils";
import {
  DEFAULT_COLUMNS,
  buildLogRuns,
  buildTraceTree,
  deriveLogMetrics,
  eventTitle,
  filterLogRuns,
  flattenTraceTree,
  groupRunsByAgent,
  sortLogRuns,
  type AgentGroup,
  type LogColumn,
  type LogFilters,
  type LogRun,
  type LogSortKey,
  type LogTimeRange,
  type TraceNode,
} from "./model";

interface LogsDashboardProps {
  sessions: TraceSession[];
  projects: Project[];
  incidents: Incident[];
  eventsBySession: Record<string, TraceEvent[]>;
  analysesBySession: Record<string, AnalysisResult | undefined>;
}

const STATUS_FILTERS: Array<{ value: LogFilters["status"]; label: string }> = [
  { value: "all", label: "All" },
  { value: "failed", label: "Failed" },
  { value: "error", label: "Error" },
  { value: "running", label: "Running" },
  { value: "passed", label: "Passed" },
];

const TIME_RANGES: Array<{ value: LogTimeRange; label: string }> = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "all", label: "All" },
  { value: "1h", label: "1h" },
];

const COLUMN_LABELS: Record<LogColumn, string> = {
  status: "Status",
  run: "Run",
  input: "Input",
  output: "Output",
  error: "Error",
  project: "Project",
  environment: "Env",
  start_time: "Start Time",
  latency: "Latency",
  feedback: "Feedback",
  tokens: "Tokens",
};

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

function allExpandable(nodes: TraceNode[], ids = new Set<string>()): Set<string> {
  for (const node of nodes) {
    if (node.children.length) ids.add(node.id);
    allExpandable(node.children, ids);
  }
  return ids;
}

function toggleValue(values: string[], value: string): string[] {
  return values.includes(value)
    ? values.filter((candidate) => candidate !== value)
    : [...values, value];
}

function uniqueSorted(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value)))).sort();
}

function numberFormat(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function costEstimate(tokens: number): string {
  if (!tokens) return "$0.0000";
  return `$${((tokens / 1000) * 0.0015).toFixed(4)}`;
}

function eventLatency(event: TraceEvent): number {
  const payload = event.payload as Record<string, unknown>;
  return Number(payload.latency_ms ?? payload.duration_ms ?? event.t_offset_ms ?? 0);
}

function firstFailedEvent(run: LogRun): TraceEvent | undefined {
  const critical = run.analysis?.critical_step_seq;
  return (
    run.events.find((event) => event.seq === critical) ??
    run.events.find(
      (event) =>
        event.type === "error" ||
        (event.type === "goal_check" &&
          (event.payload as { passed?: boolean }).passed === false),
    ) ??
    run.events[0]
  );
}

export function LogsDashboard({
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

  const allTags = React.useMemo(
    () => uniqueSorted(runs.flatMap((run) => run.session.tags)),
    [runs],
  );
  const environments = React.useMemo(
    () => uniqueSorted(runs.map((run) => run.session.environment)),
    [runs],
  );

  const [selectedAgentId, setSelectedAgentId] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");
  const [status, setStatus] = React.useState<LogFilters["status"]>("all");
  const [failedOnly, setFailedOnly] = React.useState(true);
  const [timeRange, setTimeRange] = React.useState<LogTimeRange>("7d");
  const [selectedEnvironments, setSelectedEnvironments] = React.useState<string[]>([]);
  const [selectedTags, setSelectedTags] = React.useState<string[]>([]);
  const [visibleColumns, setVisibleColumns] = React.useState<LogColumn[]>(DEFAULT_COLUMNS);
  const [sortKey, setSortKey] = React.useState<LogSortKey>("start_time");
  const [sortDirection, setSortDirection] = React.useState<"asc" | "desc">("desc");
  const [selectedRunId, setSelectedRunId] = React.useState(
    runs.find((run) => ["failed", "error"].includes(run.session.status))?.session.id ??
      runs[0]?.session.id ??
      "",
  );
  const [selectedSeq, setSelectedSeq] = React.useState<number | null>(null);
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const [detailTab, setDetailTab] = React.useState<"run" | "feedback" | "metadata">("run");
  const [traceExpanded, setTraceExpanded] = React.useState(false);

  const filters = React.useMemo<LogFilters>(
    () => ({
      query,
      status,
      failedOnly,
      timeRange,
      projects: selectedAgentId ? [selectedAgentId] : [],
      environments: selectedEnvironments,
      tags: selectedTags,
    }),
    [failedOnly, query, selectedAgentId, selectedEnvironments, selectedTags, status, timeRange],
  );

  const filteredRuns = React.useMemo(
    () => sortLogRuns(filterLogRuns(runs, filters), sortKey, sortDirection),
    [filters, runs, sortDirection, sortKey],
  );
  const metrics = React.useMemo(() => deriveLogMetrics(filteredRuns), [filteredRuns]);
  const selectedRun = React.useMemo(
    () => runs.find((run) => run.session.id === selectedRunId) ?? filteredRuns[0] ?? runs[0],
    [filteredRuns, runs, selectedRunId],
  );
  const traceTree = React.useMemo(
    () => buildTraceTree(selectedRun?.events ?? []),
    [selectedRun],
  );
  const visibleTrace = React.useMemo(
    () => flattenTraceTree(traceTree, expanded),
    [expanded, traceTree],
  );
  const selectedEvent = React.useMemo(
    () =>
      selectedRun?.events.find((event) => event.seq === selectedSeq) ??
      (selectedRun ? firstFailedEvent(selectedRun) : undefined),
    [selectedRun, selectedSeq],
  );

  const hasSidebarFilters =
    selectedEnvironments.length > 0 ||
    selectedTags.length > 0;

  React.useEffect(() => {
    if (filteredRuns.length && !filteredRuns.some((run) => run.session.id === selectedRunId)) {
      setSelectedRunId(filteredRuns[0].session.id);
    }
  }, [filteredRuns, selectedRunId]);

  React.useEffect(() => {
    if (!selectedRun) return;
    const initialEvent = firstFailedEvent(selectedRun);
    setSelectedSeq(initialEvent?.seq ?? null);
    setExpanded(allExpandable(buildTraceTree(selectedRun.events)));
  }, [selectedRun?.session.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const showColumn = React.useCallback(
    (column: LogColumn) => visibleColumns.includes(column),
    [visibleColumns],
  );

  const onSort = (key: LogSortKey) => {
    if (sortKey === key) setSortDirection((direction) => (direction === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDirection(key === "run" || key === "status" ? "asc" : "desc");
    }
  };

  const clearAllFilters = () => {
    setQuery("");
    setStatus("all");
    setFailedOnly(false);
    setSelectedEnvironments([]);
    setSelectedTags([]);
  };

  const traceDebuggerNode = selectedRun ? (
    <TraceDebugger
      run={selectedRun}
      traceTree={traceTree}
      visibleTrace={visibleTrace}
      expanded={expanded}
      onExpandedChange={setExpanded}
      selectedEvent={selectedEvent}
      onEventSelect={(event) => {
        setSelectedSeq(event.seq);
        setDetailTab("run");
      }}
      detailTab={detailTab}
      onDetailTabChange={setDetailTab}
      isExpanded={traceExpanded}
      onExpandToggle={() => setTraceExpanded((v) => !v)}
    />
  ) : (
    <div className="landing-framed-surface flex min-h-[320px] items-center justify-center p-6 text-sm text-muted-foreground">
      No runs match the current filters.
    </div>
  );

  return (
    <div className="flex min-h-0 gap-3">
      {/* Left rail: agent selector + filters + metrics */}
      <AgentFilterRail
        agentGroups={agentGroups}
        selectedAgentId={selectedAgentId}
        onAgentSelect={(id) => {
          setSelectedAgentId(id);
          setSelectedTags([]);
          setSelectedEnvironments([]);
        }}
        metrics={metrics}
        environments={environments}
        selectedEnvironments={selectedEnvironments}
        onEnvironmentToggle={(env) =>
          setSelectedEnvironments((values) => toggleValue(values, env))
        }
        tags={allTags}
        selectedTags={selectedTags}
        onTagToggle={(tag) => setSelectedTags((values) => toggleValue(values, tag))}
        onClearFilters={clearAllFilters}
      />

      {/* Center: filter bar + runs table + trace detail */}
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <LogFiltersBar
          query={query}
          onQueryChange={setQuery}
          status={status}
          onStatusChange={setStatus}
          failedOnly={failedOnly}
          onFailedOnlyChange={setFailedOnly}
          timeRange={timeRange}
          onTimeRangeChange={setTimeRange}
          visibleColumns={visibleColumns}
          onVisibleColumnsChange={setVisibleColumns}
          resultCount={filteredRuns.length}
          hasFilters={
            Boolean(query) ||
            status !== "all" ||
            failedOnly ||
            timeRange !== "7d" ||
            hasSidebarFilters
          }
          onClear={clearAllFilters}
        />

        <RunsTable
          runs={filteredRuns}
          selectedRunId={selectedRun?.session.id}
          showColumn={showColumn}
          sortKey={sortKey}
          sortDirection={sortDirection}
          onSort={onSort}
          onSelect={(run) => setSelectedRunId(run.session.id)}
        />

        {traceDebuggerNode}
      </div>

      {/* Expanded trace overlay */}
      {traceExpanded && selectedRun ? (
        <div
          className="fixed inset-0 z-50 flex flex-col bg-canvas/95 backdrop-blur-sm"
          role="dialog"
          aria-label="Expanded trace view"
          aria-modal="true"
        >
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4">
            <TraceDebugger
              run={selectedRun}
              traceTree={traceTree}
              visibleTrace={visibleTrace}
              expanded={expanded}
              onExpandedChange={setExpanded}
              selectedEvent={selectedEvent}
              onEventSelect={(event) => {
                setSelectedSeq(event.seq);
                setDetailTab("run");
              }}
              detailTab={detailTab}
              onDetailTabChange={setDetailTab}
              isExpanded={traceExpanded}
              onExpandToggle={() => setTraceExpanded(false)}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function LogFiltersBar({
  query,
  onQueryChange,
  status,
  onStatusChange,
  failedOnly,
  onFailedOnlyChange,
  timeRange,
  onTimeRangeChange,
  visibleColumns,
  onVisibleColumnsChange,
  resultCount,
  hasFilters,
  onClear,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  status: LogFilters["status"];
  onStatusChange: (value: LogFilters["status"]) => void;
  failedOnly: boolean;
  onFailedOnlyChange: (value: boolean) => void;
  timeRange: LogTimeRange;
  onTimeRangeChange: (value: LogTimeRange) => void;
  visibleColumns: LogColumn[];
  onVisibleColumnsChange: (columns: LogColumn[]) => void;
  resultCount: number;
  hasFilters: boolean;
  onClear: () => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="landing-framed-surface flex flex-col overflow-hidden lg:flex-row lg:items-stretch">
        <label className="relative min-w-0 flex-1 border-b border-border/50 transition-colors focus-within:bg-elevated/55 lg:border-b-0 lg:border-r">
          <span className="sr-only">Search logs</span>
          <Search className="absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Search runs, inputs, outputs, errors…"
            aria-label="Search logs"
            className="h-14 w-full bg-transparent pl-11 pr-12 text-[13px] text-foreground outline-none placeholder:text-muted-foreground/60"
          />
          {query ? (
            <button
              type="button"
              onClick={() => onQueryChange("")}
              aria-label="Clear search"
              className="absolute right-1 top-1/2 flex size-11 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="size-3.5" />
            </button>
          ) : null}
        </label>

        <div className="flex flex-wrap items-center gap-2 border-b border-border/50 p-2 lg:border-b-0 lg:border-r">
          {STATUS_FILTERS.map((filter) => {
            const active = status === filter.value;
            return (
              <button
                key={filter.value}
                type="button"
                aria-pressed={active}
                onClick={() => onStatusChange(filter.value)}
                className={cn(
                  "inline-flex min-h-8 items-center rounded-full px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                  active
                    ? "bg-accent/10 text-accent shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {filter.label}
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2 p-2">
          <Button
            type="button"
            variant={failedOnly ? "default" : "outline"}
            size="sm"
            aria-pressed={failedOnly}
            onClick={() => onFailedOnlyChange(!failedOnly)}
          >
            <ListFilter className="size-3.5" />
            Failed only
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <Timer className="size-3.5" />
                {TIME_RANGES.find((range) => range.value === timeRange)?.label}
                <ChevronDown className="size-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Time range</DropdownMenuLabel>
              {TIME_RANGES.map((range) => (
                <DropdownMenuCheckboxItem
                  key={range.value}
                  checked={timeRange === range.value}
                  onCheckedChange={() => onTimeRangeChange(range.value)}
                >
                  Last {range.label}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <ColumnMenu
            visibleColumns={visibleColumns}
            onVisibleColumnsChange={onVisibleColumnsChange}
          />

          <div className="ml-auto flex items-center gap-1.5">
            <span className="mono whitespace-nowrap text-[10px] text-muted-foreground">
              {resultCount} results
            </span>
            {hasFilters ? (
              <button
                type="button"
                onClick={onClear}
                aria-label="Clear all filters"
                title="Clear all filters"
                className="flex size-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <RotateCcw className="size-3.5" />
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function ColumnMenu({
  visibleColumns,
  onVisibleColumnsChange,
}: {
  visibleColumns: LogColumn[];
  onVisibleColumnsChange: (columns: LogColumn[]) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <Columns3 className="size-3.5" />
          Columns
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-[360px] overflow-auto">
        <DropdownMenuLabel>Visible columns</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {(Object.keys(COLUMN_LABELS) as LogColumn[]).map((column) => (
          <DropdownMenuCheckboxItem
            key={column}
            checked={visibleColumns.includes(column)}
            onCheckedChange={() => {
              if (visibleColumns.includes(column) && visibleColumns.length <= 3) return;
              onVisibleColumnsChange(toggleValue(visibleColumns, column) as LogColumn[]);
            }}
          >
            {COLUMN_LABELS[column]}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function AgentFilterRail({
  agentGroups,
  selectedAgentId,
  onAgentSelect,
  metrics,
  environments,
  selectedEnvironments,
  onEnvironmentToggle,
  tags,
  selectedTags,
  onTagToggle,
  onClearFilters,
}: {
  agentGroups: AgentGroup[];
  selectedAgentId: string | null;
  onAgentSelect: (id: string | null) => void;
  metrics: ReturnType<typeof deriveLogMetrics>;
  environments: string[];
  selectedEnvironments: string[];
  onEnvironmentToggle: (env: string) => void;
  tags: string[];
  selectedTags: string[];
  onTagToggle: (tag: string) => void;
  onClearFilters: () => void;
}) {
  return (
    <aside
      className="hidden w-56 shrink-0 flex-col gap-3 lg:flex"
      aria-label="Agent navigation and filters"
    >
      {/* Agent selector */}
      <nav className="landing-framed-surface overflow-hidden" aria-label="Agent list">
        <div className="border-b border-border/70 px-3 py-2.5">
          <h2 className="flex items-center gap-2 text-xs font-semibold text-foreground">
            <Bot className="size-3.5" />
            Agents
          </h2>
        </div>
        <ul className="p-1.5">
          <li>
            <button
              type="button"
              aria-pressed={selectedAgentId === null}
              onClick={() => onAgentSelect(null)}
              className={cn(
                "flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-[12px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                selectedAgentId === null
                  ? "bg-accent/10 font-medium text-accent"
                  : "text-muted-foreground hover:bg-elevated hover:text-foreground",
              )}
            >
              <span className="truncate">All agents</span>
              <span
                className={cn(
                  "mono ml-1.5 shrink-0 rounded-full px-2 py-0.5 text-[10px]",
                  selectedAgentId === null
                    ? "bg-accent/15 text-accent"
                    : "bg-elevated text-muted-foreground",
                )}
              >
                {agentGroups.reduce((s, g) => s + g.totalRuns, 0)}
              </span>
            </button>
          </li>
          {agentGroups.map((group) => (
            <li key={group.projectId}>
              <button
                type="button"
                aria-pressed={selectedAgentId === group.projectId}
                onClick={() => onAgentSelect(group.projectId)}
                className={cn(
                  "flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-[12px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  selectedAgentId === group.projectId
                    ? "bg-accent/10 font-medium text-accent"
                    : "text-muted-foreground hover:bg-elevated hover:text-foreground",
                )}
              >
                <span className="truncate">{group.label}</span>
                <span
                  className={cn(
                    "mono ml-1.5 shrink-0 rounded-full px-2 py-0.5 text-[10px]",
                    selectedAgentId === group.projectId
                      ? "bg-accent/15 text-accent"
                      : "bg-elevated text-muted-foreground",
                    group.failedRuns > 0 &&
                      selectedAgentId !== group.projectId &&
                      "bg-warning/10 text-warning",
                  )}
                >
                  {group.failedRuns > 0
                    ? `${group.failedRuns}/${group.totalRuns}`
                    : group.totalRuns}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {/* Filtered metrics */}
      <div className="landing-framed-surface overflow-hidden">
        <div className="flex items-center justify-between border-b border-border/70 px-3 py-2.5">
          <h2 className="text-xs font-semibold text-foreground">Filtered metrics</h2>
          <span className="text-[10px] text-muted-foreground">live</span>
        </div>
        <dl className="grid grid-cols-2 gap-px bg-border/50">
          <MetricTile label="Runs" value={String(metrics.totalRuns)} Icon={Activity} />
          <MetricTile label="Failures" value={String(metrics.failedRuns)} Icon={AlertCircle} />
          <MetricTile label="Error rate" value={pct(metrics.errorRate)} Icon={Gauge} />
          <MetricTile label="P50" value={fmtDuration(metrics.p50LatencyMs)} Icon={Timer} />
          <MetricTile label="P99" value={fmtDuration(metrics.p99LatencyMs)} Icon={Timer} />
          <MetricTile label="Tokens" value={numberFormat(metrics.totalTokens)} Icon={FileJson} />
        </dl>
      </div>

      {/* Filter shortcuts */}
      <div className="landing-framed-surface overflow-hidden">
        <div className="flex items-center justify-between border-b border-border/70 px-3 py-2.5">
          <h2 className="flex items-center gap-2 text-xs font-semibold text-foreground">
            <ListFilter className="size-3.5" />
            Filter shortcuts
          </h2>
          <button
            type="button"
            onClick={onClearFilters}
            className="text-[11px] text-accent transition-colors hover:text-accent-bright focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Clear
          </button>
        </div>
        <FilterGroup title="Environment">
          {environments.map((environment) => (
            <CheckFilter
              key={environment}
              label={environment}
              checked={selectedEnvironments.includes(environment)}
              onChange={() => onEnvironmentToggle(environment)}
            />
          ))}
        </FilterGroup>
        <FilterGroup title="Tags" icon={<Tags className="size-3" />}>
          {tags.map((tag) => (
            <CheckFilter
              key={tag}
              label={tag}
              checked={selectedTags.includes(tag)}
              onChange={() => onTagToggle(tag)}
            />
          ))}
        </FilterGroup>
      </div>
    </aside>
  );
}

function RunsTable({
  runs,
  selectedRunId,
  showColumn,
  sortKey,
  sortDirection,
  onSort,
  onSelect,
}: {
  runs: LogRun[];
  selectedRunId: string | undefined;
  showColumn: (column: LogColumn) => boolean;
  sortKey: LogSortKey;
  sortDirection: "asc" | "desc";
  onSort: (key: LogSortKey) => void;
  onSelect: (run: LogRun) => void;
}) {
  if (runs.length === 0) {
    return (
      <div className="landing-framed-surface flex min-h-[260px] items-center justify-center p-6 text-sm text-muted-foreground">
        No runs match the current filters.
      </div>
    );
  }

  return (
    <div className="landing-framed-surface max-h-[42dvh] min-h-[340px] overflow-auto">
      <Table>
        <TableHeader className="sticky top-0 z-10 bg-muted/35">
          <TableRow className="hover:bg-transparent">
            {showColumn("status") ? (
              <TableHead className="w-[96px]">Status</TableHead>
            ) : null}
            {showColumn("run") ? (
              <SortableHead
                label="Run"
                sortId="run"
                sortKey={sortKey}
                sortDirection={sortDirection}
                onSort={onSort}
                className="min-w-[230px]"
              />
            ) : null}
            {showColumn("input") ? (
              <TableHead className="hidden min-w-[260px] sm:table-cell">Input</TableHead>
            ) : null}
            {showColumn("output") ? (
              <TableHead className="hidden min-w-[220px] md:table-cell">Output</TableHead>
            ) : null}
            {showColumn("error") ? (
              <TableHead className="hidden min-w-[200px] lg:table-cell">Error</TableHead>
            ) : null}
            {showColumn("project") ? (
              <TableHead className="hidden w-[150px] xl:table-cell">Project</TableHead>
            ) : null}
            {showColumn("environment") ? (
              <TableHead className="hidden w-[110px] xl:table-cell">Env</TableHead>
            ) : null}
            {showColumn("start_time") ? (
              <SortableHead
                label="Start Time"
                sortId="start_time"
                sortKey={sortKey}
                sortDirection={sortDirection}
                onSort={onSort}
                className="hidden w-[142px] 2xl:table-cell"
              />
            ) : null}
            {showColumn("latency") ? (
              <SortableHead
                label="Latency"
                sortId="latency"
                sortKey={sortKey}
                sortDirection={sortDirection}
                onSort={onSort}
                className="hidden w-[100px] 2xl:table-cell"
              />
            ) : null}
            {showColumn("feedback") ? (
              <TableHead className="hidden w-[112px] 2xl:table-cell">Feedback</TableHead>
            ) : null}
            {showColumn("tokens") ? (
              <SortableHead
                label="Tokens"
                sortId="tokens"
                sortKey={sortKey}
                sortDirection={sortDirection}
                onSort={onSort}
                className="hidden w-[98px] 2xl:table-cell"
              />
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => {
            const selected = run.session.id === selectedRunId;
            const failed = ["failed", "error"].includes(run.session.status);
            return (
              <TableRow
                key={run.session.id}
                tabIndex={0}
                role="button"
                aria-label={`Inspect run ${run.session.id}`}
                aria-pressed={selected}
                onClick={() => onSelect(run)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(run);
                  }
                }}
                className={cn(
                  "cursor-pointer outline-none focus-visible:bg-elevated focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
                  selected && "bg-accent/[0.06] hover:bg-accent/[0.06]",
                  failed && !selected && "hover:bg-warning/[0.04]",
                )}
              >
                {showColumn("status") ? (
                  <TableCell className="py-2">
                    <StatusPill status={run.session.status} />
                  </TableCell>
                ) : null}
                {showColumn("run") ? (
                  <TableCell className="py-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">
                        {run.session.user_goal ?? run.session.id}
                      </p>
                      <p className="mono truncate text-[10px] text-muted-foreground">
                        {shortId(run.session.id, 14)}
                      </p>
                    </div>
                  </TableCell>
                ) : null}
                {showColumn("input") ? (
                  <PreviewCell value={run.inputPreview} className="hidden sm:table-cell" />
                ) : null}
                {showColumn("output") ? (
                  <PreviewCell value={run.outputPreview} className="hidden md:table-cell" />
                ) : null}
                {showColumn("error") ? (
                  <PreviewCell value={run.errorPreview} tone="error" className="hidden lg:table-cell" />
                ) : null}
                {showColumn("project") ? (
                  <TableCell className="hidden truncate py-2 text-muted-foreground xl:table-cell">
                    {run.project?.name ?? run.session.project_id}
                  </TableCell>
                ) : null}
                {showColumn("environment") ? (
                  <TableCell className="hidden py-2 xl:table-cell">
                    <span className="mono inline-flex items-center rounded-full bg-elevated px-2.5 py-1 text-[10px] text-muted-foreground">
                      {run.session.environment ?? "unknown"}
                    </span>
                  </TableCell>
                ) : null}
                {showColumn("start_time") ? (
                  <TableCell
                    className="mono hidden whitespace-nowrap py-2 text-xs text-muted-foreground 2xl:table-cell"
                    title={run.session.started_at}
                  >
                    {fmtRelative(run.session.started_at)}
                  </TableCell>
                ) : null}
                {showColumn("latency") ? (
                  <TableCell className="hidden py-2 2xl:table-cell">
                    <LatencyBadge ms={run.latencyMs} />
                  </TableCell>
                ) : null}
                {showColumn("feedback") ? (
                  <TableCell className="hidden py-2 2xl:table-cell">
                    <span className="mono text-xs text-muted-foreground">
                      {run.confidence !== null ? pct(run.confidence) : "none"}
                    </span>
                  </TableCell>
                ) : null}
                {showColumn("tokens") ? (
                  <TableCell className="mono hidden py-2 text-xs text-muted-foreground 2xl:table-cell">
                    {numberFormat(run.totalTokens)}
                  </TableCell>
                ) : null}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function SortableHead({
  label,
  sortId,
  sortKey,
  sortDirection,
  onSort,
  className,
}: {
  label: string;
  sortId: LogSortKey;
  sortKey: LogSortKey;
  sortDirection: "asc" | "desc";
  onSort: (key: LogSortKey) => void;
  className?: string;
}) {
  const active = sortId === sortKey;
  return (
    <TableHead
      className={className}
      aria-sort={active ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(sortId)}
        className="inline-flex items-center gap-1 text-left font-medium transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {label}
        <ChevronDown
          className={cn(
            "size-3 transition-transform",
            active && sortDirection === "asc" && "rotate-180",
          )}
        />
      </button>
    </TableHead>
  );
}

function PreviewCell({
  value,
  tone,
  className,
}: {
  value: string;
  tone?: "error";
  className?: string;
}) {
  return (
    <TableCell className={cn("py-2", className)}>
      {value ? (
        <span
          className={cn(
            "block truncate text-xs",
            tone === "error" ? "text-warning" : "text-muted-foreground",
          )}
          title={value}
        >
          {value}
        </span>
      ) : (
        <span className="text-muted-foreground/40">—</span>
      )}
    </TableCell>
  );
}

function LatencyBadge({ ms }: { ms: number }) {
  const slow = ms >= 12000;
  return (
    <span
      className={cn(
        "mono inline-flex rounded-full border px-2 py-0.5 text-[10px]",
        slow
          ? "border-warning/30 bg-warning/10 text-warning"
          : "border-success/30 bg-success/10 text-success",
      )}
    >
      {fmtDuration(ms)}
    </span>
  );
}

export function LogSessionTraceView({ run }: { run: LogRun }) {
  const [selectedSeq, setSelectedSeq] = React.useState<number | null>(() => {
    return firstFailedEvent(run)?.seq ?? null;
  });
  const [expanded, setExpanded] = React.useState<Set<string>>(() => {
    return allExpandable(buildTraceTree(run.events));
  });
  const [detailTab, setDetailTab] = React.useState<"run" | "feedback" | "metadata">("run");
  const [isExpanded, setIsExpanded] = React.useState(false);

  const traceTree = React.useMemo(() => buildTraceTree(run.events), [run.events]);
  const visibleTrace = React.useMemo(
    () => flattenTraceTree(traceTree, expanded),
    [expanded, traceTree],
  );
  const selectedEvent = React.useMemo(
    () => run.events.find((event) => event.seq === selectedSeq) ?? firstFailedEvent(run),
    [run, selectedSeq],
  );

  React.useEffect(() => {
    const initialEvent = firstFailedEvent(run);
    setSelectedSeq(initialEvent?.seq ?? null);
    setExpanded(allExpandable(buildTraceTree(run.events)));
    setDetailTab("run");
  }, [run, run.events]);

  return (
    <TraceDebugger
      run={run}
      traceTree={traceTree}
      visibleTrace={visibleTrace}
      expanded={expanded}
      onExpandedChange={setExpanded}
      selectedEvent={selectedEvent}
      onEventSelect={(event) => {
        setSelectedSeq(event.seq);
        setDetailTab("run");
      }}
      detailTab={detailTab}
      onDetailTabChange={setDetailTab}
      isExpanded={isExpanded}
      onExpandToggle={() => setIsExpanded((value) => !value)}
    />
  );
}

function TraceDebugger({
  run,
  traceTree,
  visibleTrace,
  expanded,
  onExpandedChange,
  selectedEvent,
  onEventSelect,
  detailTab,
  onDetailTabChange,
  isExpanded,
  onExpandToggle,
}: {
  run: LogRun;
  traceTree: TraceNode[];
  visibleTrace: Array<{ node: TraceNode; depth: number }>;
  expanded: Set<string>;
  onExpandedChange: (value: Set<string>) => void;
  selectedEvent: TraceEvent | undefined;
  onEventSelect: (event: TraceEvent) => void;
  detailTab: "run" | "feedback" | "metadata";
  onDetailTabChange: (tab: "run" | "feedback" | "metadata") => void;
  isExpanded: boolean;
  onExpandToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-1 gap-3 lg:grid-cols-[minmax(360px,0.95fr)_minmax(420px,1.05fr)]",
        isExpanded ? "h-full min-h-0 flex-1" : "min-h-[520px]",
      )}
    >
      <section
        className={cn(
          "instrument-panel flex flex-col overflow-hidden",
          isExpanded ? "min-h-0 flex-1" : "min-h-[520px]",
        )}
        aria-label="Trace waterfall"
      >
        <div className="instrument-header">
          <div>
            <p className="micro">Trace waterfall</p>
            <p className="mono mt-1 text-[10px] text-muted-foreground">
              {run.events.length} events · {traceTree.length} roots
            </p>
          </div>
          <div className="flex items-center gap-1">
            <Button variant="outline" size="sm" type="button">
              <Filter className="size-3" />
              Waterfall
            </Button>
            <button
              type="button"
              onClick={() => onExpandedChange(allExpandable(traceTree))}
              className="flex size-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Expand trace tree"
            >
              <PanelRight className="size-3.5" />
            </button>
            <button
              type="button"
              onClick={onExpandToggle}
              className="flex size-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={isExpanded ? "Collapse trace view" : "Expand trace to full view"}
              title={isExpanded ? "Collapse" : "Expand to full view"}
            >
              {isExpanded ? (
                <Minimize2 className="size-3.5" />
              ) : (
                <Expand className="size-3.5" />
              )}
            </button>
          </div>
        </div>
        <ol className="min-h-0 flex-1 overflow-auto py-1">
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
              <li key={node.id}>
                <div
                  className={cn(
                    "grid h-9 w-full grid-cols-[minmax(0,1fr)_auto] items-center border-l-2 pr-3 text-left text-xs transition-colors",
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
      </section>

      <RunInspector
        run={run}
        event={selectedEvent}
        tab={detailTab}
        onTabChange={onDetailTabChange}
        onEvidenceSelect={(seq) => {
          const match = run.events.find((candidate) => candidate.seq === seq);
          if (match) onEventSelect(match);
        }}
        isExpanded={isExpanded}
      />
    </div>
  );
}

function RunInspector({
  run,
  event,
  tab,
  onTabChange,
  onEvidenceSelect,
  isExpanded,
}: {
  run: LogRun;
  event: TraceEvent | undefined;
  tab: "run" | "feedback" | "metadata";
  onTabChange: (tab: "run" | "feedback" | "metadata") => void;
  onEvidenceSelect: (seq: number) => void;
  isExpanded?: boolean;
}) {
  const eventPayload = event?.payload ?? {};
  const eventMetadata = event?.metadata ?? null;

  return (
    <section
      className={cn(
        "instrument-panel flex flex-col overflow-hidden",
        isExpanded ? "min-h-0 flex-1" : "min-h-[520px]",
      )}
      aria-label="Run inspector"
    >
      <div className="instrument-header">
        <div className="min-w-0">
          <p className="micro">Run inspector</p>
          <h2 className="truncate text-sm font-semibold text-foreground">
            {event ? eventTitle(event) : (run.session.user_goal ?? run.session.id)}
          </h2>
          <p className="mono truncate text-[10px] text-muted-foreground">
            {run.session.id}
            {event ? ` · seq ${event.seq}` : ""}
          </p>
        </div>
        <span className="mono hidden rounded-full border border-border bg-elevated px-2.5 py-1 text-[10px] text-muted-foreground sm:inline">
          {costEstimate(run.totalTokens)}
        </span>
      </div>

      <Tabs
        value={tab}
        onValueChange={(value) => onTabChange(value as "run" | "feedback" | "metadata")}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="mx-3 mt-1 flex">
          <TabsTrigger value="run">Run</TabsTrigger>
          <TabsTrigger value="feedback">Feedback</TabsTrigger>
          <TabsTrigger value="metadata">Metadata</TabsTrigger>
        </TabsList>

        <div className="min-h-0 flex-1 overflow-auto px-4 pb-4">
          <TabsContent value="run" className="mt-3 space-y-4">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
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

          <TabsContent value="feedback" className="mt-3 space-y-4">
            <div className="grid grid-cols-2 gap-2">
              <Readout
                label="Confidence"
                value={run.confidence !== null ? pct(run.confidence) : "pending"}
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

          <TabsContent value="metadata" className="mt-3 space-y-4">
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
    </section>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-elevated px-3 py-2">
      <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className="mono mt-1 truncate text-xs text-foreground">{value}</dd>
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
    <details open={defaultOpen} className="group rounded-xl border border-border bg-panel/50">
      <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between px-3 text-xs font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {title}
        <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-border/70 p-3">{children}</div>
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
        "max-h-52 overflow-auto whitespace-pre-wrap rounded-xl border border-border bg-canvas p-3 text-xs leading-5",
        tone === "error" ? "text-warning" : "text-foreground/90",
      )}
    >
      {children}
    </pre>
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
    <div className="bg-panel px-3 py-2.5">
      <dt className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
        <Icon className="size-3" />
        {label}
      </dt>
      <dd className="mono mt-1 truncate text-sm text-foreground">{value}</dd>
    </div>
  );
}

function FilterGroup({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="border-b border-border/70 p-3 last:border-b-0">
      <p className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
        {icon}
        {title}
      </p>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function CheckFilter({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className="flex min-h-7 cursor-pointer items-center gap-2 rounded-lg px-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="size-3 rounded border-border accent-accent"
      />
      <span className="truncate">{label}</span>
    </label>
  );
}
