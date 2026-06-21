import type { Metadata } from "next";
import { Gauge, ShieldCheck, Sparkles, TrendingUp } from "lucide-react";

import { getEvalScoreboard } from "@/lib/data";
import {
  ConsolePage,
  ConsolePageContent,
  ConsolePageHeader,
  ConsoleEyebrow,
  MetricReadout,
  SignalChip,
} from "@/components/common/console-primitives";
import { EvalScoreboardView } from "@/components/evals/eval-scoreboard";

export const metadata: Metadata = {
  title: "Evals · Promptetheus",
  description:
    "Fix-quality scoreboard: LLM-as-judge verdicts on every self-healing run.",
};

export default function EvalsPage() {
  const scoreboard = getEvalScoreboard();

  return (
    <ConsolePage>
      <ConsolePageHeader>
        <div className="min-w-0">
          <ConsoleEyebrow icon={<Gauge className="size-3.5" strokeWidth={1.8} aria-hidden />}>
            Fix-quality evals
          </ConsoleEyebrow>
          <h1 className="landing-display-lg max-w-4xl">
            The healer, graded on its own work
          </h1>
          <p className="mt-5 max-w-2xl text-sm leading-6 text-muted-foreground">
            Every self-healing run is scored by an LLM-as-judge against the
            assertion the agent violated: the fix only ships when the
            <span className="text-foreground"> before</span> output fails and the
            <span className="text-foreground"> after</span> output passes. These
            verdicts stream to Sentry in parallel for production observability.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-2.5 text-[11px] font-medium text-muted-foreground">
            <SignalChip Icon={Sparkles} label="LLM-as-judge before/after" />
            <SignalChip Icon={ShieldCheck} label="Gate blocks non-fixes" />
            <SignalChip Icon={TrendingUp} label="Emitted to Sentry" />
          </div>
        </div>
        <dl className="hidden shrink-0 grid-cols-2 gap-x-8 sm:grid">
          <MetricReadout label="Pass rate" value={`${Math.round(scoreboard.pass_rate * 100)}%`} />
          <MetricReadout label="Flips" value={scoreboard.flips} />
        </dl>
      </ConsolePageHeader>
      <ConsolePageContent>
        <EvalScoreboardView scoreboard={scoreboard} />
      </ConsolePageContent>
    </ConsolePage>
  );
}
