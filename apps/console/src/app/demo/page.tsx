import {
  Activity,
  CheckCircle2,
  Code2,
  Radio,
  TriangleAlert,
  Wrench,
} from "lucide-react";

import {
  LandingAppShell,
  LandingCard,
  LandingSection,
  SectionHeader,
} from "@/components/landing/landing-primitives";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type DemoCard = {
  agent: string;
  caption: string;
  mediaPath: string;
  stateLabel: string;
  tone: "failed" | "install" | "streaming" | "fixing" | "passed";
};

type DemoSection = {
  id: string;
  eyebrow: string;
  title: string;
  body: string;
  cta?: {
    href: string;
    label: string;
  };
  cards: DemoCard[];
};

const agentTracks = [
  {
    key: "browser",
    label: "Browser Agent",
    failed: "Books the wrong time slot and claims the task is complete.",
    install: "Add the Promptetheus decorator before the browser agent entrypoint.",
    streaming: "Rerun the browser agent while trace events stream into Promptetheus.",
    passed: "Books the requested slot after the fix and passes the replay check.",
  },
  {
    key: "voice",
    label: "Voice Agent",
    failed: "Misses the escalation handoff after silence and user frustration.",
    install: "Wrap the voice agent so transcript, silence, and handoff events are captured.",
    streaming: "Rerun the call and stream transcript, latency, and tool-handoff logs.",
    passed: "Routes the escalation correctly and records a passing handoff replay.",
  },
  {
    key: "chat",
    label: "Chat Agent",
    failed: "Repeats stale advice and loops the customer back to the wrong step.",
    install: "Observe the chat agent so turns, tool calls, and outcomes are logged.",
    streaming: "Rerun the chat flow with live turn, tool, and outcome events.",
    passed: "Resolves the issue with the corrected prompt and tool context.",
  },
] as const;

const fixTracks = [
  {
    key: "fix-agent",
    label: "Fix Agent",
    caption: "Packages the root cause, evidence, and patch target for the coding run.",
  },
  {
    key: "patch-agent",
    label: "Patch Agent",
    caption: "Applies the suggested code or prompt change in a dedicated branch.",
  },
  {
    key: "regression-agent",
    label: "Regression Agent",
    caption: "Replays the original bad step and confirms the behavior no longer regresses.",
  },
] as const;

const demoSections: DemoSection[] = [
  {
    id: "agents-fail",
    eyebrow: "Step 01",
    title: "Agents fail in production",
    body: "Start with three agent recordings that show real task failures before Promptetheus is installed.",
    cards: agentTracks.map((agent) => ({
      agent: agent.label,
      caption: agent.failed,
      mediaPath: `/demo-recordings/${agent.key}-failed.mp4`,
      stateLabel: "failed run",
      tone: "failed",
    })),
  },
  {
    id: "install-promptetheus",
    eyebrow: "Step 02",
    title: "Install Promptetheus",
    body: "The same three agents get a lightweight wrapper before their entrypoint.",
    cards: agentTracks.map((agent) => ({
      agent: agent.label,
      caption: agent.install,
      mediaPath: `/demo-recordings/${agent.key}-install.mp4`,
      stateLabel: "decorator added",
      tone: "install",
    })),
  },
  {
    id: "rerun-with-logs",
    eyebrow: "Step 03",
    title: "Rerun with logs streaming",
    body: "The failures still happen, but this time the page shows the logs that Promptetheus would capture.",
    cta: {
      href: "#dispatch-fixes",
      label: "Dispatch fixes",
    },
    cards: agentTracks.map((agent) => ({
      agent: agent.label,
      caption: agent.streaming,
      mediaPath: `/demo-recordings/${agent.key}-logged-rerun.mp4`,
      stateLabel: "logs streaming",
      tone: "streaming",
    })),
  },
  {
    id: "dispatch-fixes",
    eyebrow: "Step 04",
    title: "Dispatch the fixes",
    body: "A fake in-page dashboard handoff moves the case into coding-agent work without leaving the demo.",
    cards: fixTracks.map((agent) => ({
      agent: agent.label,
      caption: agent.caption,
      mediaPath: `/demo-recordings/${agent.key}.mp4`,
      stateLabel: "fix in progress",
      tone: "fixing",
    })),
  },
  {
    id: "agents-pass",
    eyebrow: "Step 05",
    title: "Agents pass after the fix",
    body: "Return to the original three agent recordings and show the corrected runs passing.",
    cards: agentTracks.map((agent) => ({
      agent: agent.label,
      caption: agent.passed,
      mediaPath: `/demo-recordings/${agent.key}-passed.mp4`,
      stateLabel: "passed replay",
      tone: "passed",
    })),
  },
];

