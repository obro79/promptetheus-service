"use client";

import * as React from "react";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import {
  ArrowRight,
  Brain,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Code2,
  Database,
  GitPullRequest,
  Network,
  Radio,
  Sparkles,
  TriangleAlert,
  Wrench,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const SURFACE = "rounded-lg border border-border/70 bg-panel";

type Tone = "failed" | "install" | "streaming" | "fixing" | "passed";

const TONES: Record<Tone, { solid: string; icon: LucideIcon }> = {
  failed: {
    solid: "border-destructive bg-destructive text-destructive-foreground",
    icon: TriangleAlert,
  },
  install: {
    solid: "border-warning bg-warning text-warning-foreground",
    icon: Code2,
  },
  streaming: {
    solid: "border-yellow-400 bg-yellow-400 text-yellow-950",
    icon: Radio,
  },
  fixing: {
    solid: "border-accent bg-accent text-accent-foreground",
    icon: Wrench,
  },
  passed: {
    solid: "border-success bg-success text-success-foreground",
    icon: CheckCircle2,
  },
};

type DemoSection = {
  id: string;
  rail: string;
  eyebrow: string;
  title: string;
  body: string;
  tone: Tone;
  /** Custom stage renderer key. When set, adds extra content below the copy. */
  render?: "memory";
};

const SECTIONS: DemoSection[] = [
  {
    id: "agents-fail",
    rail: "Fail",
    eyebrow: "Step 01 · Baseline",
    title: "Agents fail in production",
    body: "Three production agents hit real failures before Promptetheus is installed. Use the walkthrough controls to move through the loop manually.",
    tone: "failed",
  },
  {
    id: "install-promptetheus",
    rail: "Install",
    eyebrow: "Step 02 · Instrument",
    title: "Install Promptetheus",
    body: "Add the lightweight wrapper before each agent entrypoint so runs, tool calls, outcomes, and artifacts can be observed.",
    tone: "install",
  },
  {
    id: "rerun-with-logs",
    rail: "Observe",
    eyebrow: "Step 03 · Observe",
    title: "Rerun with logs streaming",
    body: "Rerun the workflows with instrumentation active, then inspect the trace events and failure signals on the logs page.",
    tone: "streaming",
  },
  {
    id: "dispatch-fixes",
    rail: "Heal",
    eyebrow: "Step 04 · Heal",
    title: "Dispatch the fixes",
    body: "The incident bundle gives the fix agent the root cause, evidence, and replay target needed to open a verified patch.",
    tone: "fixing",
  },
  {
    id: "redis-memory",
    rail: "Recall",
    eyebrow: "Step 05 · Recall",
    title: "Redis remembers what worked",
    body: "Every verified fix is embedded into a Redis 8 Vector Set. When a new incident arrives, VSIM clusters it with past failures and packs the nearest fixes into the context packet handed to Devin.",
    tone: "fixing",
    render: "memory",
  },
  {
    id: "agents-pass",
    rail: "Pass",
    eyebrow: "Step 06 · Verify",
    title: "Agents pass after the fix",
    body: "The corrected runs pass, and the replay check confirms the original failure no longer regresses.",
    tone: "passed",
  },
];

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
      if (event.key === "ArrowRight") {
        goTo(active + 1);
      } else if (event.key === "ArrowLeft") {
        goTo(active - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, goTo]);

  const section = SECTIONS[active];

  return (
    <section
      id="run-the-loop"
      aria-label="Self-heal loop walkthrough"
      className="scroll-mt-8"
    >
      <div className="mb-8 flex flex-col gap-5">
        <div>
          <p className="mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">
            The self-heal loop
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-foreground sm:text-[1.7rem]">
            Six passes, one click at a time
          </h2>
        </div>
      </div>

      <StepRail sections={SECTIONS} active={active} onSelect={goTo} />

      <div className={cn("mt-8 overflow-hidden p-6 sm:p-10", SURFACE)}>
        <div key={section.id} className="animate-materialize">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
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
            <Button asChild className="min-h-11 shrink-0">
              <Link href="/logs">
                Open logs page
                <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            </Button>
          </div>

          {section.render === "memory" ? <MemoryStage /> : null}

          <div className="mt-8 flex justify-end">
            <div className="flex items-center gap-1.5 rounded-xl border border-border/70 bg-panel/80 p-1.5 shadow-sm">
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
      </div>
    </section>
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
        "flex size-11 items-center justify-center rounded-lg border border-border/70 bg-panel text-foreground transition-colors",
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

// ─── Memory stage (Step 05 · Recall) ────────────────────────────────────────────
// A custom stage that visualizes the Redis-backed heal loop: verified fixes are
// embedded into a Redis 8 Vector Set (VADD), a new incident is clustered against
// them (VSIM), and the nearest fixes are packed into the context packet sent to
// Devin. Pure SVG + Tailwind, no data fetch — it mirrors scripts/visualize_clusters.py.

type ClusterShape = "square" | "circle" | "triangle";

type ClusterDef = {
  label: string;
  shape: ClusterShape;
  color: string;
  /** Dashed hull ellipse around the cluster. */
  hull: { cx: number; cy: number; rx: number; ry: number };
  points: { x: number; y: number }[];
};

const CLUSTERS: ClusterDef[] = [
  {
    label: "browser_goal_mismatch",
    shape: "square",
    color: "#ef4444",
    hull: { cx: 78, cy: 66, rx: 46, ry: 40 },
    points: [
      { x: 56, y: 50 },
      { x: 88, y: 44 },
      { x: 70, y: 74 },
      { x: 98, y: 70 },
      { x: 52, y: 82 },
    ],
  },
  {
    label: "ignored_ui_warning",
    shape: "circle",
    color: "#3b82f6",
    hull: { cx: 84, cy: 176, rx: 50, ry: 38 },
    points: [
      { x: 60, y: 162 },
      { x: 96, y: 166 },
      { x: 74, y: 192 },
      { x: 108, y: 188 },
      { x: 56, y: 184 },
    ],
  },
  {
    label: "false_success_claim",
    shape: "triangle",
    color: "#22c55e",
    hull: { cx: 234, cy: 138, rx: 52, ry: 56 },
    points: [
      { x: 214, y: 110 },
      { x: 248, y: 120 },
      { x: 224, y: 146 },
      { x: 258, y: 150 },
      { x: 232, y: 174 },
    ],
  },
];

/** The incoming incident under triage, plus its nearest neighbours from VSIM. */
const NEW_INCIDENT = { x: 124, y: 58 };
const VSIM_NEIGHBOURS = [
  { x: 98, y: 70 },
  { x: 88, y: 44 },
  { x: 70, y: 74 },
];

const HEAL_LOOP: { label: string; sub: string; icon: LucideIcon }[] = [
  { label: "remember_fix", sub: "VADD", icon: Database },
  { label: "find_similar", sub: "VSIM", icon: Network },
  { label: "warm-start", sub: "context", icon: Sparkles },
  { label: "Devin", sub: "session", icon: Brain },
  { label: "open PR", sub: "verified", icon: GitPullRequest },
];

const PACKET_FIXES = [
  { id: "inc-email-001", label: "missing_capability", score: 0.967, best: true },
  { id: "inc-slot-014", label: "browser_goal_mismatch", score: 0.842, best: false },
  { id: "inc-warn-073", label: "ignored_ui_warning", score: 0.799, best: false },
];

function ClusterGlyph({
  shape,
  x,
  y,
  color,
  opacity = 1,
}: {
  shape: ClusterShape;
  x: number;
  y: number;
  color: string;
  opacity?: number;
}) {
  if (shape === "circle") {
    return <circle cx={x} cy={y} r={5.5} fill={color} opacity={opacity} />;
  }
  if (shape === "triangle") {
    return (
      <polygon
        points={`${x},${y - 6} ${x + 6},${y + 5} ${x - 6},${y + 5}`}
        fill={color}
        opacity={opacity}
      />
    );
  }
  return (
    <rect x={x - 5} y={y - 5} width={10} height={10} rx={1.5} fill={color} opacity={opacity} />
  );
}

function ClusterMap() {
  return (
    <div className={cn("flex flex-col", SURFACE)}>
      <div className="flex items-center justify-between border-b border-border/70 px-4 py-3">
        <div className="flex items-center gap-2">
          <Network className="size-4 text-accent" aria-hidden />
          <span className="mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            Redis 8 Vector Set · ptvec
          </span>
        </div>
        <span className="mono text-[10px] text-muted-foreground/70">VSIM · cosine</span>
      </div>

      <div className="relative">
        <svg viewBox="0 0 320 240" className="h-auto w-full" role="img" aria-label="Incident clusters in the Redis vector set">
          {/* Cluster hulls */}
          {CLUSTERS.map((c) => (
            <ellipse
              key={`hull-${c.label}`}
              cx={c.hull.cx}
              cy={c.hull.cy}
              rx={c.hull.rx}
              ry={c.hull.ry}
              fill={c.color}
              fillOpacity={0.06}
              stroke={c.color}
              strokeOpacity={0.4}
              strokeWidth={1}
              strokeDasharray="4 4"
            />
          ))}

          {/* VSIM edges from the new incident to its nearest neighbours */}
          {VSIM_NEIGHBOURS.map((n, i) => (
            <line
              key={`edge-${i}`}
              x1={NEW_INCIDENT.x}
              y1={NEW_INCIDENT.y}
              x2={n.x}
              y2={n.y}
              stroke="#8b5cf6"
              strokeWidth={1.25}
              strokeDasharray="3 3"
              className="animate-pulse"
            />
          ))}

          {/* Cluster points */}
          {CLUSTERS.map((c) =>
            c.points.map((p, i) => (
              <ClusterGlyph key={`${c.label}-${i}`} shape={c.shape} x={p.x} y={p.y} color={c.color} />
            )),
          )}

          {/* New incident under triage */}
          <circle cx={NEW_INCIDENT.x} cy={NEW_INCIDENT.y} r={11} fill="#8b5cf6" fillOpacity={0.18} className="animate-ping" />
          <circle cx={NEW_INCIDENT.x} cy={NEW_INCIDENT.y} r={6} fill="#8b5cf6" stroke="white" strokeWidth={1.5} />
        </svg>

        <span className="mono absolute left-[39%] top-[14%] rounded border border-accent/40 bg-accent-muted/70 px-1.5 py-0.5 text-[9px] font-semibold text-accent">
          new incident
        </span>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-2 border-t border-border/70 px-4 py-3">
        {CLUSTERS.map((c) => (
          <div key={`legend-${c.label}`} className="flex items-center gap-1.5">
            <svg width={12} height={12} viewBox="0 0 12 12" aria-hidden>
              <ClusterGlyph shape={c.shape} x={6} y={6} color={c.color} />
            </svg>
            <span className="mono text-[10px] text-muted-foreground">{c.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ContextPacket() {
  return (
    <div className={cn("flex flex-col", SURFACE)}>
      <div className="flex items-center justify-between border-b border-border/70 px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-accent" aria-hidden />
          <span className="mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            context_packet → Devin
          </span>
        </div>
        <span className="mono text-[10px] text-muted-foreground/70">top-k = 3</span>
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="rounded-md border border-border/60 bg-elevated/40 px-3 py-2">
          <p className="mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/70">
            root_cause
          </p>
          <p className="mt-1 text-[12px] leading-5 text-foreground">
            agent invoked email.send but no such tool was registered (missing capability)
          </p>
        </div>

        <div>
          <p className="mono mb-1.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground/70">
            similar_fixes · VSIM
          </p>
          <div className="flex flex-col gap-1.5">
            {PACKET_FIXES.map((fix) => (
              <div
                key={fix.id}
                className={cn(
                  "flex items-center justify-between rounded-md border px-2.5 py-1.5",
                  fix.best
                    ? "border-accent/40 bg-accent-muted/50"
                    : "border-border/60 bg-panel",
                )}
              >
                <div className="flex min-w-0 items-center gap-2">
                  {fix.best ? (
                    <Sparkles className="size-3.5 shrink-0 text-accent" aria-hidden />
                  ) : (
                    <Wrench className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  )}
                  <span className="mono truncate text-[11px] text-foreground">{fix.id}</span>
                  <span className="mono hidden text-[10px] text-muted-foreground sm:inline">
                    {fix.label}
                  </span>
                </div>
                <span
                  className={cn(
                    "mono shrink-0 text-[11px] font-semibold tabular-nums",
                    fix.best ? "text-accent" : "text-muted-foreground",
                  )}
                >
                  {fix.score.toFixed(3)}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-md border border-border/60 bg-elevated/40 px-3 py-2">
          <p className="mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/70">
            allowed_paths
          </p>
          <p className="mono mt-1 text-[12px] text-foreground">agents/</p>
        </div>

        <div className="mt-auto flex items-center gap-2 rounded-md border border-accent/30 bg-accent-muted/40 px-3 py-2">
          <Brain className="size-4 text-accent" aria-hidden />
          <span className="text-[12px] text-foreground">
            Dispatched to <span className="font-semibold">Devin</span> with{" "}
            <span className="mono text-accent">similar_fix_count = 3</span>
          </span>
        </div>
      </div>
    </div>
  );
}

/** Compact horizontal ribbon of the Redis-backed heal loop stages. */
function HealLoopRibbon() {
  return (
    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-2">
      {HEAL_LOOP.map((stage, i) => {
        const Icon = stage.icon;
        return (
          <React.Fragment key={stage.label}>
            <div className="flex items-center gap-2 rounded-lg border border-border/70 bg-panel px-2.5 py-1.5">
              <span className="flex size-6 items-center justify-center rounded-md border border-accent/30 bg-accent-muted/50 text-accent">
                <Icon className="size-3.5" aria-hidden />
              </span>
              <span className="flex flex-col leading-tight">
                <span className="mono text-[11px] font-medium text-foreground">{stage.label}</span>
                <span className="mono text-[9px] uppercase tracking-[0.12em] text-muted-foreground/70">
                  {stage.sub}
                </span>
              </span>
            </div>
            {i < HEAL_LOOP.length - 1 ? (
              <ArrowRight className="size-3.5 shrink-0 text-muted-foreground/50" aria-hidden />
            ) : null}
          </React.Fragment>
        );
      })}
    </div>
  );
}

export function MemoryStage() {
  return (
    <div className="mt-8 flex flex-col gap-6 animate-materialize">
      <HealLoopRibbon />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <ClusterMap />
        <ContextPacket />
      </div>
    </div>
  );
}
