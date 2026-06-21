"use client";

import * as React from "react";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  ArrowRight,
  Brain,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Code2,
  MessageSquare,
  Play,
  Radio,
  TriangleAlert,
  Waypoints,
  Wrench,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const SURFACE = "rounded-lg border border-border/70 bg-panel";

// ─── Tone system ──────────────────────────────────────────────────────────────

type Tone = "failed" | "install" | "streaming" | "fixing" | "passed";

const TONES: Record<
  Tone,
  { chip: string; solid: string; dot: string; icon: LucideIcon; glow: string }
> = {
  failed: {
    chip: "border-destructive/30 bg-destructive/10 text-destructive",
    solid: "border-destructive bg-destructive text-destructive-foreground",
    dot: "bg-destructive",
    icon: TriangleAlert,
    glow: "from-destructive/14",
  },
  install: {
    chip: "border-warning/35 bg-warning/10 text-warning",
    solid: "border-warning bg-warning text-warning-foreground",
    dot: "bg-warning",
    icon: Code2,
    glow: "from-warning/14",
  },
  streaming: {
    chip: "border-yellow-400/40 bg-yellow-400/10 text-yellow-500",
    solid: "border-yellow-400 bg-yellow-400 text-yellow-950",
    dot: "bg-yellow-400",
    icon: Radio,
    glow: "from-yellow-400/16",
  },
  fixing: {
    chip: "border-accent/30 bg-accent-muted/60 text-accent",
    solid: "border-accent bg-accent text-accent-foreground",
    dot: "bg-accent",
    icon: Wrench,
    glow: "from-accent/14",
  },
  passed: {
    chip: "border-success/35 bg-success/10 text-success",
    solid: "border-success bg-success text-success-foreground",
    dot: "bg-success",
    icon: CheckCircle2,
    glow: "from-success/14",
  },
};

// ─── Content ──────────────────────────────────────────────────────────────────

const agentTracks = [
  {
    key: "browser",
    label: "Browser Agent",
    icon: Waypoints,
    failed: "Books the wrong time slot and claims the task is complete.",
    install:
      "Add the Promptetheus decorator before the browser agent entrypoint.",
    streaming:
      "Rerun the browser agent while trace events stream into Promptetheus.",
    passed:
      "Books the requested slot after the fix and passes the replay check.",
  },
  {
    key: "voice",
    label: "Voice Agent",
    icon: Radio,
    failed: "Misses the escalation handoff after silence and user frustration.",
    install:
      "Wrap the voice agent so transcript, silence, and handoff events are captured.",
    streaming:
      "Rerun the call and stream transcript, latency, and tool-handoff logs.",
    passed:
      "Routes the escalation correctly and records a passing handoff replay.",
  },
  {
    key: "chat",
    label: "Chat Agent",
    icon: MessageSquare,
    failed:
      "Repeats stale advice and loops the customer back to the wrong step.",
    install:
      "Observe the chat agent so turns, tool calls, and outcomes are logged.",
    streaming: "Rerun the chat flow with live turn, tool, and outcome events.",
    passed: "Resolves the issue with the corrected prompt and tool context.",
  },
] as const;

const fixTracks = [
  {
    key: "fix-agent",
    label: "Fix Agent",
    icon: Brain,
    caption:
      "Packages the root cause, evidence, and patch target for the coding run.",
  },
  {
    key: "patch-agent",
    label: "Patch Agent",
    icon: Code2,
    caption:
      "Applies the suggested code or prompt change in a dedicated branch.",
  },
  {
    key: "regression-agent",
    label: "Regression Agent",
    icon: Activity,
    caption:
      "Replays the original bad step and confirms the behavior no longer regresses.",
  },
] as const;

/** A single trace line shown streaming into Promptetheus on the Observe step.
 *  The `error` lines mirror the matching failed runs on the /logs page. */
type DemoLogLine = { type: string; text: string; tone?: "error" };

/** Per-agent log rotations for the Observe step. Each agent cycles through its
 *  own distinct entries, drawn from that agent's real runs in data/events.json:
 *  the browser agent's many wrong-slot / policy failures, the voice agent's
 *  refund-cancellation miss, the chat agent's refund-policy contradiction. The
 *  `error` lines are verbatim from the /logs page; keep in sync. */
