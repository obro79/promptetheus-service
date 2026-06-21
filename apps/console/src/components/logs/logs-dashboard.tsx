"use client";

import * as React from "react";
import Link from "next/link";
import {
  Activity,
  AlertCircle,
  BarChart3,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Columns3,
  Database,
  FileJson,
  Filter,
  Gauge,
  Home,
  ListFilter,
  ListTree,
  MessageSquare,
  MoreHorizontal,
  PanelRight,
  Search,
  Settings,
  Sparkles,
  Tags,
  Terminal,
  Timer,
  X,
  type LucideIcon,
} from "lucide-react";

import { JsonViewer } from "@/components/common/json-viewer";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
  eventSummary,
  eventTitle,
  filterLogRuns,
  flattenTraceTree,
  sortLogRuns,
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

const NAV_ITEMS: Array<{ label: string; href: string; Icon: LucideIcon; active?: boolean }> = [
  { label: "Home", href: "/", Icon: Home },
  { label: "Logs", href: "/logs", Icon: ListTree, active: true },
  { label: "Monitoring", href: "/incidents", Icon: BarChart3 },
  { label: "Datasets", href: "/sessions", Icon: Database },
  { label: "Prompts", href: "/agents", Icon: Sparkles },
  { label: "Settings", href: "/settings/projects", Icon: Settings },
];

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
  const allTags = React.useMemo(
    () => uniqueSorted(runs.flatMap((run) => run.session.tags)),
    [runs],
  );
  const environments = React.useMemo(
    () => uniqueSorted(runs.map((run) => run.session.environment)),
    [runs],
  );
  const [query, setQuery] = React.useState("");
  const [status, setStatus] = React.useState<LogFilters["status"]>("all");
  const [failedOnly, setFailedOnly] = React.useState(true);
  const [timeRange, setTimeRange] = React.useState<LogTimeRange>("7d");
  const [selectedProjects, setSelectedProjects] = React.useState<string[]>([]);
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

  const filters = React.useMemo<LogFilters>(
    () => ({
      query,
      status,
      failedOnly,
      timeRange,
      projects: selectedProjects,
      environments: selectedEnvironments,
      tags: selectedTags,
    }),
    [failedOnly, query, selectedEnvironments, selectedProjects, selectedTags, status, timeRange],
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

  return (
    <div className="min-h-dvh bg-[#07080c] text-[#e7eaf0]">
      <div className="flex min-h-dvh">
        <LogsSidebar />
        <main className="min-w-0 flex-1">
          <HeaderBar timeRange={timeRange} onTimeRangeChange={setTimeRange} />

          <div className="grid min-h-[calc(100dvh-56px)] grid-cols-1 xl:grid-cols-[minmax(0,1fr)_286px]">
            <section className="min-w-0 border-r border-[#222733]">
              <div className="border-b border-[#222733] px-4 py-3 lg:px-5">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                    <div className="relative min-w-[260px] flex-1 sm:max-w-[520px]">
                      <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-[#7d8596]" />
                      <input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="Search runs, inputs, outputs, errors..."
                        aria-label="Search logs"
                        className="h-9 w-full rounded-md border border-[#252b37] bg-[#0d1017] pl-9 pr-9 text-xs text-[#f4f6fa] outline-none placeholder:text-[#677083] focus:border-[#3d8bfd] focus:ring-2 focus:ring-[#3d8bfd]/20"
                      />
                      {query ? (
                        <button
                          type="button"
                          onClick={() => setQuery("")}
                          aria-label="Clear search"
                          className="absolute right-2 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded text-[#8b94a7] hover:bg-[#1b202b] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]"
                        >
                          <X className="size-3.5" />
                        </button>
                      ) : null}
                    </div>
                    <StatusSegment value={status} onChange={setStatus} />
                    <button
                      type="button"
                      aria-pressed={failedOnly}
                      onClick={() => setFailedOnly((value) => !value)}
                      className={cn(
                        "inline-flex h-9 items-center gap-2 rounded-md border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]",
                        failedOnly
                          ? "border-[#f97316]/40 bg-[#2a1710] text-[#fbbf24]"
                          : "border-[#252b37] bg-[#0d1017] text-[#aab2c3] hover:bg-[#151a24] hover:text-white",
                      )}
                    >
                      <ListFilter className="size-3.5" />
                      Failed only
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    <ColumnMenu
                      visibleColumns={visibleColumns}
                      onVisibleColumnsChange={setVisibleColumns}
                    />
                    <button
                      type="button"
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-[#252b37] bg-[#0d1017] px-3 text-xs font-medium text-[#aab2c3] hover:bg-[#151a24] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]"
                    >
                      <MoreHorizontal className="size-3.5" />
                    </button>
                  </div>
                </div>
              </div>

              <RunsTable
                runs={filteredRuns}
                selectedRunId={selectedRun?.session.id}
                showColumn={showColumn}
                sortKey={sortKey}
                sortDirection={sortDirection}
                onSort={onSort}
                onSelect={(run) => setSelectedRunId(run.session.id)}
              />

              {selectedRun ? (
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
                />
              ) : (
                <div className="flex min-h-[320px] items-center justify-center border-t border-[#222733] text-sm text-[#8b94a7]">
                  No runs match the current filters.
                </div>
              )}
            </section>

            <RightRail
              metrics={metrics}
              projects={projects}
              selectedProjects={selectedProjects}
              onProjectToggle={(projectId) => setSelectedProjects((values) => toggleValue(values, projectId))}
              environments={environments}
              selectedEnvironments={selectedEnvironments}
              onEnvironmentToggle={(environment) =>
                setSelectedEnvironments((values) => toggleValue(values, environment))
              }
              tags={allTags}
              selectedTags={selectedTags}
              onTagToggle={(tag) => setSelectedTags((values) => toggleValue(values, tag))}
              onClearFilters={() => {
                setQuery("");
                setStatus("all");
                setFailedOnly(false);
                setSelectedProjects([]);
                setSelectedEnvironments([]);
                setSelectedTags([]);
              }}
            />
          </div>
        </main>
      </div>
    </div>
  );
}

function LogsSidebar() {
  return (
    <aside className="relative hidden w-[216px] shrink-0 border-r border-[#222733] bg-[#0a0c12] lg:block">
      <div className="flex h-14 items-center gap-2 border-b border-[#222733] px-3">
        <div className="flex size-7 items-center justify-center rounded-md bg-[#f4f6fa] text-[11px] font-bold text-[#07080c]">
          P
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-white">Promptetheus</p>
          <p className="text-[10px] text-[#7d8596]">Observability</p>
        </div>
      </div>
      <nav className="space-y-5 px-2 py-3" aria-label="Logs navigation">
        <div className="space-y-1">
          {NAV_ITEMS.slice(0, 3).map((item) => (
            <SideLink key={item.href} {...item} />
          ))}
        </div>
        <div>
          <p className="px-2 pb-1 text-[10px] font-semibold uppercase text-[#677083]">
            Evaluation
          </p>
          <div className="space-y-1">
            {NAV_ITEMS.slice(3, 4).map((item) => (
              <SideLink key={item.href} {...item} />
            ))}
          </div>
        </div>
        <div>
          <p className="px-2 pb-1 text-[10px] font-semibold uppercase text-[#677083]">
            Prompt Engineering
          </p>
          <div className="space-y-1">
            {NAV_ITEMS.slice(4).map((item) => (
              <SideLink key={item.href} {...item} />
            ))}
          </div>
        </div>
      </nav>
      <div className="absolute bottom-0 left-0 right-0 hidden border-t border-[#222733] p-3 lg:block">
        <div className="flex items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-full bg-[#182133] text-[10px] font-semibold text-[#8ab4ff]">
            OF
          </span>
          <div className="min-w-0">
            <p className="truncate text-xs text-[#e7eaf0]">Owen Fisher</p>
            <p className="truncate text-[10px] text-[#7d8596]">Mock workspace</p>
          </div>
        </div>
      </div>
    </aside>
  );
}

function SideLink({
  label,
  href,
  Icon,
  active,
}: {
  label: string;
  href: string;
  Icon: LucideIcon;
  active?: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "flex min-h-8 items-center gap-2 rounded-md px-2 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]",
        active
          ? "bg-[#171c27] text-white"
          : "text-[#9aa3b5] hover:bg-[#121721] hover:text-white",
      )}
    >
      <Icon className="size-3.5" />
      {label}
    </Link>
  );
}

