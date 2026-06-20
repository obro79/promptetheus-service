import { Activity, ListTree, ShieldAlert, Sparkles } from "lucide-react";

import { getSessions } from "@/lib/data";
import {
  ConsolePage,
  ConsolePageContent,
  ConsolePageHeader,
  ConsoleEyebrow,
  MetricReadout,
  SignalChip,
} from "@/components/common/console-primitives";
import { SessionsView } from "@/components/sessions/sessions-view";

export const metadata = {
  title: "Sessions · Promptetheus",
  description: "Live trace stream of instrumented agent runs.",
};

export default function SessionsPage() {
  const sessions = getSessions();
  const failed = sessions.filter(
    (s) => s.status === "failed" || s.status === "error",
  ).length;
  const passed = sessions.filter((s) => s.status === "passed").length;

  return (
    <ConsolePage>
      <ConsolePageHeader>
        <div className="min-w-0">
          <ConsoleEyebrow icon={<ListTree className="size-3.5" strokeWidth={1.8} aria-hidden />}>
            Session logs
          </ConsoleEyebrow>
          <h1 className="display max-w-4xl text-5xl leading-[0.92] text-foreground sm:text-6xl lg:text-7xl">
            Instrumented agent runs
          </h1>
          <p className="mt-5 max-w-2xl text-sm leading-6 text-muted-foreground">
            Raw agent runs with events, artifacts, and replay links. Use this
            when a failure was logged but not yet clustered into the inbox.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-2.5 text-[11px] font-medium text-muted-foreground">
            <SignalChip Icon={Sparkles} label="Replay artifacts attached" />
            <SignalChip Icon={ShieldAlert} label="Failure clustering active" />
            <SignalChip Icon={Activity} label="Live sessions streaming" />
          </div>
        </div>
        <dl className="grid w-full grid-cols-3 gap-3 lg:w-auto">
          <MetricReadout label="Total" value={sessions.length} />
          <MetricReadout label="Failed" value={failed} tone="warning" />
          <MetricReadout label="Passed" value={passed} tone="signal" />
        </dl>
      </ConsolePageHeader>

      <ConsolePageContent>
        <SessionsView sessions={sessions} />
      </ConsolePageContent>
    </ConsolePage>
  );
}
