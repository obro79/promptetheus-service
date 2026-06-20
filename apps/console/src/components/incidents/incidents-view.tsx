"use client";

import * as React from "react";
import { Inbox, SearchX } from "lucide-react";

import type { Incident } from "@/lib/types";
import { EmptyState } from "@/components/common/empty-state";
import {
  IncidentFilters,
  type SeverityFilter,
  type StatusFilter,
} from "./incident-filters";
import { IncidentList } from "./incident-list";

const EMPTY_RESULTS_ILLUSTRATION = {
  src: "/illustrations/empty-results.webp",
  width: 176,
  height: 107,
} as const;

const EMPTY_INCIDENTS_ILLUSTRATION = {
  src: "/illustrations/empty-incidents.webp",
  width: 208,
  height: 104,
} as const;

export interface IncidentsViewProps {
  incidents: Incident[];
}

export function IncidentsView({ incidents }: IncidentsViewProps) {
  const [query, setQuery] = React.useState("");
  const [status, setStatus] = React.useState<StatusFilter>("all");
  const [severity, setSeverity] = React.useState<SeverityFilter>("all");

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return incidents.filter((incident) => {
      if (status !== "all" && incident.status !== status) return false;
      if (severity !== "all" && incident.severity !== severity) return false;
      if (!q) return true;
      const haystack = [
        incident.title,
        incident.label,
        incident.fingerprint,
        incident.root_cause ?? "",
        ...incident.labels,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [incidents, query, status, severity]);

  const hasFilters = query.trim() !== "" || status !== "all" || severity !== "all";

  return (
    <div className="flex flex-col gap-6">
      <IncidentFilters
        query={query}
        onQueryChange={setQuery}
        status={status}
        onStatusChange={setStatus}
        severity={severity}
        onSeverityChange={setSeverity}
        resultCount={filtered.length}
        hasFilters={hasFilters}
        onClear={() => {
          setQuery("");
          setStatus("all");
          setSeverity("all");
        }}
      />

      {filtered.length === 0 ? (
        hasFilters ? (
          <EmptyState
            icon={SearchX}
            illustration={EMPTY_RESULTS_ILLUSTRATION}
            title="No incidents match your filters"
            description="Try clearing the search or widening the status and severity filters."
          />
        ) : (
          <EmptyState
            icon={Inbox}
            illustration={EMPTY_INCIDENTS_ILLUSTRATION}
            title="No incidents yet"
            description="When the analysis engine clusters failing sessions, incidents will land here."
          />
        )
      ) : (
        <IncidentList incidents={filtered} />
      )}
    </div>
  );
}
