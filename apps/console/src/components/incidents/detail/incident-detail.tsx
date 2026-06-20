"use client";

import { ForensicConsole } from "@/components/forensics/forensic-console";
import type { IncidentContext } from "@/lib/types";

export interface IncidentDetailProps {
  context: IncidentContext;
}

export function IncidentDetail({ context }: IncidentDetailProps) {
  return (
    <ForensicConsole
      session={context.session}
      events={context.events}
      analysis={context.analysis}
      artifacts={context.artifacts}
      incident={context.incident}
      regressionRuns={context.regression_runs}
    />
  );
}
