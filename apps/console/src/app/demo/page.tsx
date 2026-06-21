import type { LucideIcon } from "lucide-react";
import {
  ArrowRight,
  Bot,
  CircleDot,
  Crosshair,
  ListTree,
  MessageSquare,
  Play,
  Radio,
  Sparkles,
  Terminal,
  TriangleAlert,
  Zap,
} from "lucide-react";

import {
  ConsoleEyebrow,
  ConsolePage,
  ConsolePageContent,
  ConsolePageHeader,
  MetricReadout,
} from "@/components/common/console-primitives";
import { DemoPresentation } from "@/components/demo/demo-presentation";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const metadata = {
  title: "Guided demo · Promptetheus",
  description:
    "Watch three agents fail in production, get instrumented, stream live traces, and heal themselves after an auto-dispatched fix.",
};

// ─── Shared surface language (matches the logs dashboard) ─────────────────────

const SURFACE = "rounded-lg border border-border/70 bg-panel";
const PANEL_HEADER =
  "flex min-h-11 items-center justify-between gap-2 border-b border-border/60 px-3.5 py-2";

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function DemoPage() {
  return (
    <ConsolePage>
      <ConsolePageHeader>
        <div className="min-w-0">
          <ConsoleEyebrow icon={<Play className="size-3.5" strokeWidth={2} aria-hidden />}>
            Guided demo
          </ConsoleEyebrow>
          <h1 className="landing-display-lg max-w-3xl text-[2.1rem] leading-[1.05] sm:text-[2.5rem]">
            Watch an agent fail, then heal itself
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-muted-foreground">
            Five passes through the same three agents: a real failure, a one-line install,
            a logged rerun, an auto-dispatched fix, and a passing replay — the whole
            self-heal loop, one click at a time.
          </p>
        </div>

        <dl className="grid w-full grid-cols-3 gap-x-6 lg:w-auto">
          <MetricReadout label="Agents" value={3} />
          <MetricReadout label="Failures caught" value={3} />
          <MetricReadout label="Replays passing" value="100%" tone="signal" />
        </dl>
      </ConsolePageHeader>

      <ConsolePageContent className="flex flex-col gap-16 pt-4 sm:gap-20">
        <RunShowcase />
        <DemoPresentation />
      </ConsolePageContent>
    </ConsolePage>
  );
}

// ─── Run showcase (the LangSmith-style centerpiece) ───────────────────────────

type ShowcaseEvent = {
  seq: number;
  offset: number;
  type: string;
  lane: "browser" | "detector" | "sdk";
  text: string;
  evidence?: boolean;
  critical?: boolean;
};

const SHOWCASE_EVENTS: ShowcaseEvent[] = [
  { seq: 1, offset: 0, type: "user_message", lane: "sdk", text: "Book a 30-min slot with Dr. Rao for Tuesday 2:00 PM" },
  { seq: 2, offset: 240, type: "llm_call", lane: "sdk", text: "claude-opus-4 · plan_booking" },
  { seq: 3, offset: 980, type: "browser_action", lane: "browser", text: "click  [data-slot='tue-1600']" },
  { seq: 4, offset: 1520, type: "dom_snapshot", lane: "browser", text: "Selected: Tuesday 4:00 PM", evidence: true },
  { seq: 5, offset: 2100, type: "tool_call", lane: "sdk", text: "confirm_booking({ slot: 'tue-1600' })", evidence: true },
  { seq: 6, offset: 2360, type: "tool_result", lane: "sdk", text: "→ bk_44e1 confirmed" },
  { seq: 7, offset: 2610, type: "goal_check", lane: "detector", text: "failed · booked 16:00, requested 14:00", critical: true },
  { seq: 8, offset: 2680, type: "agent_message", lane: "sdk", text: "All set — you're booked for Tuesday!" },
];

const EVENT_ICON: Record<string, LucideIcon> = {
  user_message: MessageSquare,
  agent_message: Bot,
  llm_call: Sparkles,
  tool_call: Terminal,
  tool_result: Terminal,
  browser_action: CircleDot,
  dom_snapshot: CircleDot,
  goal_check: TriangleAlert,
};

const TYPE_TONE: Record<string, string> = {
  llm_call: "text-accent",
  tool_call: "text-accent",
  browser_action: "text-accent",
  dom_snapshot: "text-accent",
  goal_check: "text-destructive",
};

function fmtOffset(ms: number): string {
  return ms < 1000 ? `+${ms}ms` : `+${(ms / 1000).toFixed(2)}s`;
}

function RunShowcase() {
  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">
            Inside one run
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-foreground sm:text-[1.7rem]">
            The exact step Promptetheus catches
          </h2>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-warning/35 bg-warning/10 px-2.5 py-1 text-[11px] font-medium text-warning">
          <Radio className="size-3 animate-pulse" aria-hidden />
          live capture
        </span>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)]">
        <TraceStreamPanel />
        <VerdictPanel />
      </div>
    </section>
  );
}

