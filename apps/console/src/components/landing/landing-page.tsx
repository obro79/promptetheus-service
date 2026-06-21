import Link from "next/link";
import type { CSSProperties } from "react";
import {
  ArrowRight,
  CheckCircle2,
  GitPullRequest,
  Play,
  SearchCheck,
  Sparkles,
} from "lucide-react";

import {
  failureVolumeBars,
  fixAgentChecklist,
  heroMockup,
  heroMockupTabs,
  heroSidebarItems,
  landingAgents,
  landingHero,
  landingIncidentLoopStreamEvents,
  landingMetricTiles,
  landingNavItems,
  landingProofCards,
  landingSections,
  streamWorkflowEvents,
} from "@/components/landing/landing-content";
import {
  LandingCard,
  LandingSection,
  SectionHeader,
} from "@/components/landing/landing-primitives";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type LandingStats = {
  fixedIncidents: number;
  openIncidents: number;
};

const useCaseAssetClassNames = {
  browser: "landing-video-asset-browser",
  chat: "landing-video-asset-chat",
  voice: "landing-video-asset-voice",
} as const;

const workflowAssetClassNames = {
  dashboard: "landing-workflow-asset-dashboard",
  fix: "landing-workflow-asset-fix",
  install: "landing-workflow-asset-install",
  stream: "landing-workflow-asset-stream",
} as const;

const streamEventToneClassNames = {
  artifact: "landing-stream-event-artifact",
  model: "landing-stream-event-model",
  prompt: "landing-stream-event-prompt",
  state: "landing-stream-event-state",
  summary: "landing-stream-event-summary",
  tool: "landing-stream-event-tool",
  warning: "landing-stream-event-warning",
} as const;

export function LandingPage({ stats }: { stats: LandingStats }) {
  return (
    <div className="landing-page">
      <LandingHero />

      <LandingSection
        id="agents"
        containerClassName="landing-use-case-container grid gap-10"
      >
        <SectionHeader
          align="center"
          body={landingSections.agents.body}
          title={landingSections.agents.title}
        />

        <div className="grid gap-4 md:grid-cols-3 md:items-stretch">
          {landingAgents.map((agent) => (
            <HomeAgentCard key={agent.title} agent={agent} />
          ))}
        </div>
      </LandingSection>

      <LandingSection
        id="proof"
        className="bg-canvas"
        density="compact"
        containerClassName="grid gap-8 lg:grid-cols-[0.8fr_1.7fr] lg:items-start"
      >
        <SectionHeader
          className="max-w-md"
          title={landingSections.proof.title}
        />
        <div className="grid gap-4 sm:grid-cols-3">
          {landingProofCards.map((card) => (
            <LandingCard key={card.label} as="article" className="min-h-[260px]">
              <p className="font-display text-7xl leading-none text-foreground">{card.value}</p>
              <h3 className="mt-6 text-sm font-semibold text-accent">
                {card.label}
              </h3>
              <p className="mt-4 text-sm leading-6 text-muted-foreground">{card.body}</p>
            </LandingCard>
          ))}
        </div>
      </LandingSection>

      <LandingSection
        id="incident-loop"
        tone="band"
        containerClassName="landing-use-case-container grid gap-10"
      >
        <SectionHeader
          align="center"
          body={landingSections.incidentLoop.body}
          title={landingSections.incidentLoop.title}
        />

        <HomeIncidentLoop />
      </LandingSection>

      <LandingSection
        id="case-file"
        containerClassName="landing-use-case-container grid gap-10"
      >
        <SectionHeader
          align="center"
          body={landingSections.caseFile.body}
          title={landingSections.caseFile.title}
        />

        <CaseFilePreview stats={stats} />
      </LandingSection>

      <LandingSection className="text-center" containerClassName="flex flex-col items-center">
        <LandingCard size="hero" className="landing-cta-card max-w-5xl">
          <div className="absolute inset-x-0 top-0 h-40 bg-accent/12 blur-3xl" aria-hidden="true" />
          <h2 className="landing-display-lg relative mx-auto max-w-4xl">
            {landingSections.finalCta.title}
          </h2>
          <div className="landing-action-row relative mt-8 justify-center">
            <Button asChild size="lg" className="min-h-12 rounded-full px-6 shadow-glow">
              <Link href={landingSections.finalCta.primaryCta.href}>
                {landingSections.finalCta.primaryCta.label}
              </Link>
            </Button>
            <Button asChild variant="outline" size="lg" className="min-h-12 rounded-full px-6">
              <Link href={landingSections.finalCta.secondaryCta.href}>
                {landingSections.finalCta.secondaryCta.label}
              </Link>
            </Button>
          </div>
        </LandingCard>
      </LandingSection>
    </div>
  );
}

