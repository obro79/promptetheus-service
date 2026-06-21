"use client";

import * as React from "react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Bot,
  Bug,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Clock,
  Columns3,
  ExternalLink,
  Eye,
  FileJson,
  Filter,
  FlaskConical,
  Gauge,
  GitMerge,
  GitPullRequest,
  ListFilter,
  Loader2,
  MessageSquare,
  PanelRight,
  PlayCircle,
  Power,
  RefreshCw,
  RotateCcw,
  ScrollText,
  Search,
  Settings2,
  Sparkles,
  Tags,
  Terminal,
  Timer,
  Trash2,
  Waypoints,
  X,
  type LucideIcon,
} from "lucide-react";

import Link from "next/link";

import {
  ClaudeMark,
  DevinMark,
} from "@/components/common/brand-marks";
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
import { createClosedLogsTestPr, dispatchLogsAgentPrs } from "@/lib/promptetheus-api";
import { cn, fmtDuration, fmtRelative, pct, shortId } from "@/lib/utils";
import { buildAgents, type AgentRow } from "./agents-model";
import { FixDispatchDag } from "./fix-dispatch-dag";
import {
  DEFAULT_COLUMNS,
  buildLogRuns,
  buildTraceTree,
  deriveLogMetrics,
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

type InspectorTab = "run" | "feedback" | "fix" | "metadata";

interface LogsDashboardProps {
  sessions: TraceSession[];
  projects: Project[];
  incidents: Incident[];
  eventsBySession: Record<string, TraceEvent[]>;
  analysesBySession: Record<string, AnalysisResult | undefined>;
}

type LogSection =
  | "agents"
  | "runs"
  | "evaluations"
  | "logs"
  | "actions"
  | "settings";

const NAV_ITEMS: Array<{
  value: LogSection;
  label: string;
  Icon: LucideIcon;
}> = [
  { value: "agents", label: "Agents", Icon: Bot },
  { value: "runs", label: "Runs / Traces", Icon: Waypoints },
  { value: "evaluations", label: "Evaluations", Icon: FlaskConical },
  { value: "logs", label: "Logs", Icon: ScrollText },
  { value: "actions", label: "Actions", Icon: GitPullRequest },
  { value: "settings", label: "Settings", Icon: Settings2 },
];

/** Flat shadcn / Codex-style surface language shared across every panel:
 *  crisp 1px border, small radius, solid panel fill — no glass blur or large
 *  radii. */
const SURFACE = "rounded-lg border border-border/70 bg-panel";
const PANEL_HEADER =
  "flex min-h-11 items-center justify-between gap-2 border-b border-border/60 px-3.5 py-2";

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

function fmtMoney(value: number): string {
  if (!value) return "$0.00";
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
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
  const [section, setSection] = React.useState<LogSection>("runs");
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
  const [detailTab, setDetailTab] = React.useState<InspectorTab>("run");
  const [testPrState, setTestPrState] = React.useState<{
    status: "idle" | "running" | "closed" | "error";
    error: string | null;
    result: Awaited<ReturnType<typeof createClosedLogsTestPr>> | null;
  }>({ error: null, result: null, status: "idle" });

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
  const agents = React.useMemo(() => buildAgents(runs), [runs]);
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
    selectedProjects.length > 0 ||
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
    setSelectedProjects([]);
    setSelectedEnvironments([]);
    setSelectedTags([]);
  };

  const openRun = (run: LogRun) => {
    setSelectedRunId(run.session.id);
    setSection("runs");
  };

  const dispatchAgentPrs = React.useCallback(
    (_incidentId: string, run: LogRun) =>
      dispatchLogsAgentPrs({
        agentName: run.session.agent,
        incidentId: run.incident?.id ?? _incidentId,
        incidentTitle: run.incident?.title ?? null,
        rootCause: run.analysis?.root_cause ?? run.incident?.root_cause ?? null,
        sessionId: run.session.id,
      }),
    [],
  );

  React.useEffect(() => {
    setTestPrState({ error: null, result: null, status: "idle" });
  }, [selectedRun?.session.id]);

  const runClosedTestPr = React.useCallback(async () => {
    if (!selectedRun?.incident || testPrState.status === "running") return;

    setTestPrState({ error: null, result: null, status: "running" });
    try {
      const result = await createClosedLogsTestPr({
        agentName: selectedRun.session.agent,
        incidentId: selectedRun.incident.id,
        incidentTitle: selectedRun.incident.title,
        rootCause: selectedRun.analysis?.root_cause ?? selectedRun.incident.root_cause,
        sessionId: selectedRun.session.id,
      });
      setTestPrState({ error: null, result, status: "closed" });
    } catch (caught) {
      setTestPrState({
        error: caught instanceof Error ? caught.message : "Unable to create and close test PR.",
        result: null,
        status: "error",
      });
    }
  }, [selectedRun, testPrState.status]);

  return (
    <div className="logs-refined flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-7">
      <LogsNav active={section} onChange={setSection} />

      <div className="min-w-0 flex-1">
        {section === "runs" ? (
          <div className="flex flex-col gap-5">
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

            <div className="flex min-w-0 flex-col gap-5">
              {/* The pipeline runs full width to the edge of the pane. */}
              {selectedRun ? (
                <>
                  <TestPullRequestPanel
                    disabled={!selectedRun.incident}
                    onRun={runClosedTestPr}
                    state={testPrState}
                  />
                  <FixDispatchDag
                    dispatchHeal={dispatchAgentPrs}
                    dispatchLabel="Dispatch agent PRs"
                    prominent
                    run={selectedRun}
                  />
                </>
              ) : null}

              {/* Filtered metrics + filter shortcuts sit under the pipeline as a
                  compact strip so the pipeline above can use the full width. */}
              <FilterRail
                horizontal
                metrics={metrics}
                projects={projects}
                selectedProjects={selectedProjects}
                onProjectToggle={(projectId) =>
                  setSelectedProjects((values) => toggleValue(values, projectId))
                }
                environments={environments}
                selectedEnvironments={selectedEnvironments}
                onEnvironmentToggle={(environment) =>
                  setSelectedEnvironments((values) => toggleValue(values, environment))
                }
                tags={allTags}
                selectedTags={selectedTags}
                onTagToggle={(tag) => setSelectedTags((values) => toggleValue(values, tag))}
                onClearFilters={clearAllFilters}
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
                <div className={cn("flex min-h-[320px] items-center justify-center p-6 text-sm text-muted-foreground", SURFACE)}>
                  No runs match the current filters.
                </div>
              )}
            </div>
          </div>
        ) : section === "agents" ? (
          <AgentsPanel agents={agents} onOpenRun={openRun} />
        ) : section === "logs" ? (
          <LogsPanel
            query={query}
            onQueryChange={setQuery}
            status={status}
            onStatusChange={setStatus}
            runs={filteredRuns}
            onOpenRun={openRun}
          />
        ) : section === "evaluations" ? (
          <EvaluationsPanel agents={agents} runs={runs} />
        ) : section === "actions" ? (
          <ActionsPanel incidents={incidents} onOpenRun={openRun} />
        ) : (
          <SettingsPanel agents={agents} />
        )}
      </div>
    </div>
  );
}

