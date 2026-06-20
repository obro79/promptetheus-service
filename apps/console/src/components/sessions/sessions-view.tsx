"use client";

import * as React from "react";

import type { TraceSession } from "@/lib/types";
import {
  SessionFilters,
  type StatusCounts,
  type StatusFilter,
} from "@/components/sessions/session-filters";
import { SessionsTable } from "@/components/sessions/sessions-table";

export interface SessionsViewProps {
  sessions: TraceSession[];
}

function computeCounts(sessions: TraceSession[]): StatusCounts {
  const counts: StatusCounts = {
    all: sessions.length,
    running: 0,
    passed: 0,
    failed: 0,
    error: 0,
  };
  for (const s of sessions) {
    counts[s.status] += 1;
  }
  return counts;
}

/** Holds the client-side filter state and renders the filter bar + table. */
export function SessionsView({ sessions }: SessionsViewProps) {
  const [status, setStatus] = React.useState<StatusFilter>("all");
  const [query, setQuery] = React.useState("");

  const counts = React.useMemo(() => computeCounts(sessions), [sessions]);

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return sessions.filter((s) => {
      if (status !== "all" && s.status !== status) return false;
      if (!q) return true;
      const goal = s.user_goal?.toLowerCase() ?? "";
      const agent = s.agent?.toLowerCase() ?? "";
      return goal.includes(q) || agent.includes(q);
    });
  }, [sessions, status, query]);

  return (
    <div className="flex flex-col gap-3">
      <SessionFilters
        status={status}
        onStatusChange={setStatus}
        query={query}
        onQueryChange={setQuery}
        counts={counts}
      />

      <div className="flex items-center justify-between px-0.5 text-[11px] text-muted-foreground">
        <span>
          <span className="mono tabular-nums text-foreground">
            {filtered.length}
          </span>{" "}
          of <span className="mono tabular-nums">{sessions.length}</span>{" "}
          sessions
        </span>
        {query || status !== "all" ? (
          <button
            type="button"
            onClick={() => {
              setStatus("all");
              setQuery("");
            }}
            className="text-muted-foreground transition-colors duration-150 hover:text-foreground"
          >
            Reset filters
          </button>
        ) : null}
      </div>

      <SessionsTable sessions={filtered} />
    </div>
  );
}
