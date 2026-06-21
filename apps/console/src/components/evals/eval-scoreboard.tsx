import { ArrowRight, CheckCircle2, ShieldAlert, XCircle } from "lucide-react";

import type { EvalScoreboard, EvalScoreboardRow } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

interface StatCardProps {
  label: string;
  value: string;
  hint?: string;
}

function StatCard({ label, value, hint }: StatCardProps) {
  return (
    <div className="surface min-w-0 rounded-2xl px-5 py-4">
      <p className="text-[9px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </p>
      <p className="display mt-1 text-4xl leading-none text-foreground tabular-nums">
        {value}
      </p>
      {hint ? (
        <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

function ConfidenceBar({ value, tone }: { value: number; tone: "ok" | "bad" }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full",
            tone === "ok" ? "bg-success" : "bg-destructive",
          )}
          style={{ width: pct(value) }}
        />
      </div>
      <span className="w-9 text-right text-[11px] tabular-nums text-muted-foreground">
        {pct(value)}
      </span>
    </div>
  );
}

function ScoreboardRow({ row }: { row: EvalScoreboardRow }) {
  return (
    <li className="grid grid-cols-1 items-center gap-3 px-5 py-4 sm:grid-cols-[1fr_auto_auto] sm:gap-6">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-foreground">{row.label}</p>
        <p className="mt-0.5 truncate text-[11px] leading-4 text-muted-foreground">
          {row.reason ?? row.incident_id}
        </p>
      </div>

      <div className="flex items-center gap-2">
        <Badge variant="destructive" className="gap-1">
          <XCircle className="size-3" strokeWidth={2} aria-hidden /> before
        </Badge>
        <ArrowRight className="size-3.5 text-muted-foreground/60" aria-hidden />
        {row.after_passed ? (
          <Badge variant="success" className="gap-1">
            <CheckCircle2 className="size-3" strokeWidth={2} aria-hidden /> after
          </Badge>
        ) : (
          <Badge variant="destructive" className="gap-1">
            <XCircle className="size-3" strokeWidth={2} aria-hidden /> after
          </Badge>
        )}
      </div>

      <div className="flex items-center gap-3 justify-self-start sm:justify-self-end">
        <ConfidenceBar value={row.confidence} tone={row.after_passed ? "ok" : "bad"} />
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {row.attempts} {row.attempts === 1 ? "attempt" : "attempts"}
        </span>
        {row.fallback ? (
          <Badge variant="warning" title="Deterministic fallback (no judge)">
            deterministic
          </Badge>
        ) : null}
      </div>
    </li>
  );
}

export interface EvalScoreboardViewProps {
  scoreboard: EvalScoreboard;
}

export function EvalScoreboardView({ scoreboard }: EvalScoreboardViewProps) {
  const { total, passed, pass_rate, flips, avg_confidence, fallback_count, rows } =
    scoreboard;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Fix-quality pass rate" value={pct(pass_rate)} hint={`${passed} of ${total} heals`} />
        <StatCard label="Before → after flips" value={String(flips)} hint="failures the fix resolved" />
        <StatCard label="Avg judge confidence" value={pct(avg_confidence)} hint="LLM-as-judge verdicts" />
        <StatCard
          label="Judged live"
          value={String(total - fallback_count)}
          hint={fallback_count ? `${fallback_count} deterministic` : "all real judge runs"}
        />
      </div>

      <div className="landing-framed-surface overflow-hidden rounded-2xl">
        <div className="flex items-center gap-2 border-b border-border-strong/45 px-5 py-3">
          <ShieldAlert className="size-3.5 text-muted-foreground/70" strokeWidth={1.8} aria-hidden />
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Per-incident eval verdicts
          </h2>
        </div>
        {rows.length ? (
          <ul className="divide-y divide-border-strong/30">
            {rows.map((row) => (
              <ScoreboardRow key={row.incident_id} row={row} />
            ))}
          </ul>
        ) : (
          <p className="px-5 py-10 text-center text-sm text-muted-foreground">
            No heals have been evaluated yet. Run the self-healing loop on an
            incident to populate the scoreboard.
          </p>
        )}
      </div>
    </div>
  );
}