function LandingHero() {
  return (
    <section className="relative isolate min-h-[42rem] overflow-hidden bg-[hsl(var(--hero-sky-top))] pb-20 text-white sm:min-h-[46rem] sm:pb-24">
      <div className="cluely-hero-backdrop pointer-events-none absolute inset-0" />
      <div className="landing-hero-readable-scrim pointer-events-none absolute inset-0" />
      <LandingHeroNav />
      <div className="relative z-30 mx-auto flex max-w-6xl flex-col items-center px-4 pt-20 text-center sm:px-6 sm:pt-24 lg:pt-28">
        <p className="landing-hero-category">
          {landingHero.category}
        </p>
        <h1 className="mt-5 max-w-6xl font-display text-[3.75rem] font-normal leading-[0.88] tracking-normal text-white drop-shadow-[0_3px_18px_hsl(213_82%_18%/0.34)] sm:text-[5.8rem] sm:leading-[0.84] lg:text-[7rem]">
          {landingHero.title}
        </h1>
        <p className="mt-8 max-w-3xl text-balance text-lg font-semibold leading-8 text-white drop-shadow-[0_2px_12px_hsl(213_82%_18%/0.32)] sm:text-2xl">
          {landingHero.body}
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Button
            asChild
            className="min-h-14 px-8 text-base shadow-[0_12px_28px_hsl(221_100%_40%/0.34)]"
            size="lg"
          >
            <Link href={landingHero.primaryCta.href}>
              <Play className="size-4" aria-hidden="true" />
              {landingHero.primaryCta.label}
            </Link>
          </Button>
          <Button
            asChild
            className="border-white/30 bg-foreground/45 px-8 text-base text-white shadow-[0_12px_28px_hsl(205_86%_31%/0.12)] hover:bg-foreground/55"
            size="lg"
            variant="outline"
          >
            <Link href={landingHero.secondaryCta.href}>
              {landingHero.secondaryCta.label}
              <ArrowRight className="size-4" aria-hidden="true" />
            </Link>
          </Button>
        </div>
        <HeroProofStrip />
      </div>
    </section>
  );
}

function LandingHeroNav() {
  return (
    <header className="relative z-40 mx-auto flex h-20 max-w-6xl items-center gap-4 px-5 text-white sm:px-8">
      <Link
        href="/"
        className="flex min-h-11 min-w-0 items-center gap-2 rounded-full pr-2 text-white transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/80"
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-white/40 bg-white/20 text-sm font-bold shadow-[0_8px_30px_hsl(213_82%_18%/0.22)] backdrop-blur">
          P
        </span>
        <span className="truncate text-base font-semibold drop-shadow-[0_1px_8px_hsl(213_82%_18%/0.28)] sm:text-lg">
          Promptetheus
        </span>
      </Link>
      <nav className="ml-auto hidden items-center gap-7 text-base font-semibold text-white/90 lg:flex">
        {landingNavItems.map((item) => (
          <Link key={item.href} href={item.href} className="transition-colors hover:text-white">
            {item.label}
          </Link>
        ))}
      </nav>
      <Button
        asChild
        className="ml-auto min-h-11 shrink-0 border-white/30 bg-white/20 px-5 text-white shadow-[0_10px_30px_hsl(213_82%_18%/0.16)] hover:bg-white/25 lg:ml-0"
        variant="outline"
      >
        <Link href="/demo">{landingHero.primaryCta.label}</Link>
      </Button>
    </header>
  );
}

function HeroProofStrip() {
  return (
    <div className="landing-hero-proof-strip" aria-label="Promptetheus workflow">
      {landingHero.proofSteps.map((step, index) => (
        <div key={step} className="landing-hero-proof-step">
          <span>{String(index + 1).padStart(2, "0")}</span>
          <p>{step}</p>
        </div>
      ))}
    </div>
  );
}