const OBSERVE_LOGS: Record<string, DemoLogLine[]> = {
  browser: [
    {
      type: "goal_check",
      text: "Requested time 2:00 PM but selected 2:00 AM (12-hour mismatch).",
      tone: "error",
    },
    {
      type: "goal_check",
      text: "Requested Eastern timezone; booked in Pacific (3 hour offset).",
      tone: "error",
    },
    {
      type: "goal_check",
      text: "Requested refundable ticket but selected ticket is non-refundable.",
      tone: "error",
    },
    {
      type: "error",
      text: "Guardrail triggered: destructive action 'Delete workspace' blocked.",
      tone: "error",
    },
    {
      type: "error",
      text: "Policy violation: user said 'do not purchase' but agent advanced to payment confirmation.",
      tone: "error",
    },
  ],
  voice: [
    {
      type: "tool_call",
      text: "get_order_status(order_id='48192') → cancellable: true",
    },
    { type: "user_message", text: "“No, cancel it. I don't want the status.”" },
    { type: "score", text: "user_sentiment = -0.72" },
    {
      type: "goal_check",
      text: "User requested cancellation, but cancel_order and issue_refund were never called.",
      tone: "error",
    },
    {
      type: "session_end",
      text: "status failed · false_success_detected",
      tone: "error",
    },
  ],
  chat: [
    {
      type: "tool_call",
      text: "orders.lookup(order_id='88241') → apparel, delivered",
    },
    { type: "retrieval", text: "refund policy · apparel return window" },
    { type: "score", text: "policy_grounding = 0.18" },
    {
      type: "goal_check",
      text: "Agent said non-refundable; policy says apparel is refundable within 30 days (order is 9 days old).",
      tone: "error",
    },
  ],
};

type DemoCard = {
  agent: string;
  icon: LucideIcon;
  caption: string;
  /** Real recording source, when one exists for this step. */
  video?: string;
  /** When false, the recording plays with sound (voice agent). Defaults to muted. */
  muted?: boolean;
  /** Trace lines that animate into Promptetheus beneath the media (Observe step). */
  logs?: DemoLogLine[];
  tone: Tone;
};

type DemoSection = {
  id: string;
  rail: string;
  eyebrow: string;
  title: string;
  body: string;
  tone: Tone;
  /** When set, the step's CTA advances the deck to this slide index. */
  cta?: { label: string; target: number };
  cards: DemoCard[];
};

const SECTIONS: DemoSection[] = [
  {
    id: "agents-fail",
    rail: "Fail",
    eyebrow: "Step 01 · Baseline",
    title: "Agents fail in production",
    body: "Three agent recordings show real task failures before Promptetheus is installed — silent, hard to reproduce, easy to ship.",
    tone: "failed",
    cards: agentTracks.map((agent) => ({
      agent: agent.label,
      icon: agent.icon,
      caption: agent.failed,
      video: `/assets/demo-agents/${agent.key}-fail.webm`,
      muted: agent.key !== "voice",
      tone: "failed",
    })),
  },
  {
    id: "install-promptetheus",
    rail: "Install",
    eyebrow: "Step 02 · Instrument",
    title: "Install Promptetheus",
    body: "The same three agents get a lightweight wrapper before their entrypoint — one decorator, no framework lock-in.",
    tone: "install",
    cards: agentTracks.map((agent) => ({
      agent: agent.label,
      icon: agent.icon,
      caption: agent.install,
      tone: "install",
    })),
  },
  {
    id: "rerun-with-logs",
    rail: "Observe",
    eyebrow: "Step 03 · Observe",
    title: "Rerun with logs streaming",
    body: "The failures still happen — but now every step streams into Promptetheus, and the detector flags the exact bad move.",
    tone: "streaming",
    cta: { label: "Dispatch the fixes", target: 3 },
    cards: agentTracks.map((agent) => ({
      agent: agent.label,
      icon: agent.icon,
      caption: agent.streaming,
      // Same recording as the Fail step — the failure still happens on rerun.
      video: `/assets/demo-agents/${agent.key}-fail.webm`,
      muted: agent.key !== "voice",
      logs: OBSERVE_LOGS[agent.key],
      tone: "streaming",
    })),
  },
  {
    id: "dispatch-fixes",
    rail: "Heal",
    eyebrow: "Step 04 · Heal",
    title: "Dispatch the fixes",
    body: "The incident hands off to coding agents without leaving the demo: brief, patch, and replay run end to end.",
    tone: "fixing",
    cta: { label: "See them pass", target: 4 },
    cards: fixTracks.map((agent) => ({
      agent: agent.label,
      icon: agent.icon,
      caption: agent.caption,
      tone: "fixing",
    })),
  },
  {
    id: "agents-pass",
    rail: "Pass",
    eyebrow: "Step 05 · Verify",
    title: "Agents pass after the fix",
    body: "Back to the original three agents — the corrected runs pass, and the replay check confirms the failure is gone.",
    tone: "passed",
    cards: agentTracks.map((agent) => ({
      agent: agent.label,
      icon: agent.icon,
      caption: agent.passed,
      video: `/assets/demo-agents/${agent.key}-pass.webm`,
      muted: agent.key !== "voice",
      tone: "passed",
    })),
  },
];