const toneStyles: Record<DemoCard["tone"], { label: string; icon: typeof Activity }> = {
  failed: {
    label: "border-destructive/35 bg-destructive/10 text-destructive",
    icon: TriangleAlert,
  },
  install: {
    label: "border-accent/30 bg-accent-muted/60 text-accent",
    icon: Code2,
  },
  streaming: {
    label: "border-warning/35 bg-warning/10 text-warning",
    icon: Radio,
  },
  fixing: {
    label: "border-accent/30 bg-accent-muted/60 text-accent",
    icon: Wrench,
  },
  passed: {
    label: "border-success/35 bg-success/10 text-success",
    icon: CheckCircle2,
  },
};

export default function DemoPage() {
  return (
    <LandingAppShell>
      <main>
        <LandingSection
          className="pt-12 sm:pt-16 lg:pt-20"
          containerClassName="landing-use-case-container"
          density="compact"
        >
          <div className="mx-auto max-w-4xl text-center">
            <p className="landing-eyebrow">Demo scaffold</p>
            <h1 className="landing-display-xl text-foreground">
              Five passes through the same three agents
            </h1>
            <p className="landing-copy mx-auto mt-5 max-w-2xl">
              A lightweight storyboard for the final demo: failed recordings,
              instrumentation, logged reruns, fix dispatch, and passing replays.
            </p>
          </div>
        </LandingSection>

        {demoSections.map((section, index) => (
          <DemoStorySection
            key={section.id}
            section={section}
            tone={index % 2 === 0 ? "plain" : "band"}
          />
        ))}
      </main>
    </LandingAppShell>
  );
}

function DemoStorySection({
  section,
  tone,
}: {
  section: DemoSection;
  tone: "plain" | "band";
}) {
  return (
    <LandingSection
      id={section.id}
      className="scroll-mt-8"
      containerClassName="landing-use-case-container grid gap-8"
      tone={tone}
    >
      <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <SectionHeader
          body={section.body}
          className="max-w-3xl"
          eyebrow={section.eyebrow}
          title={section.title}
        />
        {section.cta ? (
          <Button asChild size="lg" className="w-full sm:w-fit">
            <a href={section.cta.href}>{section.cta.label}</a>
          </Button>
        ) : null}
      </div>

      <div className="grid gap-4 md:grid-cols-3 md:items-stretch">
        {section.cards.map((card) => (
          <DemoRecordingCard key={`${section.id}-${card.agent}`} card={card} />
        ))}
      </div>
    </LandingSection>
  );
}

function DemoRecordingCard({ card }: { card: DemoCard }) {
  const tone = toneStyles[card.tone];
  const Icon = tone.icon;

  return (
    <LandingCard
      as="article"
      size="compact"
      className="flex h-full min-h-[31rem] flex-col overflow-hidden border-border-strong/70 bg-panel/88 p-0"
    >
      <div className="flex min-h-14 items-center justify-between gap-3 border-b border-border/65 px-4">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-foreground">{card.agent}</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">Recording slot</p>
        </div>
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em]",
            tone.label,
          )}
        >
          <Icon className="size-3" aria-hidden="true" />
          {card.stateLabel}
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-4 p-4">
        <RecordingPlaceholder card={card} />
        <p className="text-sm leading-6 text-muted-foreground">{card.caption}</p>
      </div>
    </LandingCard>
  );
}

function RecordingPlaceholder({ card }: { card: DemoCard }) {
  const tone = toneStyles[card.tone];
  const Icon = tone.icon;

  return (
    <div
      aria-label={`${card.agent} future recording placeholder`}
      className="relative flex min-h-72 flex-col justify-between overflow-hidden rounded-[1rem] border border-border/80 bg-[linear-gradient(180deg,hsl(var(--elevated)/0.8),hsl(var(--panel)/0.96))] p-4 shadow-inner"
      data-media-path={card.mediaPath}
      role="img"
    >
      <div
        className="absolute inset-0 bg-[radial-gradient(circle_at_20%_0%,hsl(var(--accent)/0.13),transparent_16rem),linear-gradient(135deg,hsl(var(--panel)/0.1),hsl(var(--elevated)/0.42))]"
        aria-hidden="true"
      />
      <div className="relative flex items-center justify-between gap-3">
        <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          Recording placeholder
        </span>
        <span className={cn("rounded-full border px-2 py-1 text-[10px] font-semibold", tone.label)}>
          future media
        </span>
      </div>

      <div className="relative grid place-items-center py-8 text-center">
        <span className="flex size-16 items-center justify-center rounded-full border border-accent/25 bg-accent-muted/45 text-accent shadow-glow">
          <Icon className="size-7" aria-hidden="true" />
        </span>
        <p className="mt-4 max-w-[14rem] text-sm font-medium text-foreground">
          Drop the final recording here.
        </p>
      </div>

      <div className="relative rounded-lg border border-border/70 bg-canvas/70 px-3 py-2">
        <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          Future path
        </p>
        <p className="mt-1 truncate font-mono text-[11px] text-foreground" title={card.mediaPath}>
          {card.mediaPath}
        </p>
      </div>
    </div>
  );
}