function HomeAgentCard({
  agent,
}: {
  agent: (typeof landingAgents)[number];
}) {
  return (
    <article className="landing-agent-card surface flex h-full flex-col overflow-hidden rounded-[1.45rem] border-border/80 bg-panel/90 shadow-[0_22px_64px_hsl(var(--shadow-color)/0.13)]">
      <div className="border-b border-border/50 px-4 py-3">
        <h3 className="text-sm font-semibold text-foreground">{agent.title}</h3>
      </div>

      <div className="flex flex-1 flex-col p-3 pb-0">
        <AgentVisualSlot agent={agent} />
      </div>

      <div className="landing-agent-card-task px-4 py-3">
        <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/75">
          Production task
        </p>
        <p className="mt-1 text-sm leading-snug text-muted-foreground">{agent.task}</p>
        <dl className="landing-agent-evidence-list">
          <div>
            <dt>Failure</dt>
            <dd>{agent.failure}</dd>
          </div>
          <div>
            <dt>Evidence</dt>
            <dd>{agent.evidence}</dd>
          </div>
          <div>
            <dt>Fix path</dt>
            <dd>{agent.fixAction}</dd>
          </div>
        </dl>
      </div>
    </article>
  );
}

function AgentVisualSlot({ agent }: { agent: (typeof landingAgents)[number] }) {
  const sceneToneClass = {
    browser: "landing-video-asset-browser",
    chat: "landing-video-asset-chat",
    voice: "landing-video-asset-voice",
  }[agent.kind];

  if (agent.videoSrc) {
    return (
      <video
        aria-label={agent.assetLabel}
        autoPlay
        className={cn(
          "landing-agent-card-visual w-full rounded-[1rem] border border-border/75 bg-white/60 object-cover",
          sceneToneClass,
        )}
        loop
        muted
        playsInline
        poster={agent.posterSrc}
      />
    );
  }

  return (
    <div
      className={cn(
        "landing-agent-card-visual relative w-full overflow-hidden rounded-[1rem] border border-border/75 bg-[linear-gradient(180deg,hsl(var(--elevated)/0.86),hsl(var(--panel)/0.92))] shadow-inner",
        sceneToneClass,
      )}
      role="img"
      aria-label={agent.assetLabel}
    >
      {agent.kind === "browser" ? <BrowserMiniScene /> : null}
      {agent.kind === "chat" ? <ChatMiniScene /> : null}
      {agent.kind === "voice" ? <VoiceMiniScene /> : null}
    </div>
  );
}

function BrowserMiniScene() {
  return (
    <div className="landing-agent-scene landing-agent-mini-scene" aria-hidden="true">
      <div className="landing-agent-mini-browser-panel">
        <div className="landing-browser-chrome">
          <span />
          <span />
          <span />
          <div>checkout.acme.test/book</div>
        </div>
        <div className="landing-browser-page">
          <div className="landing-browser-hero-line" />
          <div className="landing-browser-row landing-browser-row-short" />
          <div className="landing-browser-row" />
          <div className="landing-browser-slot-grid">
            <div className="landing-browser-slot">Mon 10:00 AM</div>
            <div className="landing-browser-slot landing-browser-slot-active">Tue 2:00 PM</div>
          </div>
          <div className="landing-browser-target">Confirm order</div>
          <div className="landing-browser-click-ring landing-agent-mini-click-ring" />
          <div className="landing-browser-cursor landing-agent-mini-cursor" />
        </div>
      </div>
    </div>
  );
}

function ChatMiniScene() {
  return (
    <div className="landing-agent-scene landing-agent-mini-scene" aria-hidden="true">
      <div className="landing-chat-reel landing-chat-window landing-agent-mini-chat-window">
        <div className="landing-chat-bubble landing-chat-user landing-chat-mini-user-1">
          I still cannot access my workspace.
        </div>
        <div className="landing-chat-indicator landing-chat-thinking landing-chat-mini-thinking-1">
          <span>Thinking</span>
          <span className="landing-chat-indicator-dots">
            <span />
            <span />
            <span />
          </span>
        </div>
        <div className="landing-chat-indicator landing-chat-typing landing-chat-mini-typing-1">
          <span className="landing-chat-indicator-dots">
            <span />
            <span />
            <span />
          </span>
        </div>
        <div className="landing-chat-bubble landing-chat-agent landing-chat-mini-agent-1">
          Try refreshing and signing in again.
        </div>
        <div className="landing-chat-bubble landing-chat-user landing-chat-mini-user-2">
          That loops me back to billing.
        </div>
        <div className="landing-chat-indicator landing-chat-thinking landing-chat-mini-thinking-2">
          <span>Thinking</span>
          <span className="landing-chat-indicator-dots">
            <span />
            <span />
            <span />
          </span>
        </div>
      </div>
    </div>
  );
}