function HeaderBar({
  timeRange,
  onTimeRangeChange,
}: {
  timeRange: LogTimeRange;
  onTimeRangeChange: (value: LogTimeRange) => void;
}) {
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-[#222733] bg-[#090b11]/95 px-4 backdrop-blur lg:px-5">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 text-[11px] text-[#7d8596]">
          <span>Acme</span>
          <ChevronRight className="size-3" />
          <span>Observability</span>
          <ChevronRight className="size-3" />
          <span className="text-[#d8dde8]">Logs</span>
        </div>
        <h1 className="text-base font-semibold leading-tight text-white">
          Logs
        </h1>
      </div>
      <div className="flex items-center gap-2">
        <span className="hidden rounded-md border border-[#252b37] bg-[#0d1017] px-2 py-1 text-[11px] text-[#9aa3b5] sm:inline-flex">
          Retention 14d
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="inline-flex h-8 items-center gap-2 rounded-md border border-[#252b37] bg-[#0d1017] px-2.5 text-xs text-[#d8dde8] hover:bg-[#151a24] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]">
              <Timer className="size-3.5" />
              {TIME_RANGES.find((range) => range.value === timeRange)?.label}
              <ChevronDown className="size-3" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="border-[#252b37] bg-[#0d1017] text-[#d8dde8]">
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
        <button className="hidden h-8 items-center gap-2 rounded-md border border-[#252b37] bg-[#0d1017] px-2.5 text-xs text-[#d8dde8] hover:bg-[#151a24] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd] md:inline-flex">
          <BarChart3 className="size-3.5" />
          Dashboard
        </button>
      </div>
    </header>
  );
}

