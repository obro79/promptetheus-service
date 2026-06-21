"use client";

import * as React from "react";
import { ChevronDown, Columns3, RotateCcw, Search, Timer, X } from "lucide-react";

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
import { cn, fmtRelative, shortId } from "@/lib/utils";
import { toggleValue, formatLatencyBadge } from "./logs-shared";
import type { LogColumn, LogFilters, LogRun, LogSortKey, LogTimeRange } from "./model";

const STATUS_FILTERS: Array<{ value: LogFilters["status"]; label: string }> = [
  { value: "all", label: "All" },
  { value: "failed", label: "Failed" },
  { value: "passed", label: "Passed" },
  { value: "running", label: "Running" },
  { value: "error", label: "Error" },
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

export interface LogsRunsPanelProps {
  runs: LogRun[];
  statusCounts: Record<LogFilters["status"], number>;
  selectedRunId: string | undefined;
  query: string;
  onQueryChange: (value: string) => void;
  status: LogFilters["status"];
  onStatusChange: (value: LogFilters["status"]) => void;
  timeRange: LogTimeRange;
  onTimeRangeChange: (value: LogTimeRange) => void;
  visibleColumns: LogColumn[];
  onVisibleColumnsChange: (columns: LogColumn[]) => void;
  sortKey: LogSortKey;
  sortDirection: "asc" | "desc";
  onSort: (key: LogSortKey) => void;
  onSelectRun: (run: LogRun) => void;
  runRowRefs: React.MutableRefObject<Map<string, HTMLTableRowElement>>;
  hasFilters: boolean;
  onClearFilters: () => void;
}

export function LogsRunsPanel({
  runs,
  statusCounts,
  selectedRunId,
  query,
  onQueryChange,
  status,
  onStatusChange,
  timeRange,
  onTimeRangeChange,
  visibleColumns,
  onVisibleColumnsChange,
  sortKey,
  sortDirection,
  onSort,
  onSelectRun,
  runRowRefs,
  hasFilters,
  onClearFilters,
}: LogsRunsPanelProps) {
  const searchRef = React.useRef<HTMLInputElement>(null);
  const showColumn = React.useCallback(
    (column: LogColumn) => visibleColumns.includes(column),
    [visibleColumns],
  );

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.key === "/" &&
        !(event.target instanceof HTMLInputElement) &&
        !(event.target instanceof HTMLTextAreaElement)
      ) {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden" aria-label="Runs list">
      <div className="landing-framed-surface flex shrink-0 flex-col overflow-hidden">
        <div className="flex flex-col gap-0 border-b border-border/40 lg:flex-row lg:items-stretch">
          <label className="relative min-w-0 flex-1 transition-colors focus-within:bg-elevated/40 lg:border-r lg:border-border/40">
            <span className="sr-only">Search logs</span>
            <Search className="absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              ref={searchRef}
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="Search runs, inputs, outputs, errors…"
              aria-label="Search logs"
              className="h-11 w-full bg-transparent pl-11 pr-12 text-[13px] text-foreground outline-none placeholder:text-muted-foreground/60"
            />
            {query ? (
              <button
                type="button"
                onClick={() => onQueryChange("")}
                aria-label="Clear search"
                className="absolute right-1 top-1/2 flex size-9 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="size-3.5" />
              </button>
            ) : (
              <span className="mono absolute right-4 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground">
                /
              </span>
            )}
          </label>

          <div className="console-panel-pad flex flex-wrap items-center gap-x-1 gap-y-1 border-t border-border/40 lg:min-w-0 lg:flex-1 lg:border-t-0">
            {STATUS_FILTERS.map((filter) => {
              const active = status === filter.value;
              const count = statusCounts[filter.value];
              return (
                <button
                  key={filter.value}
                  type="button"
                  aria-pressed={active}
                  aria-label={`${filter.label} (${count})`}
                  onClick={() => onStatusChange(filter.value)}
                  className={cn(
                    "inline-flex min-h-7 items-center gap-1 rounded-full px-2.5 text-[11px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                    active
                      ? "bg-accent/10 text-accent"
                      : "text-muted-foreground hover:bg-elevated/60 hover:text-foreground",
                  )}
                >
                  {filter.label}
                  <span className="mono text-[10px] opacity-75">{count}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="console-panel-pad flex flex-wrap items-center gap-2 py-2.5">
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
              {runs.length} results
            </span>
            {hasFilters ? (
              <button
                type="button"
                onClick={onClearFilters}
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

      <div className="landing-framed-surface mt-3 min-h-0 flex-1 overflow-auto">
        {runs.length === 0 ? (
          <div className="flex min-h-[200px] items-center justify-center console-panel-pad py-6 text-sm text-muted-foreground">
            No runs match the current filters.
          </div>
        ) : (
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-muted/30">
              <TableRow className="hover:bg-transparent">
                {showColumn("status") ? (
                  <TableHead className="w-[88px]">Status</TableHead>
                ) : null}
                {showColumn("run") ? (
                  <SortableHead
                    label="Run"
                    sortId="run"
                    sortKey={sortKey}
                    sortDirection={sortDirection}
                    onSort={onSort}
                    className="min-w-[180px]"
                  />
                ) : null}
                {showColumn("input") ? (
                  <TableHead className="hidden min-w-[200px] sm:table-cell">Input</TableHead>
                ) : null}
                {showColumn("output") ? (
                  <TableHead className="hidden min-w-[180px] md:table-cell">Output</TableHead>
                ) : null}
                {showColumn("error") ? (
                  <TableHead className="min-w-[140px]">Error</TableHead>
                ) : null}
                {showColumn("project") ? (
                  <TableHead className="hidden w-[130px] xl:table-cell">Project</TableHead>
                ) : null}
                {showColumn("environment") ? (
                  <TableHead className="hidden w-[100px] xl:table-cell">Env</TableHead>
                ) : null}
                {showColumn("start_time") ? (
                  <SortableHead
                    label="Start"
                    sortId="start_time"
                    sortKey={sortKey}
                    sortDirection={sortDirection}
                    onSort={onSort}
                    className="hidden w-[110px] lg:table-cell"
                  />
                ) : null}
                {showColumn("latency") ? (
                  <SortableHead
                    label="Latency"
                    sortId="latency"
                    sortKey={sortKey}
                    sortDirection={sortDirection}
                    onSort={onSort}
                    className="w-[90px]"
                  />
                ) : null}
                {showColumn("feedback") ? (
                  <TableHead className="hidden w-[100px] xl:table-cell">Feedback</TableHead>
                ) : null}
                {showColumn("tokens") ? (
                  <SortableHead
                    label="Tokens"
                    sortId="tokens"
                    sortKey={sortKey}
                    sortDirection={sortDirection}
                    onSort={onSort}
                    className="hidden w-[90px] xl:table-cell"
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
                    ref={(node) => {
                      if (node) runRowRefs.current.set(run.session.id, node);
                      else runRowRefs.current.delete(run.session.id);
                    }}
                    data-run-id={run.session.id}
                    tabIndex={0}
                    role="button"
                    aria-label={`Inspect run ${run.session.id}`}
                    aria-pressed={selected}
                    onClick={() => onSelectRun(run)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelectRun(run);
                      }
                    }}
                    className={cn(
                      "cursor-pointer border-l-2 outline-none focus-visible:bg-elevated focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
                      selected
                        ? "border-l-accent bg-accent/[0.06] hover:bg-accent/[0.06]"
                        : "border-l-transparent",
                      failed && !selected && "hover:bg-warning/[0.04]",
                    )}
                  >
                    {showColumn("status") ? (
                      <TableCell className="py-3">
                        <StatusPill status={run.session.status} />
                      </TableCell>
                    ) : null}
                    {showColumn("run") ? (
                      <TableCell className="py-3">
                        <div className="min-w-0">
                          <p
                            className={cn(
                              "truncate text-sm text-foreground",
                              selected ? "font-semibold" : "font-medium",
                            )}
                          >
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
                      <PreviewCell value={run.errorPreview} tone="error" />
                    ) : null}
                    {showColumn("project") ? (
                      <TableCell className="hidden truncate py-3 text-muted-foreground xl:table-cell">
                        {run.project?.name ?? run.session.project_id}
                      </TableCell>
                    ) : null}
                    {showColumn("environment") ? (
                      <TableCell className="hidden py-3 xl:table-cell">
                        <span className="mono inline-flex items-center rounded-full bg-elevated px-2 py-0.5 text-[10px] text-muted-foreground">
                          {run.session.environment ?? "unknown"}
                        </span>
                      </TableCell>
                    ) : null}
                    {showColumn("start_time") ? (
                      <TableCell
                        className="mono hidden whitespace-nowrap py-3 text-xs text-muted-foreground lg:table-cell"
                        title={run.session.started_at}
                      >
                        {fmtRelative(run.session.started_at)}
                      </TableCell>
                    ) : null}
                    {showColumn("latency") ? (
                      <TableCell className="py-3">
                        <LatencyBadge ms={run.latencyMs} />
                      </TableCell>
                    ) : null}
                    {showColumn("feedback") ? (
                      <TableCell className="hidden py-3 xl:table-cell">
                        <span className="mono text-xs text-muted-foreground">
                          {run.confidence !== null ? `${Math.round(run.confidence * 100)}%` : "—"}
                        </span>
                      </TableCell>
                    ) : null}
                    {showColumn("tokens") ? (
                      <TableCell className="mono hidden py-3 text-xs text-muted-foreground xl:table-cell">
                        {run.totalTokens}
                      </TableCell>
                    ) : null}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>
    </section>
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
    <TableCell className={cn("py-3", className)}>
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
  const { slow, label } = formatLatencyBadge(ms);
  return (
    <span
      className={cn(
        "mono inline-flex rounded-full border px-2 py-0.5 text-[10px]",
        slow
          ? "border-warning/30 bg-warning/10 text-warning"
          : "border-success/30 bg-success/10 text-success",
      )}
    >
      {label}
    </span>
  );
}
