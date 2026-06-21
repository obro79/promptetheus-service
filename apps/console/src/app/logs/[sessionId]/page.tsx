import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, ListTree } from "lucide-react";
import { notFound } from "next/navigation";

import {
  ConsoleEyebrow,
  ConsolePage,
  ConsolePageContent,
  ConsolePageHeader,
  MetricReadout,
} from "@/components/common/console-primitives";
import { LogSessionTraceView } from "@/components/logs/logs-dashboard";
import { buildLogRuns } from "@/components/logs/model";
import { StatusPill } from "@/components/common/status-pill";
import { Button } from "@/components/ui/button";
import {
  getAnalysis,
  getEvents,
  getIncidents,
  getProject,
  getProjects,
  getSession,
} from "@/lib/data";
import type { AnalysisResult, TraceEvent } from "@/lib/types";
import { fmtDuration, shortId } from "@/lib/utils";

interface LogSessionPageProps {
  params: { sessionId: string };
}

export function generateMetadata({ params }: LogSessionPageProps): Metadata {
  const session = getSession(params.sessionId);
  if (!session) {
    return { title: "Session not found · Logs · Promptetheus" };
  }
  return {
    title: `${session.user_goal ?? shortId(session.id, 12)} · Logs · Promptetheus`,
    description: `Trace waterfall and run inspector for session ${session.id}.`,
  };
}

export default function LogSessionPage({ params }: LogSessionPageProps) {
  const session = getSession(params.sessionId);
  if (!session) notFound();

  const projects = getProjects();
  const incidents = getIncidents();
  const events = getEvents(session.id);
  const analysis = getAnalysis(session.id);
  const eventsBySession: Record<string, TraceEvent[]> = { [session.id]: events };
  const analysesBySession: Record<string, AnalysisResult | undefined> = {
    [session.id]: analysis,
  };

  const runs = buildLogRuns({
    sessions: [session],
    projects,
    incidents,
    eventsBySession,
    analysesBySession,
  });
  const run = runs[0];
  if (!run) notFound();

  const project = getProject(session.project_id);

  return (
    <ConsolePage>
      <ConsolePageHeader>
        <div className="min-w-0">
          <Button asChild variant="ghost" size="sm" className="-ml-2 mb-3 h-8 px-2 text-muted-foreground">
            <Link href="/logs">
              <ArrowLeft className="size-3.5" />
              Back to logs
            </Link>
          </Button>
          <ConsoleEyebrow icon={<ListTree className="size-3.5" strokeWidth={1.8} aria-hidden />}>
            Session trace
          </ConsoleEyebrow>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <h1 className="landing-display-lg max-w-4xl truncate">
              {session.user_goal ?? session.id}
            </h1>
            <StatusPill status={session.status} />
          </div>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            {project?.name ?? session.project_id} · {session.environment ?? "unknown"} ·{" "}
            <span className="mono">{session.id}</span>
          </p>
        </div>
        <dl className="grid w-full grid-cols-3 gap-3 lg:w-auto">
          <MetricReadout label="Events" value={run.events.length} />
          <MetricReadout label="Latency" value={fmtDuration(run.latencyMs)} />
          <MetricReadout
            label="Tokens"
            value={run.totalTokens.toLocaleString("en-US")}
            tone="signal"
          />
        </dl>
      </ConsolePageHeader>

      <ConsolePageContent>
        <LogSessionTraceView run={run} />
      </ConsolePageContent>
    </ConsolePage>
  );
}
