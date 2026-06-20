"use client";

import * as React from "react";
import {
  Camera,
  Code2,
  Crosshair,
  Loader2,
  ScanSearch,
  Sparkles,
  Wrench,
} from "lucide-react";

import type { AnalysisResult } from "@/lib/types";
import { cn, pct } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ConfidenceMeter } from "@/components/common/confidence-meter";
import { EvidenceChip } from "@/components/common/evidence-chip";
import { LabelTag } from "@/components/common/label-tag";

export interface DemoAnalysisProps {
  analysis: AnalysisResult;
  /** has the run finished playing? */
  ready: boolean;
  /** is the detector actively scanning? */
  analyzing: boolean;
  /** has analysis completed and lit up? */
  analyzed: boolean;
  /** has Fix been pressed? (locks the button into dispatched state) */
  fixDispatched: boolean;
  onFix: () => void;
  className?: string;
}

const EVIDENCE_CHIPS: { kind: "screenshot" | "dom_snapshot" | "warning"; label: string }[] = [
  { kind: "warning", label: "Goal mismatch" },
  { kind: "warning", label: "Ignored warning" },
  { kind: "warning", label: "False success" },
  { kind: "dom_snapshot", label: "Timezone mismatch" },
  { kind: "screenshot", label: "03-warning-visible.png" },
];

export function DemoAnalysis({
  analysis,
  ready,
  analyzing,
  analyzed,
  fixDispatched,
  onFix,
  className,
}: DemoAnalysisProps) {
  return (
    <div
      className={cn(
        "surface flex h-full flex-col overflow-hidden rounded-2xl",
        className,
      )}
    >
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <ScanSearch
            className={cn(
              "size-3.5",
              analyzing
                ? "animate-pulse text-accent"
                : analyzed
                  ? "text-destructive"
                  : "text-muted-foreground",
            )}
          />
          <span className="text-xs font-medium text-foreground">
            Failure analysis
          </span>
        </div>
        {analyzed ? (
          <span className="mono inline-flex items-center gap-1 text-[11px] text-destructive">
            <span className="size-1.5 rounded-full bg-destructive" />
            failed
          </span>
        ) : null}
      </div>

      <div className="flex-1 overflow-auto p-3">
        {!analyzed ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            {analyzing ? (
              <>
                <Loader2 className="size-6 animate-spin text-accent" />
                <p className="text-xs text-muted-foreground">
                  Scanning trace for failure signatures…
                </p>
              </>
            ) : (
              <>
                <ScanSearch className="size-6 text-muted-foreground/40" />
                <p className="max-w-[16rem] text-xs text-muted-foreground/60">
                  {ready
                    ? "Run complete. Detectors will surface evidence here."
                    : "Detectors light up once the run finishes."}
                </p>
              </>
            )}
          </div>
        ) : (
          <div className="animate-fade-in space-y-4">
            {/* Detected labels */}
            <div>
              <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
                Detected
              </p>
              <div className="flex flex-wrap gap-1.5">
                {analysis.labels.map((l) => (
                  <LabelTag
                    key={l}
                    label={l}
                    className="border-destructive/25 bg-destructive/10 text-destructive"
                  />
                ))}
              </div>
            </div>

            {/* Evidence chips */}
            <div>
              <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
                Evidence
              </p>
              <div className="flex flex-wrap gap-1.5">
                {EVIDENCE_CHIPS.map((c) => (
                  <EvidenceChip key={c.label} kind={c.kind} label={c.label} />
                ))}
              </div>
            </div>

            {/* Critical step freeze-frame */}
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2.5">
              <div className="mb-1 flex items-center gap-1.5">
                <Crosshair className="size-3.5 text-destructive" />
                <span className="text-[11px] font-medium text-destructive">
                  Critical step · seq {analysis.critical_step_seq}
                </span>
              </div>
              <p className="text-[11px] leading-snug text-foreground/90">
                Agent selected{" "}
                <span className="mono text-destructive">2:00 AM</span> while the
                goal required{" "}
                <span className="mono text-success">2:00 PM</span>.
              </p>
              <div className="mt-2 flex items-center gap-2">
                <EvidenceChip kind="screenshot" label="02-time-selected-2am.png" />
                <EvidenceChip kind="dom_snapshot" label="selected_values" />
              </div>
            </div>

            {/* Root cause + confidence */}
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                Root cause
              </p>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                {analysis.root_cause}
              </p>
            </div>

            <div className="flex items-center gap-3 rounded-md border border-border bg-elevated/40 px-2.5 py-2">
              <span className="mono text-[11px] text-muted-foreground">
                confidence
              </span>
              <ConfidenceMeter value={analysis.confidence} className="flex-1" />
              <span className="mono text-xs font-medium tabular-nums text-accent">
                {pct(analysis.confidence)}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Fix button */}
      <div className="shrink-0 border-t border-border p-3">
        <Button
          size="lg"
          onClick={onFix}
          disabled={!analyzed || fixDispatched}
          className="w-full"
        >
          {fixDispatched ? (
            <>
              <Sparkles className="size-4" />
              Fix dispatched
            </>
          ) : (
            <>
              <Wrench className="size-4" />
              Fix this incident
            </>
          )}
        </Button>
        {!analyzed ? (
          <p className="mt-2 text-center text-[10px] text-muted-foreground/50">
            available after analysis
          </p>
        ) : null}
      </div>
    </div>
  );
}