function VoiceMiniScene() {
  return (
    <div
      className="landing-agent-scene landing-agent-mini-scene landing-speaking-scene landing-agent-mini-voice-scene"
      aria-hidden="true"
    >
      <div className="landing-voice-core landing-agent-mini-voice-core">
        <div
          className="landing-demo-voice-orb landing-demo-voice-orb-speaking landing-demo-voice-orb-live"
          aria-label="Animated voice orb"
        >
          <span className="landing-demo-voice-orb-glow" />
          <span className="landing-demo-voice-orb-ring landing-demo-voice-orb-ring-one" />
          <span className="landing-demo-voice-orb-ring landing-demo-voice-orb-ring-two" />
          <span className="landing-demo-voice-orb-shell" />
          <span className="landing-demo-voice-orb-core" />
          <span className="landing-demo-voice-orb-shine" />
          <span className="landing-demo-voice-activity landing-demo-voice-bars" aria-hidden="true">
            {[0.5, 0.84, 1, 0.72, 0.92, 0.62, 0.78].map((height, barIndex) => (
              <i
                key={barIndex}
                style={
                  {
                    "--bar-height": `${height * 28}px`,
                    "--bar-delay": `${barIndex * 70}ms`,
                  } as CSSProperties
                }
              />
            ))}
          </span>
        </div>
      </div>
      <div className="landing-agent-mini-voice-evidence">
        <span>Transcript evidence</span>
        <strong>&quot;I need a human now&quot;</strong>
        <p>handoff failed · 2.1s silence · escalation pinned</p>
      </div>
    </div>
  );
}

function HomeIncidentLoop() {
  return (
    <div className="landing-instrumentation-loop surface overflow-hidden rounded-[1.6rem] border-border/80 bg-panel/90">
      <IncidentInstrumentationPanel />
      <IncidentTraceStreamPanel />
    </div>
  );
}

const loopInstallCommand = "$ uv add promptetheus-service";
const loopImportLine = "+ import promptetheus as pt";
const loopDecoratorLine = '+ @pt.observe("refund-agent")';
const loopTerminalOutputLines = [
  "resolved 18 packages in 142ms",
  "installed promptetheus-service, httpx, pydantic",
  "Built promptetheus-service @ file:///…",
] as const;

function IncidentInstrumentationPanel() {
  return (
    <div
      className="landing-loop-install-panel landing-workflow-asset-install"
      aria-label="Animated instrumentation setup with package install and trace wrapper"
    >
      <div className="landing-loop-install-sequence" aria-hidden="true">
        <div className="landing-loop-terminal landing-loop-terminal-bare">
          <div className="landing-loop-terminal-body">
            <div className="landing-loop-terminal-typewriter">
              <code
                className="landing-loop-terminal-command"
                style={{ "--type-chars": loopInstallCommand.length } as CSSProperties}
              >
                {loopInstallCommand}
              </code>
            </div>
            {loopTerminalOutputLines.map((line) => (
              <code key={line} className="landing-loop-terminal-output">
                {line}
              </code>
            ))}
          </div>
        </div>

        <div className="landing-loop-editor">
          <div className="landing-loop-panel-bar">
            <span />
            <span />
            <span />
            <p>agent.py</p>
          </div>
          <div className="landing-loop-editor-lines">
            <div className="landing-loop-editor-typewriter">
              <code
                className="landing-loop-code-import"
                style={{ "--type-chars": loopImportLine.length } as CSSProperties}
              >
                {loopImportLine}
              </code>
            </div>
            <code className="landing-loop-code-existing">  from agents import refund_agent</code>
            <div className="landing-loop-editor-typewriter">
              <code
                className="landing-loop-code-decorator"
                style={{ "--type-chars": loopDecoratorLine.length } as CSSProperties}
              >
                {loopDecoratorLine}
              </code>
            </div>
            <code className="landing-loop-code-existing">  def run_agent(task):</code>
            <code className="landing-loop-code-existing">      return refund_agent.run(task)</code>
          </div>
        </div>
      </div>
    </div>
  );
}