function LogsNav({
  active,
  onChange,
}: {
  active: LogSection;
  onChange: (section: LogSection) => void;
}) {
  return (
    <nav
      aria-label="Logs sections"
      className="flex shrink-0 gap-1 overflow-x-auto pb-1 lg:sticky lg:top-24 lg:w-[196px] lg:flex-col lg:gap-0.5 lg:overflow-visible lg:border-r lg:border-border/60 lg:pb-0 lg:pr-3"
    >
      {NAV_ITEMS.map((item) => {
        const isActive = item.value === active;
        const Icon = item.Icon;
        return (
          <button
            key={item.value}
            type="button"
            onClick={() => onChange(item.value)}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "group flex min-h-9 shrink-0 items-center gap-2.5 rounded-md px-2.5 text-left text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
              isActive
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
            )}
          >
            <Icon
              className={cn(
                "size-4 shrink-0 transition-colors",
                isActive ? "text-foreground" : "text-muted-foreground/70 group-hover:text-foreground",
              )}
              strokeWidth={1.8}
            />
            <span className="truncate">{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

function TestPullRequestPanel({
  disabled,
  onRun,
  state,
}: {
  disabled: boolean;
  onRun: () => void;
  state: {
    status: "idle" | "running" | "closed" | "error";
    error: string | null;
    result: Awaited<ReturnType<typeof createClosedLogsTestPr>> | null;
  };
}) {
  return (
    <section className={cn("flex flex-wrap items-center justify-between gap-3 p-3", SURFACE)}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex size-8 items-center justify-center rounded-lg border border-accent/25 bg-accent-muted text-accent">
            <GitPullRequest className="size-3.5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-foreground">GitHub smoke test</h2>
            <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
              Create a disposable PR in obro79/demo-agents, then close it immediately.
            </p>
          </div>
        </div>
        {state.status === "closed" && state.result ? (
          <a
            href={state.result.url}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-flex max-w-full items-center gap-1 truncate text-xs font-medium text-success underline-offset-4 hover:underline"
          >
            <span className="truncate">
              Closed PR #{state.result.number}: {state.result.title}
            </span>
            <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
          </a>
        ) : state.status === "error" ? (
          <p className="mt-2 text-xs text-destructive">{state.error}</p>
        ) : null}
      </div>

      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || state.status === "running"}
        onClick={onRun}
        aria-label="Create and close test PR"
      >
        {state.status === "running" ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <GitPullRequest className="size-3.5" aria-hidden="true" />
        )}
        {state.status === "running" ? "Testing..." : "Test PR"}
      </Button>
    </section>
  );
}

// ─── Agents (default view) ────────────────────────────────────────────────────

/** Shared grid template so the column header and each row align exactly. */
const AGENT_GRID =
  "md:grid md:grid-cols-[minmax(0,1fr)_104px_124px_104px_84px_80px_72px_24px] md:items-center md:gap-4";

function AgentsPanel({
  agents,
  onOpenRun,
}: {
  agents: AgentRow[];
  onOpenRun: (run: LogRun) => void;
}) {
  const [expandedId, setExpandedId] = React.useState<string | null>(agents[0]?.id ?? null);
  const totalRuns = agents.reduce((sum, agent) => sum + agent.runCount, 0);

  if (agents.length === 0) {
    return (
      <EmptyPanel
        Icon={Bot}
        title="No agents yet"
        description="Once you instrument an agent and start sending traces, each agent and version will appear here with live health stats."
      />
    );
  }

  return (
    <section className={cn("overflow-hidden", SURFACE)}>
      <header className="flex items-center justify-between gap-3 px-4 py-3.5">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Agents</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {agents.length} agents · {totalRuns} runs
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="size-1.5 rounded-full bg-success" />
          live
        </span>
      </header>

      <div
        className={cn(
          "hidden border-t border-border/60 bg-muted/30 px-4 py-2 text-[11px] font-medium text-muted-foreground",
          AGENT_GRID,
        )}
      >
        <span>Agent</span>
        <span>Status</span>
        <span>Last run</span>
        <span className="text-right">Avg latency</span>
        <span className="text-right">Success</span>
        <span className="text-right">Cost</span>
        <span className="text-right">Version</span>
        <span />
      </div>

      <ul className="divide-y divide-border/60 border-t border-border/60">
        {agents.map((agent) => (
          <AgentListItem
            key={agent.id}
            agent={agent}
            expanded={agent.id === expandedId}
            onToggle={() =>
              setExpandedId((current) => (current === agent.id ? null : agent.id))
            }
            onOpenRun={onOpenRun}
          />
        ))}
      </ul>
    </section>
  );
}

function AgentListItem({
  agent,
  expanded,
  onToggle,
  onOpenRun,
}: {
  agent: AgentRow;
  expanded: boolean;
  onToggle: () => void;
  onOpenRun: (run: LogRun) => void;
}) {
  const lowSuccess = agent.successRate < 0.9;
  return (
    <li className={cn(expanded && "bg-elevated/30")}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className={cn(
          "w-full px-5 py-3.5 text-left transition-colors hover:bg-elevated/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/50",
          AGENT_GRID,
        )}
      >
        {/* Name */}
        <span className="flex min-w-0 items-center gap-3">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border/60 bg-muted text-muted-foreground">
            <Bot className="size-4" strokeWidth={1.8} />
          </span>
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium text-foreground">
              {agent.name}
            </span>
            <span className="block truncate text-[11px] text-muted-foreground">
              {agent.runCount} runs · {agent.failedCount} failed
            </span>
          </span>
        </span>

        {/* Mobile stat strip */}
        <span className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground md:hidden">
          <StatusPill status={agent.status} />
          <span className="mono">{fmtDuration(agent.avgLatencyMs)}</span>
          <span className={cn("mono", lowSuccess && "text-warning")}>{pct(agent.successRate)}</span>
          <span className="mono">{fmtMoney(agent.totalCost)}</span>
          <span className="mono">v{agent.version}</span>
        </span>

        {/* Desktop columns */}
        <span className="hidden md:block">
          <StatusPill status={agent.status} />
        </span>
        <span className="mono hidden text-[12px] text-muted-foreground md:block">
          {fmtRelative(agent.lastRunAt)}
        </span>
        <span className="mono hidden text-right text-[12px] tabular-nums text-foreground md:block">
          {fmtDuration(agent.avgLatencyMs)}
        </span>
        <span
          className={cn(
            "mono hidden text-right text-[12px] tabular-nums md:block",
            lowSuccess ? "text-warning" : "text-success",
          )}
        >
          {pct(agent.successRate)}
        </span>
        <span className="mono hidden text-right text-[12px] tabular-nums text-muted-foreground md:block">
          {fmtMoney(agent.totalCost)}
        </span>
        <span className="hidden justify-end md:flex">
          <span className="mono rounded-md bg-elevated px-1.5 py-0.5 text-[10px] text-muted-foreground">
            v{agent.version}
          </span>
        </span>
        <span className="hidden justify-end md:flex">
          <ChevronRight
            className={cn(
              "size-4 text-muted-foreground/55 transition-transform",
              expanded && "rotate-90",
            )}
          />
        </span>
      </button>

      {expanded ? <AgentDrawer agent={agent} onOpenRun={onOpenRun} /> : null}
    </li>
  );
}

/** Inline, non-modal drawer that visually nests under the agent row. */
function AgentDrawer({
  agent,
  onOpenRun,
}: {
  agent: AgentRow;
  onOpenRun: (run: LogRun) => void;
}) {
  const latest = agent.runs[0];
  const failed = agent.runs.find((run) => Boolean(run.errorPreview)) ?? undefined;
  const recent = agent.runs.slice(0, 5);
  const previewEvents = (latest?.events ?? []).slice(0, 6);

  return (
    <div className="relative px-3 pb-4 pl-5 md:pl-16">
      {/* Branch connector: stem drops from the agent icon, elbows into the card. */}
      <span
        aria-hidden
        className="pointer-events-none absolute left-[36px] top-0 hidden h-[26px] w-[28px] rounded-bl-[11px] border-b border-l border-border-strong/45 md:block"
      />
      <div className="relative rounded-md border border-border/60 bg-muted/30 p-4">
        <div className="grid gap-5 lg:grid-cols-[1.05fr_0.95fr]">
          {/* Left: overview + recent runs */}
          <div className="flex flex-col gap-4">
            <div>
              <SectionLabel>Overview</SectionLabel>
              <dl className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                <AgentStat label="Runs" value={String(agent.runCount)} />
                <AgentStat
                  label="Success"
                  value={pct(agent.successRate)}
                  tone={agent.successRate < 0.9 ? "warning" : undefined}
                />
                <AgentStat label="Avg latency" value={fmtDuration(agent.avgLatencyMs)} />
                <AgentStat label="Failures" value={String(agent.failedCount)} />
                <AgentStat label="Tokens" value={numberFormat(agent.totalTokens)} />
                <AgentStat label="Cost" value={fmtMoney(agent.totalCost)} />
              </dl>
            </div>

            <div>
              <SectionLabel>Recent runs</SectionLabel>
              <ul className="mt-2 overflow-hidden rounded-md border border-border/60 bg-panel">
                {recent.map((run) => (
                  <li key={run.session.id}>
                    <button
                      type="button"
                      onClick={() => onOpenRun(run)}
                      className="flex w-full items-center gap-3 border-b border-border/50 px-3 py-2 text-left transition-colors last:border-b-0 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/50"
                    >
                      <StatusPill status={run.session.status} />
                      <span className="block min-w-0 flex-1 truncate text-[13px] text-foreground">
                        {run.session.user_goal ?? run.session.id}
                      </span>
                      <span className="mono hidden shrink-0 text-[11px] text-muted-foreground sm:block">
                        {fmtDuration(run.latencyMs)}
                      </span>
                      <span className="mono hidden shrink-0 text-[11px] text-muted-foreground md:block">
                        {fmtRelative(run.session.started_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Right: trace preview + error + actions */}
          <div className="flex flex-col gap-4">
            <div>
              <SectionLabel>Latest trace</SectionLabel>
              <ol className="mt-2 space-y-0.5 rounded-md border border-border/60 bg-panel p-2">
                {previewEvents.length === 0 ? (
                  <li className="px-2 py-3 text-[12px] text-muted-foreground">
                    No trace events recorded.
                  </li>
                ) : (
                  previewEvents.map((event) => {
                    const Icon = EVENT_ICON[event.type] ?? FileJson;
                    const isError =
                      event.type === "error" ||
                      (event.type === "goal_check" &&
                        (event.payload as { passed?: boolean }).passed === false);
                    return (
                      <li
                        key={event.seq}
                        className="flex items-center gap-2.5 rounded-md px-2 py-1.5"
                      >
                        <Icon
                          className={cn(
                            "size-3.5 shrink-0",
                            isError
                              ? "text-warning"
                              : event.type === "llm_call"
                                ? "text-accent"
                                : "text-muted-foreground",
                          )}
                          strokeWidth={1.8}
                        />
                        <span className="min-w-0 flex-1 truncate text-[12px] text-foreground">
                          {eventTitle(event)}
                        </span>
                        <span className="mono shrink-0 text-[10px] text-muted-foreground">
                          {fmtDuration(eventLatency(event))}
                        </span>
                      </li>
                    );
                  })
                )}
              </ol>
            </div>

            {failed?.errorPreview ? (
              <div>
                <SectionLabel>Error preview</SectionLabel>
                <div className="mt-2 flex items-start gap-2 rounded-md border border-warning/25 bg-warning/[0.06] p-3">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" strokeWidth={1.8} />
                  <p className="mono min-w-0 text-[11px] leading-5 text-warning/90 line-clamp-3">
                    {failed.errorPreview}
                  </p>
                </div>
              </div>
            ) : null}

            <div className="mt-auto flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                onClick={() => latest && onOpenRun(latest)}
                disabled={!latest}
              >
                <Eye className="size-3.5" />
                View full trace
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => latest && onOpenRun(latest)}
                disabled={!latest}
              >
                <PlayCircle className="size-3.5" />
                Replay run
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => onOpenRun(failed ?? latest)}
                disabled={!latest}
              >
                <Bug className="size-3.5" />
                Debug
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
      {children}
    </p>
  );
}

function AgentStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "warning";
}) {
  return (
    <div className="rounded-md border border-border/60 bg-panel px-3 py-2.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "mt-1 text-lg font-semibold tabular-nums text-foreground",
          tone === "warning" && "text-warning",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

// ─── Evaluations (charts) ─────────────────────────────────────────────────────

function EvaluationsPanel({
  agents,
  runs,
}: {
  agents: AgentRow[];
  runs: LogRun[];
}) {
  const passed = runs.filter((run) => run.session.status === "passed").length;
  const failed = runs.filter((run) => ["failed", "error"].includes(run.session.status)).length;
  const running = runs.filter((run) => run.session.status === "running").length;
  const total = runs.length;

  if (total === 0 || agents.length === 0) {
    return (
      <EmptyPanel
        Icon={FlaskConical}
        title="No evaluations yet"
        description="Once runs start flowing in, success rate, latency, and outcome charts will appear here to benchmark agent versions and catch regressions."
      />
    );
  }

  const outcome = [
    { label: "Passed", value: passed, className: "bg-success" },
    { label: "Failed / error", value: failed, className: "bg-warning" },
    { label: "Running", value: running, className: "bg-accent" },
  ];
  const maxLatency = Math.max(...agents.map((agent) => agent.avgLatencyMs), 1);

  return (
    <div className="flex flex-col gap-3">
      <ChartCard title="Run outcomes" subtitle={`${total} runs evaluated`}>
        <div
          className="flex h-3 w-full overflow-hidden rounded-md border border-border/60"
          role="img"
          aria-label={`${passed} passed, ${failed} failed or error, ${running} running`}
        >
          {outcome.map((segment) =>
            segment.value ? (
              <div
                key={segment.label}
                className={segment.className}
                style={{ width: `${(segment.value / total) * 100}%` }}
                title={`${segment.label}: ${segment.value}`}
              />
            ) : null,
          )}
        </div>
        <dl className="mt-3.5 flex flex-wrap gap-x-7 gap-y-2">
          {outcome.map((segment) => (
            <div key={segment.label} className="flex items-center gap-2">
              <span className={cn("size-2 rounded-full", segment.className)} aria-hidden />
              <dt className="text-xs text-muted-foreground">{segment.label}</dt>
              <dd className="text-sm font-semibold tabular-nums text-foreground">
                {segment.value}
              </dd>
            </div>
          ))}
        </dl>
      </ChartCard>

      <div className="grid gap-3 lg:grid-cols-2">
        <ChartCard title="Success rate by agent" subtitle="Share of non-failing runs">
          <div className="space-y-3.5">
            {agents.map((agent) => (
              <BarRow
                key={agent.id}
                label={agent.name}
                display={pct(agent.successRate)}
                ratio={agent.successRate}
                tone={agent.successRate < 0.9 ? "warning" : "success"}
              />
            ))}
          </div>
        </ChartCard>

        <ChartCard title="Avg latency by agent" subtitle="Lower is better">
          <div className="space-y-3.5">
            {agents.map((agent) => (
              <BarRow
                key={agent.id}
                label={agent.name}
                display={fmtDuration(agent.avgLatencyMs)}
                ratio={agent.avgLatencyMs / maxLatency}
                tone="accent"
              />
            ))}
          </div>
        </ChartCard>
      </div>
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={SURFACE}>
      <header className="border-b border-border/60 px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p> : null}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

function BarRow({
  label,
  display,
  ratio,
  tone,
}: {
  label: string;
  display: string;
  ratio: number;
  tone: "success" | "warning" | "accent";
}) {
  const width = Math.max(2, Math.min(100, ratio * 100));
  const fill =
    tone === "success" ? "bg-success" : tone === "warning" ? "bg-warning" : "bg-accent";
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span className="truncate text-xs font-medium text-foreground">{label}</span>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{display}</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-sm bg-muted">
        <div className={cn("h-full rounded-sm", fill)} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

// ─── Logs (flat, scannable run stream) ────────────────────────────────────────

function LogsPanel({
  query,
  onQueryChange,
  status,
  onStatusChange,
  runs,
  onOpenRun,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  status: LogFilters["status"];
  onStatusChange: (value: LogFilters["status"]) => void;
  runs: LogRun[];
  onOpenRun: (run: LogRun) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className={cn("flex flex-col gap-2 overflow-hidden p-2 sm:flex-row sm:items-center", SURFACE)}>
        <label className="relative min-w-0 flex-1">
          <span className="sr-only">Search logs</span>
          <Search className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Search runs, inputs, outputs, errors…"
            className="h-10 w-full rounded-md bg-transparent pl-10 pr-3 text-[13px] text-foreground outline-none placeholder:text-muted-foreground/60 focus-visible:bg-elevated/40"
          />
        </label>
        <div className="flex flex-wrap items-center gap-1 px-1">
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
                    ? "bg-accent/10 text-accent"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {filter.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className={cn("overflow-hidden", SURFACE)}>
        {runs.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-muted-foreground">
            No runs match the current filters.
          </p>
        ) : (
          <ul className="divide-y divide-border/60">
            {runs.map((run) => (
              <li key={run.session.id}>
                <button
                  type="button"
                  onClick={() => onOpenRun(run)}
                  className="flex w-full items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-elevated/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/50"
                >
                  <StatusPill status={run.session.status} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] text-foreground">
                      {run.session.user_goal ?? run.session.id}
                    </span>
                    {run.errorPreview ? (
                      <span className="mono block truncate text-[11px] text-warning/90">
                        {run.errorPreview}
                      </span>
                    ) : (
                      <span className="mono block truncate text-[11px] text-muted-foreground">
                        {shortId(run.session.id, 18)} · {run.session.environment ?? "unknown"}
                      </span>
                    )}
                  </span>
                  <span className="mono hidden shrink-0 text-[11px] text-muted-foreground lg:block">
                    {numberFormat(run.totalTokens)} tok
                  </span>
                  <span className="mono hidden shrink-0 text-[11px] text-muted-foreground sm:block">
                    {fmtDuration(run.latencyMs)}
                  </span>
                  <span className="mono hidden shrink-0 text-[11px] text-muted-foreground md:block">
                    {fmtRelative(run.session.started_at)}
                  </span>
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground/45" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function EmptyPanel({
  Icon,
  title,
  description,
}: {
  Icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <div className={cn("flex min-h-[440px] flex-col items-center justify-center px-6 text-center", SURFACE)}>
      <span className="flex size-12 items-center justify-center rounded-md border border-border/60 bg-muted text-muted-foreground">
        <Icon className="size-5" strokeWidth={1.8} />
      </span>
      <h2 className="mt-4 text-base font-semibold text-foreground">{title}</h2>
      <p className="mt-1.5 max-w-sm text-sm leading-6 text-muted-foreground">{description}</p>
    </div>
  );
}

// ─── Actions (human-in-the-loop PR review) ───────────────────────────────────

/** Derive a readable branch name from a GitHub PR url, or null. */
function prBranchHint(prUrl: string | null): string | null {
  if (!prUrl) return null;
  const match = prUrl.match(/\/pull\/(\d+)/);
  return match ? `PR #${match[1]}` : null;
}

/**
 * The human-in-the-loop surface: every pull request the fix agent (Devin) opened
 * for a verified fix, waiting for a person to review and merge. This is where the
 * loop deliberately stops — Promptetheus never auto-merges.
 */
function ActionsPanel({
  incidents,
  onOpenRun,
}: {
  incidents: Incident[];
  onOpenRun: (run: LogRun) => void;
}) {
  void onOpenRun; // actions link to the incident detail; run-open kept for parity
  const prs = incidents.filter((incident) => incident.pr_url || incident.fix_agent_result);
  const awaiting = prs.filter((incident) => incident.status !== "fixed");
  const merged = prs.filter((incident) => incident.status === "fixed");

  if (prs.length === 0) {
    return (
      <EmptyPanel
        Icon={GitPullRequest}
        title="No pull requests yet"
        description="When the fix agent verifies a fix it opens a pull request and pauses here for a human to review and merge — nothing is auto-merged."
      />
    );
  }

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Actions</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Pull requests opened by the fix agent — review and merge. The loop stops
            here; nothing merges without you.
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-md border border-warning/30 bg-warning/10 px-2.5 py-1 text-xs font-semibold text-warning">
          <Clock className="size-3.5" />
          {awaiting.length} awaiting review
        </span>
      </header>

      {awaiting.length > 0 ? (
        <div className="flex flex-col gap-2.5">
          {awaiting.map((incident) => (
            <ActionPrCard key={incident.id} incident={incident} />
          ))}
        </div>
      ) : null}

      {merged.length > 0 ? (
        <div className="flex flex-col gap-2.5">
          <SectionLabel>Merged</SectionLabel>
          {merged.map((incident) => (
            <ActionPrCard key={incident.id} incident={incident} merged />
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ActionPrCard({
  incident,
  merged = false,
}: {
  incident: Incident;
  merged?: boolean;
}) {
  const fix = incident.fix_agent_result;
  const runner = fix?.runner ?? "claude";
  const RunnerMark = runner === "claude" ? ClaudeMark : DevinMark;
  const branch = prBranchHint(incident.pr_url);
  const title = fix?.summary || incident.title || incident.label;

  return (
    <article className={cn("flex flex-col gap-3 p-3.5", SURFACE)}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md border border-border/60 bg-elevated">
            <DevinMark className="size-4" />
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <p className="truncate text-sm font-medium text-foreground">{title}</p>
              {branch ? (
                <span className="mono shrink-0 text-[10px] text-muted-foreground">{branch}</span>
              ) : null}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <LabelTag label={incident.label} />
              <span className="inline-flex items-center gap-1 rounded border border-border/60 bg-elevated px-1.5 py-0.5 text-[10px] text-muted-foreground">
                <RunnerMark className="size-3" /> {runner}
              </span>
              {typeof fix?.confidence === "number" ? (
                <span className="text-[10px] text-muted-foreground">
                  {pct(fix.confidence)} confidence
                </span>
              ) : null}
            </div>
          </div>
        </div>
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] font-semibold",
            merged ? "bg-success/15 text-success" : "bg-warning/15 text-warning",
          )}
        >
          {merged ? <GitMerge className="size-3" /> : <Clock className="size-3" />}
          {merged ? "merged" : "awaiting merge"}
        </span>
      </div>

      {fix?.changed_files && fix.changed_files.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {fix.changed_files.map((file) => (
            <span key={file} className="mono rounded bg-elevated px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {file}
            </span>
          ))}
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-2">
        <Link
          href={`/incidents/${incident.id}`}
          className="text-[11px] font-medium text-muted-foreground hover:text-foreground"
        >
          View incident
        </Link>
        <div className="flex items-center gap-2">
          {incident.pr_url ? (
            <a
              href={incident.pr_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-border/70 px-2.5 py-1.5 text-[11px] font-semibold text-foreground transition-colors hover:bg-elevated"
            >
              <GitPullRequest className="size-3.5" /> View PR <ExternalLink className="size-3" />
            </a>
          ) : null}
          {!merged ? (
            <button
              type="button"
              disabled={!incident.pr_url}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent px-2.5 py-1.5 text-[11px] font-semibold text-accent-foreground transition-colors hover:bg-accent-bright disabled:opacity-50"
              title={incident.pr_url ? "Open the PR on GitHub to merge" : "No PR yet"}
            >
              <GitMerge className="size-3.5" /> Approve &amp; merge
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

// ─── Settings ─────────────────────────────────────────────────────────────────

/**
 * Project settings: generic configuration plus the operational controls the demo
 * needs — reload data, and per-agent removal (decommission an instrumented agent).
 */
function SettingsPanel({ agents }: { agents: AgentRow[] }) {
  const [removed, setRemoved] = React.useState<Set<string>>(new Set());
  const visibleAgents = agents.filter((agent) => !removed.has(agent.id));

  return (
    <section className="flex flex-col gap-4">
      <header>
        <h2 className="text-sm font-semibold text-foreground">Settings</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Project configuration, instrumented agents, and maintenance.
        </p>
      </header>

      <div className={cn("flex flex-col divide-y divide-border/60", SURFACE)}>
        <SettingRow label="API endpoint" hint="Where agents send traces">
          <code className="mono rounded bg-elevated px-2 py-1 text-[11px] text-foreground">
            POST /api/ingest
          </code>
        </SettingRow>
        <SettingRow label="Connected repo" hint="Where the fix agent opens PRs">
          <code className="mono rounded bg-elevated px-2 py-1 text-[11px] text-foreground">
            acme/acmemeet-agent
          </code>
        </SettingRow>
        <SettingRow label="Trace retention" hint="How long runs are kept">
          <span className="text-[11px] text-muted-foreground">30 days</span>
        </SettingRow>
      </div>

      <div className={cn("overflow-hidden", SURFACE)}>
        <header className={PANEL_HEADER}>
          <span className="text-xs font-semibold text-foreground">
            Instrumented agents ({visibleAgents.length})
          </span>
        </header>
        {visibleAgents.length === 0 ? (
          <p className="px-3.5 py-6 text-center text-xs text-muted-foreground">
            All agents removed. Re-instrument an agent to see it here.
          </p>
        ) : (
          <ul className="divide-y divide-border/60">
            {visibleAgents.map((agent) => (
              <li key={agent.id} className="flex items-center justify-between gap-3 px-3.5 py-2.5">
                <div className="flex min-w-0 items-center gap-2.5">
                  <Bot className="size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium text-foreground">{agent.name}</p>
                    <p className="mono text-[10px] text-muted-foreground">
                      {agent.version} · {agent.runCount} runs
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setRemoved((prev) => new Set(prev).add(agent.id))}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border/70 px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-destructive/50 hover:text-destructive"
                >
                  <Trash2 className="size-3.5" /> Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className={cn("flex flex-wrap items-center justify-between gap-3 p-3.5", SURFACE)}>
        <div>
          <p className="text-xs font-semibold text-foreground">Maintenance</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Reload trace data or restart the connection to the ingestion service.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="inline-flex items-center gap-1.5 rounded-md border border-border/70 px-2.5 py-1.5 text-[11px] font-semibold text-foreground transition-colors hover:bg-elevated"
          >
            <RefreshCw className="size-3.5" /> Reload data
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="inline-flex items-center gap-1.5 rounded-md border border-border/70 px-2.5 py-1.5 text-[11px] font-semibold text-foreground transition-colors hover:bg-elevated"
          >
            <Power className="size-3.5" /> Reconnect
          </button>
        </div>
      </div>
    </section>
  );
}

function SettingRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 px-3.5 py-3">
      <div>
        <p className="text-xs font-medium text-foreground">{label}</p>
        <p className="text-[10px] text-muted-foreground">{hint}</p>
      </div>
      {children}
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
      <div className={cn("flex flex-col overflow-hidden lg:flex-row lg:items-stretch", SURFACE)}>
        <label className="relative min-w-0 flex-1 border-b border-border/60 transition-colors focus-within:bg-elevated/55 lg:border-b-0 lg:border-r">
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
      <div className={cn("flex min-h-[260px] items-center justify-center p-6 text-sm text-muted-foreground", SURFACE)}>
        No runs match the current filters.
      </div>
    );
  }

  return (
    <div
      className={cn("max-h-[42dvh] min-h-[340px] overflow-auto", SURFACE)}
      aria-label="Runs list"
    >
      <Table>
        <TableHeader className="sticky top-0 z-10 bg-muted/60">
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
                    <span className="mono inline-flex items-center rounded-md bg-elevated px-2 py-1 text-[10px] text-muted-foreground">
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
        "mono inline-flex rounded-md border px-1.5 py-0.5 text-[10px]",
        slow
          ? "border-warning/30 bg-warning/10 text-warning"
          : "border-success/30 bg-success/10 text-success",
      )}
    >
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
  detailTab: InspectorTab;
  onDetailTabChange: (tab: InspectorTab) => void;
}) {
  return (
    <div className="grid min-h-[520px] grid-cols-1 gap-3 lg:grid-cols-[minmax(360px,0.95fr)_minmax(420px,1.05fr)]">
      <section
        className={cn("flex min-h-[520px] flex-col overflow-hidden", SURFACE)}
        aria-label="Trace waterfall"
      >
        <div className={PANEL_HEADER}>
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
              className="flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Expand trace tree"
            >
              <PanelRight className="size-3.5" />
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
                  <span className="mono ml-2 shrink-0 rounded-md bg-elevated px-1.5 py-0.5 text-[10px] text-muted-foreground">
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
}: {
  run: LogRun;
  event: TraceEvent | undefined;
  tab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  onEvidenceSelect: (seq: number) => void;
}) {
  const eventPayload = event?.payload ?? {};
  const eventMetadata = event?.metadata ?? null;

  return (
    <section className={cn("flex min-h-[520px] flex-col overflow-hidden", SURFACE)} aria-label="Run inspector">
      <div className={PANEL_HEADER}>
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
        <div className="flex shrink-0 items-center gap-2">
          <Button
            type="button"
            variant={tab === "fix" ? "default" : "outline"}
            size="sm"
            onClick={() => onTabChange("fix")}
            aria-label="Open Fix DAG"
          >
            <Sparkles className="size-3.5" />
            Fix DAG
          </Button>
          <span className="mono hidden rounded-md border border-border bg-elevated px-2 py-1 text-[10px] text-muted-foreground sm:inline">
            {costEstimate(run.totalTokens)}
          </span>
        </div>
      </div>

      <Tabs
        value={tab}
        onValueChange={(value) => onTabChange(value as InspectorTab)}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="mx-3 mt-1 flex">
          <TabsTrigger value="run">Run</TabsTrigger>
          <TabsTrigger value="feedback">Feedback</TabsTrigger>
          <TabsTrigger value="fix">
            <Sparkles className="size-3.5" />
            Fix DAG
          </TabsTrigger>
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
                      className="mono min-h-8 rounded-md border border-border bg-elevated px-2 text-[11px] text-accent transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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

          <TabsContent value="fix" className="mt-3">
            <FixDispatchDag run={run} />
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
    <div className="rounded-md border border-border bg-elevated px-3 py-2">
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
    <details open={defaultOpen} className="group rounded-md border border-border bg-panel/50">
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
        "max-h-52 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-canvas p-3 text-xs leading-5",
        tone === "error" ? "text-warning" : "text-foreground/90",
      )}
    >
      {children}
    </pre>
  );
}

function FilterRail({
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
  horizontal = false,
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
  horizontal?: boolean;
}) {
  return (
    <aside
      className={cn(
        horizontal
          ? "grid gap-3 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]"
          : "flex flex-col gap-3",
      )}
    >
      <div className={cn("overflow-hidden", SURFACE)}>
        <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
          <h2 className="text-xs font-semibold text-foreground">Filtered metrics</h2>
          <span className="text-[10px] text-muted-foreground">live</span>
        </div>
        <dl
          className={cn(
            "grid gap-px bg-border/60",
            horizontal ? "grid-cols-3 sm:grid-cols-6 lg:grid-cols-2 xl:grid-cols-3" : "grid-cols-2",
          )}
        >
          <MetricTile label="Runs" value={String(metrics.totalRuns)} Icon={Activity} />
          <MetricTile label="Failures" value={String(metrics.failedRuns)} Icon={AlertCircle} />
          <MetricTile label="Error rate" value={pct(metrics.errorRate)} Icon={Gauge} />
          <MetricTile label="P50" value={fmtDuration(metrics.p50LatencyMs)} Icon={Timer} />
          <MetricTile label="P99" value={fmtDuration(metrics.p99LatencyMs)} Icon={Timer} />
          <MetricTile label="Tokens" value={numberFormat(metrics.totalTokens)} Icon={FileJson} />
        </dl>
      </div>

      <div className={cn("overflow-hidden", SURFACE)}>
        <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
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
        <div className={cn(horizontal && "grid sm:grid-cols-3")}>
          <FilterGroup title="Projects" horizontal={horizontal}>
            {projects.map((project) => (
              <CheckFilter
                key={project.id}
                label={project.name}
                checked={selectedProjects.includes(project.id)}
                onChange={() => onProjectToggle(project.id)}
              />
            ))}
          </FilterGroup>
          <FilterGroup title="Environment" horizontal={horizontal}>
            {environments.map((environment) => (
              <CheckFilter
                key={environment}
                label={environment}
                checked={selectedEnvironments.includes(environment)}
                onChange={() => onEnvironmentToggle(environment)}
              />
            ))}
          </FilterGroup>
          <FilterGroup title="Tags" icon={<Tags className="size-3" />} horizontal={horizontal}>
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
  horizontal = false,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  horizontal?: boolean;
}) {
  return (
    <div
      className={cn(
        "border-border/70 p-3",
        horizontal
          ? "border-b last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0"
          : "border-b last:border-b-0",
      )}
    >
      <p className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
        {icon}
        {title}
      </p>
      <div className={cn("space-y-1.5", horizontal && "max-h-28 overflow-y-auto pr-1")}>
        {children}
      </div>
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
    <label className="flex min-h-7 cursor-pointer items-center gap-2 rounded-md px-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground">
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

/**
 * Standalone trace + inspector view for a single run, used by the
 * `/logs/[sessionId]` route. Wraps the new {@link TraceDebugger} with
 * self-contained state so it can render outside the dashboard shell.
 */
export function LogSessionTraceView({ run }: { run: LogRun }) {
  const traceTree = React.useMemo(() => buildTraceTree(run.events), [run]);
  const [expanded, setExpanded] = React.useState<Set<string>>(() =>
    allExpandable(traceTree),
  );
  const [selectedSeq, setSelectedSeq] = React.useState<number | null>(
    () => firstFailedEvent(run)?.seq ?? null,
  );
  const [detailTab, setDetailTab] = React.useState<InspectorTab>("run");

  React.useEffect(() => {
    setExpanded(allExpandable(buildTraceTree(run.events)));
    setSelectedSeq(firstFailedEvent(run)?.seq ?? null);
    setDetailTab("run");
  }, [run.session.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const visibleTrace = React.useMemo(
    () => flattenTraceTree(traceTree, expanded),
    [expanded, traceTree],
  );
  const selectedEvent = React.useMemo(
    () => run.events.find((event) => event.seq === selectedSeq) ?? firstFailedEvent(run),
    [run, selectedSeq],
  );

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
    />
  );
}
