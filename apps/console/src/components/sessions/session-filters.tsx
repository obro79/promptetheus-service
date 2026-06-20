"use client";

import * as React from "react";
import { Search, X } from "lucide-react";

import type { SessionStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";

export type StatusFilter = "all" | SessionStatus;

export interface StatusCounts {
  all: number;
  running: number;
  passed: number;
  failed: number;
  error: number;
}

export interface SessionFiltersProps {
  status: StatusFilter;
  onStatusChange: (status: StatusFilter) => void;
  query: string;
  onQueryChange: (query: string) => void;
  counts: StatusCounts;
}

const FILTERS: { value: StatusFilter; label: string; dot: string | null }[] = [
  { value: "all", label: "All", dot: null },
  { value: "running", label: "Running", dot: "bg-accent" },
  { value: "passed", label: "Passed", dot: "bg-success" },
  { value: "failed", label: "Failed", dot: "bg-destructive" },
  { value: "error", label: "Error", dot: "bg-destructive" },
];

export function SessionFilters({
  status,
  onStatusChange,
  query,
  onQueryChange,
  counts,
}: SessionFiltersProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="surface flex items-center gap-1 rounded-2xl p-1">
        {FILTERS.map((f) => {
          const active = status === f.value;
          const count = counts[f.value];
          return (
            <button
              key={f.value}
              type="button"
              onClick={() => onStatusChange(f.value)}
              aria-pressed={active}
              className={cn(
                "group inline-flex min-h-8 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                active
                  ? "bg-accent/10 text-accent shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {f.dot ? (
                <span
                  className={cn(
                    "size-1.5 rounded-full transition-opacity duration-150",
                    f.dot,
                    active ? "opacity-100" : "opacity-60 group-hover:opacity-100",
                  )}
                />
              ) : null}
              {f.label}
              <span
                className={cn(
                  "mono tabular-nums text-[10px] transition-colors duration-150",
                  active ? "text-muted-foreground" : "text-muted-foreground/60",
                )}
              >
                {count}
              </span>
            </button>
          );
        })}
      </div>

      <div className="relative w-full sm:w-80">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Filter by goal or agent…"
          aria-label="Filter sessions"
          className="h-10 pl-9 pr-9"
        />
        {query ? (
          <button
            type="button"
            onClick={() => onQueryChange("")}
            aria-label="Clear filter"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground transition-colors duration-150 hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <X className="size-3.5" />
          </button>
        ) : null}
      </div>
    </div>
  );
}