function IncidentTraceStreamPanel() {
  return (
    <div
      className="landing-loop-stream-panel landing-workflow-asset-stream"
      aria-label="Live trace event stream"
    >
      <div className="landing-loop-stream-terminal" aria-hidden="true">
        <div className="landing-loop-stream-terminal-bar">
          <span>tail -f trace.log</span>
        </div>
        <div className="landing-loop-stream-terminal-viewport">
          <div className="landing-loop-stream-terminal-scroll">
            {[0, 1].map((copy) => (
              <div
                key={copy}
                className="landing-loop-stream-chunk"
                aria-hidden={copy === 1 ? true : undefined}
              >
                {landingIncidentLoopStreamEvents.map((event, index) => (
                  <div
                    key={`${copy}-${event.type}-${index}`}
                    className={cn(
                      "landing-loop-stream-line",
                      streamEventToneClassNames[event.tone],
                    )}
                  >
                    <span className="landing-loop-stream-ts">{event.meta}</span>
                    <span className="landing-loop-stream-kind">
                      {event.type.replaceAll("_", " ")}
                    </span>
                    <span className="landing-loop-stream-text">{event.body}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function CaseFilePreview({ stats }: { stats: LandingStats }) {
  return <HeroMockup stats={stats} />;
}

function LandingNav() {
  return (
    <header className="landing-container relative z-20 pt-4">
      <nav className="landing-nav-frame" aria-label="Landing navigation">
        <Link href="/" className="landing-brand-link">
          <span className="landing-brand-mark">P</span>
          <span className="display text-2xl leading-none text-foreground">Promptetheus</span>
        </Link>
        <div className="ml-auto hidden items-center gap-6 lg:flex">
          {landingNavItems.map((item) => (
            <Link key={item.href} href={item.href} className="landing-nav-link">
              {item.label}
            </Link>
          ))}
        </div>
        <Button asChild size="sm" className="ml-auto min-h-10 rounded-full px-4 lg:ml-4">
          <Link href="/demo">See demo</Link>
        </Button>
      </nav>
    </header>
  );
}

function HeroMockup({ stats }: { stats: LandingStats }) {
  return (
    <div className="relative mt-12 w-full">
      <div
        className="absolute left-1/2 top-5 h-48 w-[82%] -translate-x-1/2 rounded-full bg-accent/18 blur-3xl"
        aria-hidden="true"
      />
      <LandingCard className="relative mx-auto overflow-hidden border-border-strong/50 bg-panel/90 p-0 shadow-glow">
        <div className="flex min-h-16 items-center gap-3 border-b border-border/55 bg-panel/80 px-4 sm:px-5">
          <span className="flex size-10 items-center justify-center border-r border-border/55 pr-4 text-accent">
            <Sparkles className="size-5" aria-hidden="true" />
          </span>
          <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto">
            {heroMockupTabs.map((tab, index) => (
              <span
                key={tab}
                className={cn(
                  "whitespace-nowrap rounded-full border px-4 py-2 text-xs font-medium",
                  index === 1
                    ? "border-accent/25 bg-accent-muted text-accent"
                    : "border-border/60 bg-panel/60 text-muted-foreground",
                )}
              >
                {tab}
              </span>
            ))}
          </div>
          <span className="hidden items-center gap-1.5 rounded-full border border-success/25 bg-success/10 px-3 py-1.5 text-xs font-medium text-success sm:inline-flex">
            <CheckCircle2 className="size-3.5" aria-hidden="true" />
            {heroMockup.status}
          </span>
        </div>

        <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-[64px_1.4fr_0.9fr]">
          <div className="hidden rounded-2xl border border-border/45 bg-elevated/35 py-4 lg:flex lg:flex-col lg:items-center lg:gap-5">
            {heroSidebarItems.map(({ label, Icon, active }) => (
              <span
                key={label}
                className={cn(
                  "flex size-9 items-center justify-center rounded-xl text-muted-foreground",
                  active && "bg-accent-muted text-accent",
                )}
                aria-label={label}
              >
                <Icon className="size-4" aria-hidden="true" />
              </span>
            ))}
          </div>

          <div className="grid gap-4">
            <LandingCard size="compact">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-foreground">
                    {heroMockup.failureVolumeTitle}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {heroMockup.failureVolumeBody}
                  </p>
                </div>
                <span className="rounded-full bg-accent-muted px-2.5 py-1 text-[11px] font-semibold text-accent">
                  {heroMockup.failureVolumeSignal}
                </span>
              </div>
              <div className="mt-7 h-44 rounded-2xl border border-border/45 bg-gradient-to-b from-accent/10 to-transparent p-4">
                <div className="flex h-full items-end gap-2">
                  {failureVolumeBars.map((height, index) => (
                    <span
                      key={`${height}-${index}`}
                      className="flex-1 rounded-t-full bg-gradient-to-t from-accent/75 to-accent/15"
                      style={{ height: `${height}%` }}
                    />
                  ))}
                </div>
              </div>
            </LandingCard>

            <div className="grid gap-4 sm:grid-cols-2">
              {landingMetricTiles.map((tile) => (
                <MetricTile
                  key={tile.label}
                  label={tile.label}
                  tone={tile.tone}
                  value={stats[tile.statKey]}
                />
              ))}
            </div>
          </div>

          <div className="grid gap-4">
            <LandingCard size="compact">
              <p className="text-sm font-semibold text-foreground">
                {heroMockup.criticalReplayTitle}
              </p>
              <div className="mt-5 flex min-h-44 items-center justify-center rounded-2xl border border-border/45 bg-accent-muted/35">
                <div className="relative flex size-32 items-center justify-center rounded-full border border-accent/30 bg-panel/60 shadow-glow">
                  <div className="absolute inset-4 rounded-full bg-[radial-gradient(circle_at_35%_35%,hsl(var(--panel)),hsl(var(--accent-bright))_42%,hsl(var(--accent))_72%,transparent)] opacity-80" />
                  <SearchCheck
                    className="relative size-10 text-accent-foreground"
                    aria-hidden="true"
                  />
                </div>
              </div>
              <p className="mt-4 text-xs leading-5 text-muted-foreground">
                {heroMockup.criticalReplayBody}
              </p>
            </LandingCard>
            <LandingCard size="compact">
              <div className="flex items-center justify-between gap-3">
                <span>
                  <p className="text-sm font-semibold text-foreground">{heroMockup.fixAgentTitle}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{heroMockup.fixAgentBody}</p>
                </span>
                <GitPullRequest className="size-5 text-accent" aria-hidden="true" />
              </div>
              <div className="mt-5 space-y-2">
                {fixAgentChecklist.map((item) => (
                  <div key={item} className="flex items-center gap-2 text-xs text-muted-foreground">
                    <CheckCircle2 className="size-3.5 text-success" aria-hidden="true" />
                    {item}
                  </div>
                ))}
              </div>
            </LandingCard>
          </div>
        </div>
      </LandingCard>
    </div>
  );
}

function MetricTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "warning" | "success";
}) {
  return (
    <LandingCard size="compact">
      <p className={cn("display text-5xl leading-none", tone === "warning" ? "text-warning" : "text-success")}>
        {String(value).padStart(2, "0")}
      </p>
      <p className="mt-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </p>
    </LandingCard>
  );
}

function UseCaseVideoAsset({
  kind,
  label,
}: {
  kind: "browser" | "chat" | "voice";
  label: string;
}) {
  return (
    <div
      className={cn("landing-video-asset", useCaseAssetClassNames[kind])}
      role="img"
      aria-label={label}
    >
      {kind === "browser" ? <BrowserAgentAsset /> : null}
      {kind === "chat" ? <ChatAgentAsset /> : null}
      {kind === "voice" ? <VoiceAgentAsset /> : null}
    </div>
  );
}

function WorkflowVideoAsset({
  kind,
  label,
}: {
  kind: "install" | "stream" | "dashboard" | "fix";
  label: string;
}) {
  return (
    <div
      className={cn("landing-workflow-asset", workflowAssetClassNames[kind])}
      role="img"
      aria-label={label}
    >
      {kind === "install" ? <InstallWorkflowAsset /> : null}
      {kind === "stream" ? <StreamWorkflowAsset /> : null}
      {kind === "dashboard" ? <DashboardWorkflowAsset /> : null}
      {kind === "fix" ? <FixWorkflowAsset /> : null}
    </div>
  );
}

function InstallWorkflowAsset() {
  const terminalLines = [
    "$ uv add promptetheus",
    "resolved 18 packages in 142ms",
    "installed promptetheus, httpx, pydantic",
    "lockfile updated",
  ] as const;

  return (
    <div className="landing-install-sequence" aria-hidden="true">
      <div className="landing-install-terminal">
        <div className="landing-install-terminal-bar">
          <span />
          <p>terminal</p>
        </div>
        <div className="landing-install-terminal-lines">
          {terminalLines.map((line, index) => (
            <code key={line} style={{ "--install-index": index } as CSSProperties}>
              {line}
            </code>
          ))}
        </div>
      </div>

      <div className="landing-install-editor">
        <div className="landing-install-editor-bar">
          <span />
          <span />
          <span />
          <p>agent.py</p>
        </div>
        <div className="landing-install-editor-lines">
          <code className="landing-install-code-added">+ import promptetheus as t</code>
          <code className="landing-install-code-existing">  from agents import refund_agent</code>
          <code className="landing-install-code-added">+ @t.trace(name=&quot;refund-agent&quot;)</code>
          <code className="landing-install-code-existing">  def run_agent(task):</code>
          <code className="landing-install-code-existing">      return refund_agent.run(task)</code>
        </div>
      </div>

      <div className="landing-install-badge">wrapper added</div>
    </div>
  );
}

function StreamWorkflowAsset() {
  const centerEventIndex = streamWorkflowEvents.findIndex((event) => event.type === "tool.call");
  const streamCenterIndex = centerEventIndex >= 0 ? centerEventIndex : 0;
  const centerPhase = 4;

  return (
    <div className="landing-stream-window" aria-hidden="true">
      <div className="landing-stream-header">
        <span />
        <p>trace bus</p>
        <strong>2.4k events/min</strong>
      </div>

      <div className="landing-stream-viewport">
        <div className="landing-stream-highlight" />
        <div className="landing-stream-lane">
          {streamWorkflowEvents.map((event, index) => {
            const streamPhase =
              (index - streamCenterIndex + centerPhase + streamWorkflowEvents.length) %
              streamWorkflowEvents.length;

            return (
              <div
                key={event.type}
                className={cn("landing-stream-event", streamEventToneClassNames[event.tone])}
                style={{ "--stream-phase": streamPhase } as CSSProperties}
              >
                <span>{event.type}</span>
                <p>{event.body}</p>
                <em>{event.meta}</em>
              </div>
            );
          })}
        </div>
      </div>

      <div className="landing-stream-footer">
        <span>WebSocket ingest</span>
        <span>Kafka fanout</span>
        <span>Redis hot cache</span>
      </div>
    </div>
  );
}

function DashboardWorkflowAsset() {
  return (
    <div className="landing-dashboard-window" aria-hidden="true">
      <div className="landing-dashboard-sidebar">
        <span />
        <span />
        <span />
      </div>
      <div className="landing-dashboard-main">
        <div className="landing-dashboard-header">
          <span>Live traces</span>
          <strong>31</strong>
        </div>
        <div className="landing-dashboard-chart">
          {[42, 68, 54, 78, 64, 92, 72].map((height, index) => (
            <span
              key={`${height}-${index}`}
              style={{ "--bar-height": `${height}%`, "--bar-index": index } as CSSProperties}
            />
          ))}
        </div>
        <div className="landing-dashboard-list">
          <span>browser checkout replay</span>
          <span>voice handoff cluster</span>
        </div>
      </div>
    </div>
  );
}

function FixWorkflowAsset() {
  return (
    <div className="landing-pr-window" aria-hidden="true">
      <div className="landing-pr-card">
        <div className="landing-pr-header">
          <GitPullRequest className="size-4" aria-hidden="true" />
          <span>Pull request opened</span>
        </div>
        <p>fix/refund-agent-replay</p>
        <div className="landing-pr-diff">
          <span />
          <span />
          <span />
        </div>
        <div className="landing-pr-checks">
          <span>
            <CheckCircle2 className="size-3.5" aria-hidden="true" />
            replay passed
          </span>
          <span>
            <CheckCircle2 className="size-3.5" aria-hidden="true" />
            regression queued
          </span>
        </div>
      </div>
      <div className="landing-pr-orbit" />
    </div>
  );
}

function BrowserAgentAsset() {
  return (
    <div className="landing-agent-scene landing-agent-scene-browser" aria-hidden="true">
      <div className="landing-browser-reel landing-browser-reel-evidence">
        <div className="landing-browser-chrome">
          <span />
          <span />
          <span />
          <div>checkout.acme.test</div>
        </div>
        <div className="landing-browser-page">
          <div className="landing-browser-hero-line" />
          <div className="landing-browser-row landing-browser-row-short" />
          <div className="landing-browser-row" />
          <div className="landing-browser-row landing-browser-row-short" />
          <div className="landing-browser-target">Confirm order</div>
          <div className="landing-browser-warning">UI warning ignored</div>
          <div className="landing-browser-click-ring" />
          <div className="landing-browser-cursor" />
        </div>
      </div>

      <div className="landing-evidence-card landing-evidence-card-primary landing-browser-evidence-primary">
        <div className="landing-evidence-card-header">
          <strong>Checkout flow replay</strong>
          <span>UI state</span>
        </div>
        <dl>
          <div>
            <dt>Clicked</dt>
            <dd>Confirm order</dd>
          </div>
          <div>
            <dt>Expected</dt>
            <dd>Resolve warning</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>Mismatch found</dd>
          </div>
        </dl>
      </div>
      <div className="landing-evidence-card landing-evidence-card-secondary landing-browser-evidence-secondary">
        <div className="landing-evidence-card-header">
          <strong>Hidden state changed</strong>
          <span>DOM snapshot</span>
        </div>
      </div>
      <div className="landing-evidence-card landing-evidence-card-tertiary landing-browser-evidence-tertiary">
        <div className="landing-evidence-card-header">
          <strong>Warning ignored</strong>
          <span>Replay pinned</span>
        </div>
      </div>
    </div>
  );
}

function ChatAgentAsset() {
  return (
    <div className="landing-agent-scene landing-agent-scene-chat" aria-hidden="true">
      <div className="landing-chat-reel landing-chat-window">
        <div className="landing-chat-bubble landing-chat-user">
          I still cannot access my workspace.
        </div>
        <div className="landing-chat-bubble landing-chat-agent">
          Try refreshing and signing in again.
        </div>
        <div className="landing-chat-bubble landing-chat-user">
          That loops me back to billing.
        </div>
        <div className="landing-chat-drift">
          <span />
          Drift detected
        </div>
        <div className="landing-chat-cluster">12 matching sessions</div>
      </div>

      <div className="landing-evidence-card landing-evidence-card-primary landing-chat-evidence-primary">
        <div className="landing-evidence-card-header">
          <strong>Conversation drift</strong>
          <span>Turn 08</span>
        </div>
        <dl>
          <div>
            <dt>User</dt>
            <dd>Workspace loops to billing</dd>
          </div>
          <div>
            <dt>Agent</dt>
            <dd>Repeated stale fix</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>12 matching sessions</dd>
          </div>
        </dl>
      </div>
      <div className="landing-evidence-card landing-evidence-card-secondary landing-chat-evidence-secondary">
        <div className="landing-evidence-card-header">
          <strong>Cluster opened</strong>
          <span>Unresolved</span>
        </div>
      </div>
      <div className="landing-evidence-card landing-evidence-card-tertiary landing-chat-evidence-tertiary">
        <div className="landing-evidence-card-header">
          <strong>Replay turn</strong>
          <span>Ready</span>
        </div>
      </div>
    </div>
  );
}

function VoiceAgentAsset() {
  return (
    <div className="landing-agent-scene landing-agent-scene-voice landing-speaking-scene" aria-hidden="true">
      <div className="landing-voice-component">
        <div className="landing-voice-status">
          <span />
          Live voice trace
        </div>
        <div className="landing-voice-core">
          <span className="landing-voice-ring landing-voice-ring-one" />
          <span className="landing-voice-ring landing-voice-ring-two" />
          <span className="landing-voice-avatar">AI</span>
        </div>
        <div className="landing-waveform">
          {[42, 78, 56, 92, 64, 100, 48, 84, 58, 72, 44].map((height, index) => (
            <span
              key={`${height}-${index}`}
              style={{ "--wave-height": `${height}%`, "--wave-index": index } as CSSProperties}
            />
          ))}
        </div>
        <div className="landing-voice-metadata">
          <span>187ms latency</span>
          <span>speaker diarized</span>
        </div>
      </div>

      <div className="landing-evidence-card landing-evidence-card-primary landing-voice-failure-card">
        <div className="landing-evidence-card-header">
          <strong>Escalation missed</strong>
          <span>Call trace</span>
        </div>
        <dl>
          <div>
            <dt>Silence</dt>
            <dd>4.2 seconds</dd>
          </div>
          <div>
            <dt>Tool</dt>
            <dd>Handoff failed</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>Transcript pinned</dd>
          </div>
        </dl>
      </div>

      <div className="landing-voice-transcript-card">
        <span>Caller: I need a human now.</span>
        <span>Agent: I can continue helping.</span>
      </div>

      <div className="landing-evidence-card landing-evidence-card-secondary landing-voice-tool-card">
        <div className="landing-evidence-card-header">
          <strong>Tool handoff</strong>
          <span>Failed</span>
        </div>
      </div>

      <div className="landing-voice-pinned-chip">Transcript pinned</div>
    </div>
  );
}
