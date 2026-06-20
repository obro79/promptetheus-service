import { notFound } from "next/navigation";

import { ForensicConsole } from "@/components/forensics/forensic-console";
import { getIncidentContext } from "@/lib/data";

export default function DemoPage() {
  const context = getIncidentContext("inc_voice_false_success");
  if (!context) notFound();

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