function StatusSegment({
  value,
  onChange,
}: {
  value: LogFilters["status"];
  onChange: (value: LogFilters["status"]) => void;
}) {
  return (
    <div className="inline-flex h-9 items-center rounded-md border border-[#252b37] bg-[#0d1017] p-0.5">
      {STATUS_FILTERS.map((filter) => (
        <button
          key={filter.value}
          type="button"
          aria-pressed={value === filter.value}
          onClick={() => onChange(filter.value)}
          className={cn(
            "h-7 rounded px-2 text-[11px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]",
            value === filter.value
              ? "bg-[#202735] text-white"
              : "text-[#8b94a7] hover:text-white",
          )}
        >
          {filter.label}
        </button>
      ))}
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
        <button className="inline-flex h-9 items-center gap-2 rounded-md border border-[#252b37] bg-[#0d1017] px-3 text-xs font-medium text-[#aab2c3] hover:bg-[#151a24] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]">
          <Columns3 className="size-3.5" />
          Columns
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-[360px] overflow-auto border-[#252b37] bg-[#0d1017] text-[#d8dde8]">
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
  return (
    <div className="h-[42dvh] min-h-[340px] overflow-auto border-b border-[#222733]">
      <table className="w-full min-w-full table-fixed border-collapse text-left text-xs sm:min-w-[640px] md:min-w-[940px] xl:min-w-[1180px]">
        <thead className="sticky top-0 z-10 bg-[#111722] text-[11px] text-[#aab2c3]">
          <tr className="border-b border-[#2a303c]">
            {showColumn("status") ? <ColumnHead label="Status" className="w-[92px]" /> : null}
            {showColumn("run") ? (
              <SortableHead label="Run" sortId="run" sortKey={sortKey} sortDirection={sortDirection} onSort={onSort} className="w-[230px]" />
            ) : null}
            {showColumn("input") ? <ColumnHead label="Input" className="hidden w-[300px] sm:table-cell md:w-[260px]" /> : null}
            {showColumn("output") ? <ColumnHead label="Output" className="hidden w-[260px] md:table-cell" /> : null}
            {showColumn("error") ? <ColumnHead label="Error" className="hidden w-[220px] lg:table-cell" /> : null}
            {showColumn("project") ? <ColumnHead label="Project" className="hidden w-[150px] xl:table-cell" /> : null}
            {showColumn("environment") ? <ColumnHead label="Env" className="hidden w-[110px] xl:table-cell" /> : null}
            {showColumn("start_time") ? (
              <SortableHead label="Start Time" sortId="start_time" sortKey={sortKey} sortDirection={sortDirection} onSort={onSort} className="hidden w-[142px] 2xl:table-cell" />
            ) : null}
            {showColumn("latency") ? (
              <SortableHead label="Latency" sortId="latency" sortKey={sortKey} sortDirection={sortDirection} onSort={onSort} className="hidden w-[100px] 2xl:table-cell" />
            ) : null}
            {showColumn("feedback") ? <ColumnHead label="Feedback" className="hidden w-[112px] 2xl:table-cell" /> : null}
            {showColumn("tokens") ? (
              <SortableHead label="Tokens" sortId="tokens" sortKey={sortKey} sortDirection={sortDirection} onSort={onSort} className="hidden w-[98px] 2xl:table-cell" />
            ) : null}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const selected = run.session.id === selectedRunId;
            return (
              <tr
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
                  "h-10 cursor-pointer border-b border-[#1c222d] outline-none transition-colors hover:bg-[#101722] focus-visible:bg-[#141c29] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#3d8bfd]",
                  selected && "bg-[#122033] hover:bg-[#122033]",
                )}
              >
                {showColumn("status") ? (
                  <td className="px-3 py-1.5">
                    <StatusBadge status={run.session.status} />
                  </td>
                ) : null}
                {showColumn("run") ? (
                  <td className="px-3 py-1.5">
                    <div className="min-w-0">
                      <p className="truncate font-medium text-[#f4f6fa]">
                        {run.session.user_goal ?? run.session.id}
                      </p>
                      <p className="mono truncate text-[10px] text-[#6f788b]">
                        {shortId(run.session.id, 14)}
                      </p>
                    </div>
                  </td>
                ) : null}
                {showColumn("input") ? <PreviewCell value={run.inputPreview} className="hidden sm:table-cell" /> : null}
                {showColumn("output") ? <PreviewCell value={run.outputPreview} className="hidden md:table-cell" /> : null}
                {showColumn("error") ? <PreviewCell value={run.errorPreview} tone="error" className="hidden lg:table-cell" /> : null}
                {showColumn("project") ? (
                  <td className="hidden truncate px-3 py-1.5 text-[#aab2c3] xl:table-cell">{run.project?.name ?? run.session.project_id}</td>
                ) : null}
                {showColumn("environment") ? (
                  <td className="hidden px-3 py-1.5 xl:table-cell">
                    <span className="mono rounded bg-[#151a24] px-1.5 py-1 text-[10px] text-[#aab2c3]">
                      {run.session.environment ?? "unknown"}
                    </span>
                  </td>
                ) : null}
                {showColumn("start_time") ? (
                  <td className="mono hidden whitespace-nowrap px-3 py-1.5 text-[11px] text-[#9aa3b5] 2xl:table-cell" title={run.session.started_at}>
                    {fmtRelative(run.session.started_at)}
                  </td>
                ) : null}
                {showColumn("latency") ? (
                  <td className="hidden px-3 py-1.5 2xl:table-cell">
                    <LatencyBadge ms={run.latencyMs} />
                  </td>
                ) : null}
                {showColumn("feedback") ? (
                  <td className="hidden px-3 py-1.5 2xl:table-cell">
                    <span className="mono text-[11px] text-[#aab2c3]">
                      {run.confidence !== null ? pct(run.confidence) : "none"}
                    </span>
                  </td>
                ) : null}
                {showColumn("tokens") ? (
                  <td className="mono hidden px-3 py-1.5 text-[11px] text-[#aab2c3] 2xl:table-cell">
                    {numberFormat(run.totalTokens)}
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
      {runs.length === 0 ? (
        <div className="flex h-full min-h-[260px] items-center justify-center text-sm text-[#8b94a7]">
          No runs match the current filters.
        </div>
      ) : null}
    </div>
  );
}

function ColumnHead({ label, className }: { label: string; className?: string }) {
  return (
    <th scope="col" className={cn("border-r border-[#252b37] px-3 py-2 font-medium", className)}>
      {label}
    </th>
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
    <th
      scope="col"
      aria-sort={active ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}
      className={cn("border-r border-[#252b37] px-0 py-0 font-medium", className)}
    >
      <button
        type="button"
        onClick={() => onSort(sortId)}
        className="flex h-8 w-full items-center gap-1 px-3 text-left hover:bg-[#192131] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#3d8bfd]"
      >
        {label}
        <ChevronDown className={cn("size-3 transition-transform", active && sortDirection === "asc" && "rotate-180")} />
      </button>
    </th>
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
    <td className={cn("px-3 py-1.5", className)}>
      {value ? (
        <span
          className={cn(
            "block truncate",
            tone === "error" ? "text-[#fca5a5]" : "text-[#aab2c3]",
          )}
          title={value}
        >
          {value}
        </span>
      ) : (
        <span className="text-[#4f586a]">-</span>
      )}
    </td>
  );
}

function StatusBadge({ status }: { status: TraceSession["status"] }) {
  const className =
    status === "passed"
      ? "border-[#22c55e]/30 bg-[#052e1a] text-[#86efac]"
      : status === "running"
        ? "border-[#60a5fa]/30 bg-[#0b2444] text-[#93c5fd]"
        : "border-[#ef4444]/35 bg-[#2a1014] text-[#fca5a5]";
  return (
    <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium uppercase", className)}>
      <span className="size-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

function LatencyBadge({ ms }: { ms: number }) {
  const className =
    ms >= 12000
      ? "border-[#f97316]/30 bg-[#2b170a] text-[#fdba74]"
      : "border-[#22c55e]/30 bg-[#052e1a] text-[#86efac]";
  return (
    <span className={cn("mono rounded border px-1.5 py-0.5 text-[10px]", className)}>
      {fmtDuration(ms)}
    </span>
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
}) {
  return (
    <section className="grid min-h-[520px] grid-cols-1 border-b border-[#222733] lg:grid-cols-[minmax(360px,0.95fr)_minmax(420px,1.05fr)]">
      <div className="min-w-0 border-r border-[#222733] bg-[#090b11]">
        <div className="flex h-11 items-center justify-between border-b border-[#222733] px-3">
          <div>
            <p className="text-[10px] font-semibold uppercase text-[#8b94a7]">Trace</p>
            <p className="mono text-[10px] text-[#626c7f]">
              {run.events.length} events · {traceTree.length} roots
            </p>
          </div>
          <div className="flex items-center gap-1">
            <button className="flex h-7 items-center gap-1 rounded border border-[#252b37] bg-[#0d1017] px-2 text-[11px] text-[#d8dde8]">
              <Filter className="size-3" />
              Waterfall
            </button>
            <button
              type="button"
              onClick={() => onExpandedChange(allExpandable(traceTree))}
              className="flex size-7 items-center justify-center rounded border border-[#252b37] bg-[#0d1017] text-[#9aa3b5] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]"
              aria-label="Expand trace tree"
            >
              <PanelRight className="size-3.5" />
            </button>
          </div>
        </div>
        <ol className="max-h-[520px] overflow-auto py-1" aria-label="Trace waterfall">
          {visibleTrace.map(({ node, depth }) => {
            const event = node.event;
            const selected = selectedEvent?.seq === event.seq;
            const Icon = EVENT_ICON[event.type] ?? FileJson;
            const hasChildren = node.children.length > 0;
            return (
              <li key={node.id}>
                <div
                  className={cn(
                    "grid h-9 w-full grid-cols-[minmax(0,1fr)_auto] items-center border-l-2 pr-3 text-left text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#3d8bfd]",
                    selected
                      ? "border-l-[#3d8bfd] bg-[#16324f] text-white"
                      : "border-l-transparent text-[#c5cad6] hover:bg-[#101722]",
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
                        className="flex size-4 items-center justify-center rounded hover:bg-[#222a38] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]"
                        aria-label={expanded.has(node.id) ? "Collapse trace node" : "Expand trace node"}
                      >
                        <ChevronRight className={cn("size-3 transition-transform", expanded.has(node.id) && "rotate-90")} />
                      </button>
                    ) : (
                      <span className="size-4" />
                    )}
                    <button
                      type="button"
                      onClick={() => onEventSelect(event)}
                      className="flex min-w-0 flex-1 items-center gap-2 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]"
                    >
                      <Icon className={cn("size-3.5 shrink-0", event.type === "error" ? "text-[#f87171]" : event.type === "llm_call" ? "text-[#f59e0b]" : "text-[#38bdf8]")} />
                      <span className="truncate">{eventTitle(event)}</span>
                      {event.type === "llm_call" ? (
                        <span className="hidden rounded border border-[#313949] px-1 text-[10px] text-[#9aa3b5] sm:inline">
                          {String((event.payload as Record<string, unknown>).model ?? "model")}
                        </span>
                      ) : null}
                    </button>
                  </span>
                  <span className="mono ml-2 shrink-0 rounded bg-[#141a25] px-1.5 py-0.5 text-[10px] text-[#9aa3b5]">
                    {fmtDuration(eventLatency(event))}
                  </span>
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      <RunInspector
        run={run}
        event={selectedEvent}
        tab={detailTab}
        onTabChange={onDetailTabChange}
        onEvidenceSelect={(seq) => {
          const event = run.events.find((candidate) => candidate.seq === seq);
          if (event) onEventSelect(event);
        }}
      />
    </section>
  );
}

function RunInspector({
  run,
  event,
  tab,
  onTabChange,
  onEvidenceSelect,
}: {
  run: LogRun;
  event: TraceEvent | undefined;
  tab: "run" | "feedback" | "metadata";
  onTabChange: (tab: "run" | "feedback" | "metadata") => void;
  onEvidenceSelect: (seq: number) => void;
}) {
  const eventPayload = event?.payload ?? {};
  const eventMetadata = event?.metadata ?? null;
  return (
    <div className="min-w-0 bg-[#0b0d12]">
      <div className="flex h-14 items-center justify-between border-b border-[#222733] px-4">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-[#1d4ed8] text-white">
            <Activity className="size-4" />
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-white">
              {event ? eventTitle(event) : run.session.user_goal ?? run.session.id}
            </h2>
            <p className="mono truncate text-[10px] text-[#7d8596]">
              {run.session.id}
              {event ? ` · seq ${event.seq}` : ""}
            </p>
          </div>
        </div>
        <span className="mono hidden rounded border border-[#2b3240] px-2 py-1 text-[10px] text-[#9aa3b5] sm:inline">
          {costEstimate(run.totalTokens)}
        </span>
      </div>
      <div className="flex h-10 items-end gap-5 border-b border-[#222733] px-4">
        {(["run", "feedback", "metadata"] as const).map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => onTabChange(item)}
            className={cn(
              "h-10 border-b-2 text-xs font-medium capitalize focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]",
              tab === item
                ? "border-b-[#d8dde8] text-white"
                : "border-b-transparent text-[#8b94a7] hover:text-white",
            )}
          >
            {item}
          </button>
        ))}
      </div>
      <div className="max-h-[496px] overflow-auto p-4">
        {tab === "run" ? (
          <div className="space-y-4">
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
              <JsonViewer
                data={eventPayload}
                collapseDepth={2}
                className="border-[#252b37] bg-[#07080c] text-[#d8dde8]"
              />
            </InspectorSection>
          </div>
        ) : null}

        {tab === "feedback" ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2">
              <Readout label="Confidence" value={run.confidence !== null ? pct(run.confidence) : "pending"} />
              <Readout label="Signals" value={String(run.feedbackCount)} />
            </div>
            <InspectorSection title="Root cause" defaultOpen>
              <p className="text-sm leading-6 text-[#d8dde8]">
                {run.analysis?.root_cause ?? "No analysis result has been attached."}
              </p>
            </InspectorSection>
            <InspectorSection title="Labels" defaultOpen>
              <div className="flex flex-wrap gap-1.5">
                {(run.analysis?.labels ?? run.session.tags).map((label) => (
                  <span key={label} className="rounded border border-[#2f3746] bg-[#111722] px-2 py-1 text-[11px] text-[#c5cad6]">
                    {label.replaceAll("_", " ")}
                  </span>
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
                      className="mono rounded border border-[#2f3746] bg-[#111722] px-2 py-1 text-[11px] text-[#9ec5ff] hover:bg-[#17233a] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]"
                    >
                      seq {seq}
                    </button>
                  ))
                ) : (
                  <span className="text-sm text-[#8b94a7]">No evidence refs attached.</span>
                )}
              </div>
            </InspectorSection>
          </div>
        ) : null}

        {tab === "metadata" ? (
          <div className="space-y-4">
            <InspectorSection title="Run metadata" defaultOpen>
              <JsonViewer
                data={{
                  session: run.session,
                  project: run.project,
                  incident: run.incident,
                  analysis: run.analysis,
                }}
                collapseDepth={2}
                className="border-[#252b37] bg-[#07080c] text-[#d8dde8]"
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
                className="border-[#252b37] bg-[#07080c] text-[#d8dde8]"
              />
            </InspectorSection>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[#252b37] bg-[#0d1017] px-3 py-2">
      <dt className="text-[10px] uppercase text-[#7d8596]">{label}</dt>
      <dd className="mono mt-1 truncate text-xs text-[#f4f6fa]">{value}</dd>
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
    <details open={defaultOpen} className="group rounded-md border border-[#252b37] bg-[#0d1017]">
      <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between px-3 text-xs font-medium text-[#d8dde8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]">
        {title}
        <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-[#252b37] p-3">{children}</div>
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
        "max-h-52 overflow-auto whitespace-pre-wrap rounded border border-[#252b37] bg-[#07080c] p-3 text-xs leading-5",
        tone === "error" ? "text-[#fca5a5]" : "text-[#d8dde8]",
      )}
    >
      {children}
    </pre>
  );
}

function RightRail({
  metrics,
  projects,
  selectedProjects,
  onProjectToggle,
  environments,
  selectedEnvironments,
  onEnvironmentToggle,
  tags,
  selectedTags,
  onTagToggle,
  onClearFilters,
}: {
  metrics: ReturnType<typeof deriveLogMetrics>;
  projects: Project[];
  selectedProjects: string[];
  onProjectToggle: (projectId: string) => void;
  environments: string[];
  selectedEnvironments: string[];
  onEnvironmentToggle: (environment: string) => void;
  tags: string[];
  selectedTags: string[];
  onTagToggle: (tag: string) => void;
  onClearFilters: () => void;
}) {
  return (
    <aside className="border-t border-[#222733] bg-[#090b11] xl:border-t-0">
      <div className="sticky top-14 space-y-4 p-4">
        <section className="rounded-md border border-[#252b37] bg-[#0d1017]">
          <div className="flex items-center justify-between border-b border-[#252b37] px-3 py-2">
            <h2 className="text-xs font-semibold text-white">Metrics</h2>
            <span className="text-[10px] text-[#7d8596]">mock</span>
          </div>
          <div className="grid grid-cols-2 gap-px bg-[#252b37]">
            <MetricTile label="Runs" value={String(metrics.totalRuns)} Icon={Activity} />
            <MetricTile label="Failures" value={String(metrics.failedRuns)} Icon={AlertCircle} />
            <MetricTile label="Error rate" value={pct(metrics.errorRate)} Icon={Gauge} />
            <MetricTile label="P50" value={fmtDuration(metrics.p50LatencyMs)} Icon={Timer} />
            <MetricTile label="P99" value={fmtDuration(metrics.p99LatencyMs)} Icon={Timer} />
            <MetricTile label="Tokens" value={numberFormat(metrics.totalTokens)} Icon={FileJson} />
          </div>
        </section>

        <section className="rounded-md border border-[#252b37] bg-[#0d1017]">
          <div className="flex items-center justify-between border-b border-[#252b37] px-3 py-2">
            <h2 className="flex items-center gap-2 text-xs font-semibold text-white">
              <ListFilter className="size-3.5" />
              Filter Shortcuts
            </h2>
            <button
              type="button"
              onClick={onClearFilters}
              className="text-[11px] text-[#8ab4ff] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3d8bfd]"
            >
              Clear
            </button>
          </div>
          <FilterGroup title="Projects">
            {projects.map((project) => (
              <CheckFilter
                key={project.id}
                label={project.name}
                checked={selectedProjects.includes(project.id)}
                onChange={() => onProjectToggle(project.id)}
              />
            ))}
          </FilterGroup>
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
        </section>
      </div>
    </aside>
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
    <div className="bg-[#0d1017] p-3">
      <dt className="flex items-center gap-1.5 text-[10px] text-[#7d8596]">
        <Icon className="size-3" />
        {label}
      </dt>
      <dd className="mono mt-1 truncate text-sm text-[#f4f6fa]">{value}</dd>
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
    <div className="border-b border-[#252b37] p-3 last:border-b-0">
      <p className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-[#aab2c3]">
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
    <label className="flex min-h-7 cursor-pointer items-center gap-2 rounded px-1.5 text-[11px] text-[#9aa3b5] hover:bg-[#151a24] hover:text-white">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="size-3 rounded border-[#3a4252] bg-[#090b11] accent-[#3d8bfd]"
      />
      <span className="truncate">{label}</span>
    </label>
  );
}