// ─── Presentation ─────────────────────────────────────────────────────────────

const STEP_MS = 10000;

export function DemoPresentation() {
  const [active, setActive] = React.useState(0);
  const total = SECTIONS.length;

  const goTo = React.useCallback(
    (index: number) => {
      setActive(Math.max(0, Math.min(total - 1, index)));
    },
    [total],
  );

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight") goTo(active + 1);
      else if (event.key === "ArrowLeft") goTo(active - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, goTo]);

  // Auto-advance every STEP_MS, looping. Resets whenever `active` changes, so
  // manual navigation restarts the countdown from the current step.
  React.useEffect(() => {
    const id = window.setTimeout(() => {
      setActive((current) => (current + 1) % total);
    }, STEP_MS);
    return () => window.clearTimeout(id);
  }, [active, total]);

  const section = SECTIONS[active];

  return (
    <section
      id="run-the-loop"
      aria-label="Self-heal loop walkthrough"
      className="scroll-mt-8"
    >
      {/* Section heading */}
      <div className="mb-8 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">
            The self-heal loop
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-foreground sm:text-[1.7rem]">
            Five passes, one click at a time
          </h2>
        </div>
        <div className="flex items-center gap-3">
          <CountdownRing stepKey={active} />
          <div className="flex items-center gap-1.5">
            <NavButton
              direction="prev"
              disabled={active === 0}
              onClick={() => goTo(active - 1)}
            />
            <NavButton
              direction="next"
              disabled={active === total - 1}
              onClick={() => goTo(active + 1)}
            />
          </div>
        </div>
      </div>

      {/* Step rail */}
      <StepRail sections={SECTIONS} active={active} onSelect={goTo} />

      {/* Stage */}
      <div className={cn("mt-8 overflow-hidden p-6 sm:p-10", SURFACE)}>
        <div key={active}>
          <div className="flex animate-materialize flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
            <div className="min-w-0">
              <p className="mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">
                {section.eyebrow}
              </p>
              <h3 className="mt-1.5 text-2xl font-semibold text-foreground">
                {section.title}
              </h3>
              <p className="mt-3 max-w-2xl text-[15px] leading-7 text-muted-foreground">
                {section.body}
              </p>
            </div>
            {section.cta ? (
              <Button
                size="sm"
                className="shrink-0"
                onClick={() => goTo(section.cta!.target)}
              >
                {section.cta.label}
                <ArrowRight className="size-3.5" aria-hidden />
              </Button>
            ) : null}
          </div>

          <div className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-3">
            {section.cards.map((card, index) => (
              <div
                key={`${section.id}-${card.agent}`}
                style={{ animationDelay: `${120 + index * 120}ms` }}
                className="animate-materialize"
              >
                <AgentMediaCard card={card} index={index} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

// ─── Pieces ───────────────────────────────────────────────────────────────────

/** Small radial countdown — the stroke fills its circumference over `duration`,
 *  restarting each time `stepKey` changes. No numeric readout. */
function CountdownRing({
  stepKey,
  duration = STEP_MS,
  size = 22,
  stroke = 2.5,
}: {
  stepKey: number;
  duration?: number;
  size?: number;
  stroke?: number;
}) {
  const radius = (size - stroke) / 2;
  const circ = 2 * Math.PI * radius;
  const [run, setRun] = React.useState(false);

  React.useEffect(() => {
    setRun(false);
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => setRun(true));
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
  }, [stepKey]);

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="-rotate-90"
      role="img"
      aria-label="Time until next step"
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={stroke}
        className="stroke-border"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={stroke}
        strokeLinecap="round"
        className="stroke-accent"
        style={{
          strokeDasharray: circ,
          strokeDashoffset: run ? 0 : circ,
          transition: run ? `stroke-dashoffset ${duration}ms linear` : "none",
        }}
      />
    </svg>
  );
}

function NavButton({
  direction,
  disabled,
  onClick,
}: {
  direction: "prev" | "next";
  disabled: boolean;
  onClick: () => void;
}) {
  const Icon = direction === "prev" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={direction === "prev" ? "Previous step" : "Next step"}
      className={cn(
        "flex size-9 items-center justify-center rounded-md border border-border/70 bg-panel text-foreground transition-colors",
        "hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-panel",
      )}
    >
      <Icon className="size-4" aria-hidden />
    </button>
  );
}

function StepRail({
  sections,
  active,
  onSelect,
}: {
  sections: DemoSection[];
  active: number;
  onSelect: (index: number) => void;
}) {
  return (
    <nav aria-label="Demo steps" className="overflow-x-auto pb-1">
      <ol className="flex min-w-max items-center gap-1">
        {sections.map((section, index) => {
          const tone = TONES[section.tone];
          const done = index < active;
          const current = index === active;
          const Icon = tone.icon;
          return (
            <li key={section.id} className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onSelect(index)}
                aria-current={current}
                className={cn(
                  "group flex items-center gap-2.5 rounded-lg px-3 py-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  current ? "bg-elevated" : "hover:bg-elevated/60",
                )}
              >
                <span
                  className={cn(
                    "flex size-7 items-center justify-center rounded-full border text-[11px] font-semibold transition-colors",
                    current || done
                      ? tone.solid
                      : "border-border-strong/60 text-muted-foreground",
                  )}
                >
                  {done ? (
                    <Check className="size-3.5" aria-hidden />
                  ) : current ? (
                    <Icon className="size-3.5" aria-hidden />
                  ) : (
                    index + 1
                  )}
                </span>
                <span
                  className={cn(
                    "hidden text-xs font-medium transition-colors sm:inline",
                    current ? "text-foreground" : "text-muted-foreground",
                  )}
                >
                  {section.rail}
                </span>
              </button>
              {index < sections.length - 1 ? (
                <span
                  aria-hidden
                  className={cn(
                    "h-px w-5 shrink-0 transition-colors sm:w-8",
                    done ? "bg-accent/60" : "bg-border/70",
                  )}
                />
              ) : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function AgentMediaCard({
  card,
  index = 0,
}: {
  card: DemoCard;
  index?: number;
}) {
  const tone = TONES[card.tone];
  const AgentIcon = card.icon;
  const muted = card.muted ?? true;
  const videoRef = React.useRef<HTMLVideoElement>(null);

  // React doesn't reliably reflect the `muted` prop onto the DOM property, so
  // set it explicitly. The voice agent recordings are meant to play with sound.
  React.useEffect(() => {
    if (videoRef.current) videoRef.current.muted = muted;
  }, [muted]);

  return (
    <article className="group mx-auto flex w-full max-w-[19rem] flex-col gap-3">
      <div className="flex items-center gap-2">
        <AgentIcon
          className="size-4 shrink-0 text-muted-foreground"
          aria-hidden
        />
        <h4 className="truncate text-sm font-semibold text-foreground">
          {card.agent}
        </h4>
      </div>

      {/* Vertical 9:16 media frame */}
      <div
        className={cn(
          "relative aspect-[9/16] overflow-hidden transition-transform duration-300 group-hover:-translate-y-1",
          SURFACE,
        )}
      >
        {card.video ? (
          <video
            ref={videoRef}
            className="absolute inset-0 size-full object-cover"
            src={card.video}
            autoPlay
            muted={muted}
            loop
            playsInline
            preload="auto"
            aria-label={`${card.agent} recording`}
          />
        ) : (
          <div
            role="img"
            aria-label={`${card.agent} recording placeholder`}
            className="absolute inset-0 flex items-center justify-center"
          >
            <div
              aria-hidden
              className={cn(
                "absolute inset-0 bg-gradient-to-b via-transparent to-transparent",
                tone.glow,
              )}
            />
            <div
              aria-hidden
              className="absolute inset-0 grid-fade opacity-40"
            />
            <span className="relative flex size-14 items-center justify-center rounded-full border border-border/70 bg-panel/90 text-foreground shadow-sm transition-transform duration-200 group-hover:scale-110">
              <Play
                className="size-6 translate-x-0.5 fill-current"
                aria-hidden
              />
            </span>
          </div>
        )}
      </div>

      <p className="text-[13px] leading-6 text-muted-foreground">
        {card.caption}
      </p>

      {card.logs ? (
        <ErrorLogTicker entries={card.logs} offsetMs={index * 700} />
      ) : null}
    </article>
  );
}

/** Persists each ticker's rotation index across remounts, keyed by its (stable)
 *  entries array, so the Observe step keeps cycling rather than restarting. */
const tickerProgress = new WeakMap<DemoLogLine[], number>();

/** A slow vertical ticker of trace lines streaming into Promptetheus beneath the
 *  Observe recordings. One entry is shown at a time; every ~5s the next entry
 *  scrolls up into view (no stacking). Each agent cycles its own distinct set,
 *  and `error` entries — verbatim from the /logs page — are highlighted. The
 *  `offsetMs` stagger keeps the three cards from ticking in lockstep. */
function ErrorLogTicker({
  entries,
  offsetMs = 0,
}: {
  entries: DemoLogLine[];
  offsetMs?: number;
}) {
  // Remember each agent's place in its rotation across remounts (the deck
  // auto-advances and remounts every step), so the rotation keeps progressing
  // through the different entries instead of restarting at the first one.
  const [index, setIndex] = React.useState(
    () => tickerProgress.get(entries) ?? 0,
  );

  React.useEffect(() => {
    let interval: number | undefined;
    const start = window.setTimeout(() => {
      interval = window.setInterval(() => {
        setIndex((current) => {
          const next = (current + 1) % entries.length;
          tickerProgress.set(entries, next);
          return next;
        });
      }, 2600);
    }, offsetMs);
    return () => {
      window.clearTimeout(start);
      if (interval !== undefined) window.clearInterval(interval);
    };
  }, [entries, offsetMs]);

  const entry = entries[index];
  const isError = entry.tone === "error";

  return (
    <div
      className={cn(
        "overflow-hidden shadow-sm ring-1 transition-colors",
        SURFACE,
        isError ? "ring-destructive/40" : "ring-transparent",
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border/60 bg-elevated/50 px-3 py-2">
        <div className="flex items-center gap-2">
          <Radio
            className="size-3.5 animate-pulse text-yellow-500"
            aria-hidden
          />
          <span className="mono text-[11px] font-semibold uppercase tracking-[0.14em] text-foreground">
            Streaming into Promptetheus
          </span>
        </div>
        <span className="mono text-[10px] font-medium tabular-nums text-muted-foreground">
          {index + 1}/{entries.length}
        </span>
      </div>

      {/* Single-entry viewport — each new entry scrolls up into place. */}
      <div
        className={cn(
          "relative min-h-[4.25rem] overflow-hidden border-l-2 px-3 py-2.5 transition-colors",
          isError
            ? "border-l-destructive bg-destructive/[0.08]"
            : "border-l-transparent",
        )}
      >
        <div key={index} className="flex animate-ticker-up items-start gap-2.5">
          {isError ? (
            <TriangleAlert
              className="mt-0.5 size-4 shrink-0 text-destructive"
              aria-hidden
            />
          ) : (
            <span
              aria-hidden
              className="mt-1.5 size-2 shrink-0 rounded-full bg-muted-foreground/50"
            />
          )}
          <div className="min-w-0 flex-1">
            <span
              className={cn(
                "mono text-[11px] font-semibold uppercase tracking-wide",
                isError ? "text-destructive" : "text-muted-foreground/80",
              )}
            >
              {entry.type}
            </span>
            <p
              className={cn(
                "mono mt-0.5 text-[13px] leading-5",
                isError ? "font-medium text-destructive" : "text-foreground/80",
              )}
            >
              {entry.text}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
