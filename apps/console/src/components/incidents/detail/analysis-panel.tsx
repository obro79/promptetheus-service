"use client";

import * as React from "react";
import { Crosshair, FlaskConical, ScanSearch, Sparkles } from "lucide-react";

import type { AnalysisResult } from "@/lib/types";
import { cn, pct } from "@/lib/utils";
import { ConfidenceMeter } from "@/components/common/confidence-meter";
import { LabelTag } from "@/components/common/label-tag";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface AnalysisPanelProps {
  analysis: AnalysisResult;
  /** highlight the critical step when an evidence ref is clicked. */
  onFocusSeq?: (seq: number) => void;
  className?: string;
}

export function AnalysisPanel({
  analysis,
  onFocusSeq,
  className,
}: AnalysisPanelProps) {
  const detections = [...analysis.detections].sort(
    (a, b) => b.confidence - a.confidence,
  );

  return (
    <Card className={cn("overflow-hidden", className)}>
      <CardHeader className="gap-2 border-b border-border">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <ScanSearch className="size-4 text-accent" />
            Root-cause analysis
          </CardTitle>
          {analysis.fallback ? (
            <span className="mono inline-flex items-center gap-1 rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-warning">
              <Sparkles className="size-3" />
              deterministic fallback
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-3 pt-1">
          <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Overall confidence
          </span>
          <ConfidenceMeter
            value={analysis.confidence}
            className="max-w-[160px]"
          />
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        {analysis.root_cause ? (
          <p className="text-sm leading-relaxed text-foreground">
            {analysis.root_cause}
          </p>
        ) : (
          <p className="text-sm italic text-muted-foreground">
            No root cause was derived for this incident.
          </p>
        )}

        {analysis.labels.length ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Failure labels
            </span>
            {analysis.labels.map((label) => (
              <LabelTag key={label} label={label} />
            ))}
          </div>
        ) : null}

        <div className="flex flex-col gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Detections
          </span>
          <ul className="flex flex-col gap-2">
            {detections.map((det, i) => (
              <li
                key={`${det.label}-${i}`}
                className="rounded-md border border-border bg-canvas px-3 py-2.5"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="mono text-xs font-medium text-foreground">
                      {det.label}
                    </span>
                    {det.description ? (
                      <span className="text-xs leading-relaxed text-muted-foreground">
                        {det.description}
                      </span>
                    ) : null}
                  </div>
                  <span className="mono shrink-0 text-xs font-medium tabular-nums text-accent">
                    {pct(det.confidence)}
                  </span>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <ConfidenceMeter
                    value={det.confidence}
                    showLabel={false}
                    className="max-w-[120px]"
                  />
                  {det.critical_step_seq !== null ? (
                    <span className="mono inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                      <Crosshair className="size-3 text-destructive" />
                      seq {det.critical_step_seq}
                    </span>
                  ) : null}
                  {det.evidence_refs.length ? (
                    <span className="flex flex-wrap items-center gap-1">
                      <span className="text-[10px] uppercase tracking-wide text-muted-foreground/70">
                        evidence
                      </span>
                      {det.evidence_refs.map((seq) => (
                        <button
                          key={seq}
                          type="button"
                          onClick={() => onFocusSeq?.(seq)}
                          className="mono rounded border border-border bg-elevated px-1 py-0.5 text-[10px] tabular-nums text-muted-foreground transition-colors duration-150 hover:border-accent/40 hover:text-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        >
                          #{seq}
                        </button>
                      ))}
                    </span>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </div>

        {analysis.observed_final_state ? (
          <div className="rounded-md border border-destructive/25 bg-destructive/5 px-3 py-2.5">
            <div className="mb-1 flex items-center gap-1.5">
              <FlaskConical className="size-3.5 text-destructive" />
              <span className="text-[11px] font-medium uppercase tracking-wide text-destructive">
                Observed final state
              </span>
            </div>
            <p className="text-xs leading-relaxed text-foreground/90">
              {analysis.observed_final_state}
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
