"use client";

import * as React from "react";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import {
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Code2,
  Radio,
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
    id: "agents-pass",
    rail: "Pass",
    eyebrow: "Step 05 · Verify",
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
            Five passes, one click at a time
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
