import * as React from "react";
import { Layers } from "lucide-react";

import type { ReplayArtifact, TraceEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EvidenceChip, type EvidenceKind } from "@/components/common/evidence-chip";

export interface EvidenceRailProps {
  events: TraceEvent[];
  artifacts: ReplayArtifact[];
  className?: string;
}

interface EvidenceItem {
  key: string;
  kind: EvidenceKind;
  label: string;
}

/** Derive a deduped, ordered set of evidence chips from the session. */
function deriveEvidence(
  events: TraceEvent[],
  artifacts: ReplayArtifact[],
): EvidenceItem[] {
  const items: EvidenceItem[] = [];

  const goal = events.find((e) => e.type === "user_message");
  if (goal) {
    const content = (goal.payload as Record<string, unknown>).content;
    items.push({
      key: "goal",
      kind: "text",
      label:
        typeof content === "string"
          ? `goal: ${content.slice(0, 48)}${content.length > 48 ? "…" : ""}`
          : "user goal",
    });
  }

  for (const e of events) {
    if (e.type === "dom_snapshot") {
      const warnings = (e.payload as Record<string, unknown>).warnings;
      if (Array.isArray(warnings)) {
        for (const w of warnings as string[]) {
          items.push({
            key: `warn-${e.seq}`,
            kind: "warning",
            label: w.slice(0, 56) + (w.length > 56 ? "…" : ""),
          });
        }
      }
    }
  }

  for (const a of artifacts) {
    const kind: EvidenceKind =
      a.kind === "screenshot"
        ? "screenshot"
        : a.kind === "dom_snapshot"
          ? "dom_snapshot"
          : a.kind === "audio"
            ? "audio"
            : "video";
    items.push({
      key: a.artifact_id,
      kind,
      label: a.storage_path.split("/").pop() ?? a.artifact_id,
    });
  }

  return items;
}

export function EvidenceRail({
  events,
  artifacts,
  className,
}: EvidenceRailProps) {
  const items = React.useMemo(
    () => deriveEvidence(events, artifacts),
    [events, artifacts],
  );

  if (!items.length) return null;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-center gap-1.5">
        <Layers className="size-3.5 text-muted-foreground" />
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Evidence captured
        </span>
        <span className="mono text-[11px] tabular-nums text-muted-foreground/60">
          {items.length}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <EvidenceChip key={item.key} kind={item.kind} label={item.label} />
        ))}
      </div>
    </div>
  );
}
