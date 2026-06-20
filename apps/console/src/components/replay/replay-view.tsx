"use client";

import { ForensicConsole } from "@/components/forensics/forensic-console";
import type { AnalysisResult, ReplayArtifact, TraceEvent, TraceSession } from "@/lib/types";

export interface ReplayViewProps {
  session: TraceSession;
  events: TraceEvent[];
  analysis: AnalysisResult | undefined;
  artifacts: ReplayArtifact[];
}

export function ReplayView(props: ReplayViewProps) {
  return <ForensicConsole {...props} />;
}