function TraceStreamPanel() {
  return (
    <div className={cn("flex flex-col overflow-hidden", SURFACE)}>
      <div className={PANEL_HEADER}>
        <div className="flex items-center gap-2">
          <ListTree className="size-3.5 text-muted-foreground" aria-hidden />
          <span className="text-xs font-medium text-foreground">Trace stream</span>
          <span className="mono rounded bg-elevated px-1.5 py-0.5 text-[10px] text-muted-foreground">
            sess_8f2c…a91
          </span>
        </div>
        <span className="mono text-[10px] tabular-nums text-muted-foreground">
          {SHOWCASE_EVENTS.length} events · browser agent
        </span>
      </div>

      <ol className="divide-y divide-border/50">
        {SHOWCASE_EVENTS.map((event) => {
          const Icon = EVENT_ICON[event.type] ?? CircleDot;
          return (
            <li
              key={event.seq}
              className={cn(
                "flex items-start gap-2.5 px-3.5 py-2.5 transition-colors",
                event.critical
                  ? "bg-destructive/[0.07]"
                  : event.evidence
                    ? "bg-warning/[0.05]"
                    : "hover:bg-elevated/50",
              )}
            >
              <span className="mono mt-0.5 w-5 shrink-0 text-right text-[10px] tabular-nums text-muted-foreground/50">
                {event.seq}
              </span>
              <span className="mono mt-0.5 w-12 shrink-0 text-[10px] tabular-nums text-muted-foreground/50">
                {fmtOffset(event.offset)}
              </span>
              <Icon
                className={cn(
                  "mt-0.5 size-3.5 shrink-0",
                  event.critical
                    ? "text-destructive"
                    : (TYPE_TONE[event.type] ?? "text-muted-foreground"),
                )}
                aria-hidden
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "mono text-[11px] font-medium",
                      event.critical ? "text-destructive" : "text-foreground",
                    )}
                  >
                    {event.type}
                  </span>
                  {event.critical ? (
                    <span className="mono inline-flex items-center gap-0.5 rounded border border-destructive/30 bg-destructive/15 px-1 py-px text-[9px] leading-none text-destructive">
                      <Zap className="size-2.5" aria-hidden />
                      critical
                    </span>
                  ) : event.evidence ? (
                    <span className="mono rounded border border-warning/30 bg-warning/10 px-1 py-px text-[9px] leading-none text-warning">
                      evidence
                    </span>
                  ) : null}
                </div>
                <p className="mono mt-0.5 truncate text-[11px] text-muted-foreground">
                  {event.text}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

const EVIDENCE = [
  { seq: 4, label: "dom_snapshot", note: "Chosen slot resolved to 16:00" },
  { seq: 5, label: "tool_call", note: "confirm_booking sent tue-1600" },
  { seq: 7, label: "goal_check", note: "Requested 14:00 ≠ booked 16:00" },
];

function VerdictPanel() {
  return (
    <div className={cn("flex flex-col overflow-hidden", SURFACE)}>
      <div className={PANEL_HEADER}>
        <div className="flex items-center gap-2">
          <Crosshair className="size-3.5 text-accent" aria-hidden />
          <span className="text-xs font-medium text-foreground">Analysis verdict</span>
        </div>
      </div>

      <div className="flex flex-col gap-5 p-4">
        <div>
          <p className="micro text-muted-foreground">Root cause</p>
          <p className="mt-1.5 text-[13px] leading-6 text-foreground">
            The slot selector resolved to the{" "}
            <span className="font-semibold text-destructive">16:00</span> element. The agent
            confirmed the booking without verifying the chosen time against the requested{" "}
            <span className="font-semibold">14:00</span>, then reported success.
          </p>
        </div>

        <div>
          <div className="flex items-center justify-between">
            <p className="micro text-muted-foreground">Confidence</p>
            <span className="mono text-[11px] tabular-nums text-foreground">92%</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-elevated">
            <div className="h-full rounded-full bg-accent" style={{ width: "92%" }} />
          </div>
        </div>

        <div>
          <p className="micro text-muted-foreground">Evidence</p>
          <ul className="mt-1.5 flex flex-col gap-1.5">
            {EVIDENCE.map((item) => (
              <li
                key={item.seq}
                className="flex items-center gap-2 rounded-md border border-border/60 bg-elevated/40 px-2.5 py-1.5"
              >
                <span className="mono shrink-0 rounded bg-panel px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  #{item.seq}
                </span>
                <span className="mono text-[11px] text-accent">{item.label}</span>
                <span className="ml-auto truncate text-[11px] text-muted-foreground">
                  {item.note}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-md border border-border/60 bg-elevated/40 px-3 py-2">
          <p className="micro text-muted-foreground">Patch target</p>
          <p className="mono mt-1 text-[11px] text-foreground">
            browser/booking_agent.py · select_slot()
          </p>
        </div>

        <Button asChild size="sm" className="w-full">
          <a href="#run-the-loop">
            Run the self-heal loop
            <ArrowRight className="size-3.5" aria-hidden />
          </a>
        </Button>
      </div>
    </div>
  );
}
