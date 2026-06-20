"use client";

import * as React from "react";
import { ChevronDown, RotateCcw, Search, X } from "lucide-react";

import type { IncidentStatus, Severity } from "@/lib/types";

export type StatusFilter = IncidentStatus | "all";
export type SeverityFilter = Severity | "all";

const STATUS_OPTIONS = ["all", "open", "triaged", "fixing", "fixed", "ignored"] as const;
const SEVERITY_OPTIONS = ["all", "critical", "high", "medium", "low"] as const;

export interface IncidentFiltersProps {
  query: string;
  onQueryChange: (value: string) => void;
  status: StatusFilter;
  onStatusChange: (value: StatusFilter) => void;
  severity: SeverityFilter;
  onSeverityChange: (value: SeverityFilter) => void;
  resultCount: number;
  hasFilters: boolean;
  onClear: () => void;
}

export function IncidentFilters({
  query,
  onQueryChange,
  status,
  onStatusChange,
  severity,
  onSeverityChange,
  resultCount,
  hasFilters,
  onClear,
}: IncidentFiltersProps) {
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.key === "/" &&
        !(event.target instanceof HTMLInputElement) &&
        !(event.target instanceof HTMLTextAreaElement)
      ) {
        event.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="landing-framed-surface flex flex-col overflow-hidden sm:flex-row sm:items-stretch">
      <label className="relative min-w-0 flex-1 border-b border-border/50 transition-colors focus-within:bg-elevated/55 sm:border-b-0 sm:border-r">
        <span className="sr-only">Search incidents</span>
        <Search className="absolute left-4 top-1/2 size-4 -translate-y-1/2 text-accent" />
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Search failures, fingerprints, evidence…"
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
        ) : (
          <span className="mono absolute right-4 top-1/2 -translate-y-1/2 rounded-full border border-border/60 px-2 py-0.5 text-[10px] text-muted-foreground">
            /
          </span>
        )}
      </label>
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] divide-x divide-border/50 sm:flex">
        <ConsoleSelect
          label="status"
          value={status}
          onChange={(value) => onStatusChange(value as StatusFilter)}
          options={STATUS_OPTIONS}
        />
        <ConsoleSelect
          label="severity"
          value={severity}
          onChange={(value) => onSeverityChange(value as SeverityFilter)}
          options={SEVERITY_OPTIONS}
        />
        <div className="flex h-14 min-w-[86px] items-center justify-end gap-1.5 px-3 sm:border-l sm:border-border/50">
          <span className="mono whitespace-nowrap rounded-full bg-accent-muted px-2 py-1 text-[10px] text-accent">
            {resultCount}<span className="hidden min-[460px]:inline"> results</span>
          </span>
          {hasFilters ? (
            <button
              type="button"
              onClick={onClear}
              aria-label="Clear all filters"
              title="Clear all filters"
              className="flex size-11 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <RotateCcw className="size-3.5" />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ConsoleSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="relative flex h-14 min-w-0 flex-1 items-center gap-2 px-4 transition-colors hover:bg-elevated/55 focus-within:bg-elevated/55">
      <span className="mono shrink-0 text-[9px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-10 min-w-0 flex-1 cursor-pointer appearance-none bg-transparent pr-5 text-xs font-semibold text-foreground outline-none focus:text-accent"
        aria-label={`Filter by ${label}`}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 size-3.5 text-muted-foreground" />
    </label>
  );
}
