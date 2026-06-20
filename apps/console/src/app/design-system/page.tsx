import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Circle,
  Code2,
  Command,
  FileText,
  Loader2,
  Mic,
  Monitor,
  Play,
  Radio,
  Search,
  ShieldCheck,
  Sparkles,
  Terminal,
  Wand2,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const SWATCHES = [
  { label: "Canvas", className: "bg-canvas", token: "--canvas" },
  { label: "Panel", className: "bg-panel", token: "--panel" },
  { label: "Elevated", className: "bg-elevated", token: "--elevated" },
  { label: "Primary", className: "bg-accent", token: "--accent" },
  { label: "Success", className: "bg-success", token: "--success" },
  { label: "Warning", className: "bg-warning", token: "--warning" },
  { label: "Failure", className: "bg-destructive", token: "--destructive" },
] as const;

const STATES = [
  { label: "Running", detail: "Fixture is in progress", Icon: Radio, className: "text-accent" },
  { label: "Observed", detail: "Events are streaming", Icon: Activity, className: "text-accent" },
  { label: "Failed", detail: "Goal mismatch found", Icon: XCircle, className: "text-destructive" },
  { label: "Fixing", detail: "Patch bundle open", Icon: Wand2, className: "text-warning" },
  { label: "Passed", detail: "Regression replay clean", Icon: CheckCircle2, className: "text-success" },
] as const;

const AGENTS = [
  { name: "Voice Agent", Icon: Mic, event: "state_change intent unchanged", tone: "text-warning" },
  { name: "Browser Agent", Icon: Monitor, event: "dom_snapshot warning visible", tone: "text-destructive" },
  { name: "Chat Agent", Icon: Bot, event: "retrieval policy contradicted", tone: "text-accent" },
] as const;

const TERMINAL_EVENTS = [
  "[browser] browser_action click li[data-time='02:00']",
  "[browser] dom_snapshot warning: did you mean 2:00 PM?",
  "[browser] agent_message \"Booked 2pm Pacific\"",
  "[detect] goal_check failed: selected 02:00",
] as const;

export default function DesignSystemPage() {
  if (process.env.NODE_ENV === "production") notFound();

  return (
    <main className="min-h-dvh overflow-hidden bg-canvas text-foreground">
      <Hero />
      <section className="relative isolate px-4 py-6 sm:px-6 lg:px-8">
        <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[28rem] bg-[linear-gradient(180deg,hsl(var(--hero-sky-mid)/0.2),transparent_76%)]" />
        <div className="mx-auto flex max-w-7xl flex-col gap-6">
          <TopSample />
          <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(360px,0.6fr)]">
            <TypographySection />
            <AssistantPanel />
          </div>
          <ColorsSection />
          <ControlsSection />
          <CardsSection />
          <DemoComponentsSection />
          <StatesSection />
        </div>
      </section>
    </main>
  );
}

function TopSample() {
  return (
    <header className="surface flex min-h-16 items-center gap-3 rounded-full px-3 py-2 shadow-depth">
      <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent text-sm font-bold text-accent-foreground shadow-[0_14px_32px_hsl(var(--accent)/0.25)]">
        P
      </div>
      <nav className="hidden items-center gap-1 rounded-full border border-border/70 bg-panel/70 p-1 text-sm font-medium text-muted-foreground md:flex">
        {["Design system", "Demo", "Incidents"].map((item, index) => (
          <span
            key={item}
            className={cn(
              "rounded-full px-4 py-2 transition-colors",
              index === 0 ? "bg-foreground text-background shadow-sm" : "hover:bg-elevated hover:text-foreground",
            )}
          >
            {item}
          </span>
        ))}
      </nav>
      <div className="ml-auto flex min-w-0 items-center gap-2">
        <div className="hidden min-h-10 w-64 items-center gap-2 rounded-full border border-border/80 bg-panel/75 px-3 text-sm text-muted-foreground shadow-sm sm:flex">
          <Search className="size-4" />
          <span className="truncate">Search components</span>
          <span className="ml-auto rounded-full bg-elevated px-2 py-0.5 text-[11px]">cmd k</span>
        </div>
        <Button size="icon" variant="secondary" aria-label="Open command menu">
          <Command />
        </Button>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="relative isolate min-h-[58rem] overflow-hidden bg-[hsl(var(--hero-sky-top))] text-white sm:min-h-[62rem] lg:min-h-[64rem]">
      <div className="cluely-hero-backdrop pointer-events-none absolute inset-0" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,hsl(203_91%_55%/0.06)_0%,transparent_36%,hsl(55_95%_93%/0.12)_100%)]" />
      <HeroNav />
      <div className="relative z-30 mx-auto flex max-w-6xl flex-col items-center px-4 pt-24 text-center sm:px-6 sm:pt-28 lg:pt-32">
        <h1 className="max-w-5xl font-display text-[4.6rem] font-normal leading-[0.82] tracking-normal text-white drop-shadow-[0_2px_16px_hsl(205_86%_31%/0.16)] sm:text-[6.7rem] lg:text-[8rem]">
          Fix failing agents as they happen
        </h1>
        <p className="mt-9 max-w-3xl text-balance text-xl font-semibold leading-8 text-white/90 drop-shadow-[0_1px_8px_hsl(205_86%_31%/0.18)] sm:text-2xl">
          Promptetheus streams the trace, isolates the bad step, and hands a tested patch to your
          coding agent.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Button className="min-h-14 px-8 text-base shadow-[0_12px_28px_hsl(221_100%_40%/0.34)]" size="lg">
            <Play />
            Play demo
          </Button>
          <Button
            className="border-white/35 bg-white/15 px-8 text-base text-white shadow-[0_12px_28px_hsl(205_86%_31%/0.1)] hover:bg-white/24"
            size="lg"
            variant="outline"
          >
            View tokens
            <ArrowRight />
          </Button>
        </div>
      </div>
      <DesktopStage />
    </section>
  );
}

function HeroNav() {
  return (
    <header className="relative z-20 mx-auto flex h-20 max-w-6xl items-center gap-8 px-5 text-white sm:px-8">
      <div className="flex items-center gap-2.5 text-2xl font-bold">
        <span className="flex size-8 items-center justify-center rounded-full border-2 border-white/95 text-sm font-black">
          P
        </span>
        Promptetheus
      </div>
      <nav className="hidden items-center gap-9 text-lg font-semibold text-white/90 md:flex">
        {["Demo", "Replay", "Dashboard"].map((item) => (
          <span key={item} className="transition-colors hover:text-white">
            {item}
          </span>
        ))}
      </nav>
    </header>
  );
}

function DesktopStage() {
  return (
    <div className="absolute inset-x-4 bottom-[-18rem] z-10 mx-auto h-[30rem] max-w-[78rem] overflow-hidden rounded-t-[1.6rem] border border-white/35 bg-white/5 shadow-[0_-24px_90px_hsl(206_82%_40%/0.18),0_34px_100px_hsl(223_41%_9%/0.22)] backdrop-blur-[1px] sm:bottom-[-15rem] sm:h-[31rem]">
      <div className="absolute inset-x-0 top-0 flex h-12 items-center justify-between bg-white/14 px-5 text-white">
        <Circle className="size-4 fill-white/30 text-white/85" />
        <div className="flex items-center gap-4 text-white/90">
          <Radio className="size-4" />
          <Command className="size-4" />
        </div>
      </div>
      <FloatingControl />
      <BrowserWindow />
      <AssistantGlassOverlay />
    </div>
  );
}

function FloatingControl() {
  return (
    <div className="absolute left-1/2 top-14 z-30 flex -translate-x-1/2 items-center gap-2 rounded-full bg-[hsl(var(--assistant-glass)/0.82)] p-2 text-sm font-semibold text-white shadow-[0_18px_42px_hsl(223_41%_9%/0.26)] backdrop-blur-2xl">
      <span className="flex size-10 items-center justify-center rounded-full border border-white/10 bg-white/12 font-bold">
        P
      </span>
      <span className="rounded-full border border-white/10 bg-white/8 px-4 py-2">Observe</span>
      <span className="flex size-9 items-center justify-center rounded-full border border-white/10 bg-white/12">
        <Circle className="size-4 fill-white text-white" />
      </span>
    </div>
  );
}

function BrowserWindow() {
  return (
    <div className="absolute left-1/2 top-28 z-20 h-[21rem] w-[min(66rem,76vw)] -translate-x-1/2 overflow-hidden rounded-t-[1.35rem] border border-white/12 bg-[hsl(223_41%_9%)] shadow-[0_30px_90px_hsl(223_41%_9%/0.38)]">
      <div className="flex h-10 items-center gap-2 border-b border-white/10 bg-[hsl(225_20%_13%)] px-4">
        <span className="size-3 rounded-full bg-destructive" />
        <span className="size-3 rounded-full bg-warning" />
        <span className="size-3 rounded-full bg-success" />
      </div>
      <div className="grid h-[calc(100%-2.5rem)] grid-cols-2 gap-3 p-4">
        <div className="overflow-hidden rounded-[1rem] bg-[linear-gradient(140deg,hsl(190_90%_50%/0.78),hsl(222_70%_18%)_48%,hsl(25_56%_52%))]">
          <div className="h-full bg-[radial-gradient(circle_at_28%_14%,hsl(184_100%_70%/0.9),transparent_8rem),linear-gradient(180deg,transparent,hsl(0_0%_0%/0.2))]" />
        </div>
        <div className="overflow-hidden rounded-[1rem] bg-[linear-gradient(145deg,hsl(201_38%_89%),hsl(220_18%_65%)_62%,hsl(26_46%_58%))]">
          <div className="h-full bg-[radial-gradient(circle_at_54%_38%,hsl(34_80%_84%/0.82),transparent_7rem),linear-gradient(180deg,transparent,hsl(0_0%_0%/0.22))]" />
        </div>
      </div>
    </div>
  );
}

function AssistantGlassOverlay() {
  return (
    <div className="absolute left-1/2 top-32 z-40 w-[min(44rem,70vw)] -translate-x-1/2 rounded-[1.45rem] border border-[hsl(var(--assistant-glass-border)/0.22)] bg-[hsl(var(--assistant-glass)/0.72)] p-4 text-white shadow-[0_22px_70px_hsl(223_41%_9%/0.34)] backdrop-blur-2xl">
      <div className="mb-4 flex justify-end">
        <span className="rounded-full border border-accent/45 bg-accent px-4 py-2 text-sm font-semibold text-white shadow-[0_12px_32px_hsl(var(--accent)/0.36)]">
          What failed here?
        </span>
      </div>
      <p className="text-sm leading-6 text-white/82 sm:text-base">
        The browser agent selected 02:00 after the page warned that 2:00 PM was likely intended.
      </p>
      <div className="mt-5 flex flex-wrap items-center gap-4 border-t border-white/12 pt-4 text-sm text-white/72">
        <span className="inline-flex items-center gap-2">
          <Sparkles className="size-4" />
          Assist
        </span>
        <span className="inline-flex items-center gap-2">
          <ShieldCheck className="size-4" />
          Evidence
        </span>
        <span className="inline-flex items-center gap-2">
          <Terminal className="size-4" />
          Replay
        </span>
      </div>
      <div className="mt-4 flex min-h-12 items-center gap-2 rounded-[0.95rem] border border-white/14 bg-white/8 px-4 text-sm text-white/52">
        Ask about the trace, or dispatch a fix
        <Button className="ml-auto size-9 shrink-0 p-0" size="icon" aria-label="Dispatch fix">
          <Play />
        </Button>
      </div>
    </div>
  );
}

function TypographySection() {
  return (
    <SystemSection eyebrow="Typography" title="Large display, calm body, compact machine text">
      <div className="space-y-7">
        <div>
          <p className="text-6xl font-black leading-[0.9] tracking-[-0.045em] sm:text-7xl">
            Fix failing agents as they happen.
          </p>
          <p className="mt-4 max-w-xl text-lg leading-7 text-muted-foreground">
            Use this scale for demo hero moments and top-level product claims.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <TypeRow label="Section heading" sample="Incident response console" className="text-3xl font-bold tracking-[-0.03em]" />
          <TypeRow label="Body" sample="Every event links back to evidence, replay, and repair context." className="text-base leading-7 text-muted-foreground" />
          <TypeRow label="Caption" sample="Observed across 3 deterministic fixtures" className="text-sm font-medium text-muted-foreground" />
          <TypeRow label="Mono" sample="[browser] goal_check failed" className="font-mono text-sm text-foreground" />
        </div>
      </div>
    </SystemSection>
  );
}

function ColorsSection() {
  return (
    <SystemSection eyebrow="Tokens" title="Light-first semantic color system">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
        {SWATCHES.map((swatch) => (
          <div key={swatch.label} className="overflow-hidden rounded-[1.35rem] border border-border/75 bg-panel/70 shadow-sm">
            <div className={cn("h-24", swatch.className)} />
            <div className="p-3">
              <p className="text-sm font-semibold">{swatch.label}</p>
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">{swatch.token}</p>
            </div>
          </div>
        ))}
      </div>
    </SystemSection>
  );
}

function ControlsSection() {
  return (
    <SystemSection eyebrow="Controls" title="Pill actions and soft input surfaces">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Buttons</CardTitle>
            <CardDescription>Primary actions are blue pills with visible focus and compact icon support.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-3">
            <Button><Wand2 />Dispatch fix</Button>
            <Button variant="secondary"><FileText />Open replay</Button>
            <Button variant="outline">Assign owner</Button>
            <Button variant="ghost">View trace</Button>
            <Button variant="destructive"><AlertTriangle />Escalate</Button>
            <Button size="icon" variant="secondary" aria-label="Search"><Search /></Button>
            <Button disabled><Loader2 className="animate-spin" />Packaging</Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Inputs</CardTitle>
            <CardDescription>Search and command fields should feel like assistant entry points.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="block">
              <span className="mb-2 block text-sm font-medium">Search incidents</span>
              <div className="relative">
                <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input className="pl-10" placeholder="goal mismatch, refund, browser warning" />
              </div>
            </label>
            <label className="block">
              <span className="mb-2 block text-sm font-medium">Command</span>
              <div className="relative">
                <Command className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input className="pl-10 font-mono text-sm" placeholder="/dispatch inc_browser_goal_mismatch" />
              </div>
            </label>
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-muted-foreground">Disabled</span>
              <Input disabled value="Waiting for fixture playback" readOnly />
            </label>
          </CardContent>
        </Card>
      </div>
    </SystemSection>
  );
}

function CardsSection() {
  return (
    <SystemSection eyebrow="Cards" title="Rounded panels for assistant and evidence surfaces">
      <div className="grid gap-4 lg:grid-cols-4">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Basic card</CardTitle>
            <CardDescription>Use for bounded component groups and local settings.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-24 rounded-[1rem] border border-border/70 bg-elevated/70" />
          </CardContent>
        </Card>
        <AgentCard />
        <EvidenceCard />
        <MetricCard />
      </div>
    </SystemSection>
  );
}

function DemoComponentsSection() {
  return (
    <SystemSection eyebrow="Demo pieces" title="Three-agent fixture components">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.64fr)]">
        <div className="grid gap-4 md:grid-cols-3">
          {AGENTS.map((agent) => (
            <ThreeAgentCard key={agent.name} {...agent} />
          ))}
        </div>
        <div className="grid gap-4">
          <TerminalStrip />
          <CodeBlock />
          <IncidentRow />
          <FixPipeline />
        </div>
      </div>
    </SystemSection>
  );
}

function StatesSection() {
  return (
    <SystemSection eyebrow="States" title="Every status combines icon, text, and color">
      <div className="grid gap-3 md:grid-cols-5">
        {STATES.map(({ label, detail, Icon, className }) => (
          <div key={label} className="rounded-[1.25rem] border border-border/75 bg-panel/75 p-4 shadow-sm">
            <Icon className={cn("mb-6 size-5", className)} />
            <p className="text-sm font-semibold">{label}</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p>
          </div>
        ))}
      </div>
    </SystemSection>
  );
}

function AssistantPanel() {
  return (
    <aside className="surface flex min-h-[28rem] flex-col justify-between rounded-[1.8rem] p-5">
      <div>
        <div className="flex items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2 rounded-full bg-accent-muted px-3 py-1.5 text-sm font-semibold text-accent">
            <Sparkles className="size-4" />
            Assistant panel
          </span>
          <span className="rounded-full border border-border/70 bg-panel px-3 py-1 text-xs text-muted-foreground">
            live
          </span>
        </div>
        <div className="mt-8 space-y-3">
          <MessageBubble side="left" text="Why did the browser agent fail?" />
          <MessageBubble side="right" text="It clicked 2:00 AM after the page warned that 2:00 PM was likely intended." />
          <MessageBubble side="left" text="Package the fix and replay it." />
        </div>
      </div>
      <div className="mt-6 rounded-[1.4rem] border border-border/80 bg-white/72 p-2 shadow-sm">
        <div className="flex min-h-12 items-center gap-2 rounded-full bg-elevated/70 px-4 text-sm text-muted-foreground">
          <Command className="size-4" />
          Ask Promptetheus to repair this incident
          <Button className="ml-auto" size="sm">
            Send
          </Button>
        </div>
      </div>
    </aside>
  );
}

function TypeRow({
  label,
  sample,
  className,
}: {
  label: string;
  sample: string;
  className: string;
}) {
  return (
    <div className="rounded-[1.1rem] border border-border/75 bg-panel/70 p-4">
      <p className="mb-3 text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </p>
      <p className={className}>{sample}</p>
    </div>
  );
}

function AgentCard() {
  return (
    <Card className="lg:col-span-1">
      <CardHeader>
        <CardTitle>Agent card</CardTitle>
        <CardDescription>Compact incident postcard for the homepage and demo grid.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-[1.35rem] border border-border/75 bg-panel/90 p-3 shadow-[0_18px_48px_hsl(var(--shadow-color)/0.12)]">
          <div className="mb-3 flex items-center justify-between gap-3">
            <span className="inline-flex items-center gap-2 text-sm font-semibold">
              <span className="flex size-8 items-center justify-center rounded-full border border-border/80 bg-white/80">
                <Monitor className="size-4 text-destructive" />
              </span>
              Browser Agent
            </span>
            <span className="rounded-full bg-destructive/10 px-2.5 py-1 text-xs font-medium text-destructive">
              failed
            </span>
          </div>
          <div className="rounded-[1.1rem] border border-border/75 bg-[linear-gradient(180deg,hsl(var(--elevated)/0.86),hsl(var(--panel)/0.92))] p-3">
            <div className="rounded-[0.9rem] border border-border/70 bg-panel/80 p-3 shadow-sm">
              <div className="mb-3 flex items-center gap-1.5 border-b border-border/70 pb-2">
                <span className="size-2.5 rounded-full bg-destructive" />
                <span className="size-2.5 rounded-full bg-warning" />
                <span className="size-2.5 rounded-full bg-success" />
                <span className="ml-2 h-4 flex-1 rounded-full bg-elevated" />
              </div>
              <div className="grid gap-2">
                <span className="h-3 w-3/4 rounded-full bg-accent/25" />
                <span className="h-3 w-1/2 rounded-full bg-accent/20" />
              </div>
              <div className="mt-5 flex items-center justify-between gap-3">
                <span className="rounded-full bg-accent px-3 py-1.5 text-xs font-semibold text-accent-foreground">
                  Confirm order
                </span>
                <span className="rounded-full border border-destructive/25 bg-destructive/10 px-3 py-1.5 text-xs font-semibold text-destructive">
                  Warning visible
                </span>
              </div>
            </div>
          </div>
          <div className="mt-3 px-1">
            <p className="font-mono text-[10px] font-semibold uppercase text-muted-foreground/75">
              Production task
            </p>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Complete a checkout or booking flow
            </p>
            <div className="mt-3 flex items-start gap-2.5 rounded-[1rem] border border-destructive/20 bg-destructive/10 px-3 py-2.5">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
              <div>
                <p className="font-mono text-[10px] font-semibold uppercase text-destructive/70">
                  Failure captured
                </p>
                <p className="mt-0.5 text-sm font-semibold leading-5 text-destructive">
                  Wrong click after an ignored UI warning
                </p>
              </div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5 px-1">
            {["DOM state", "screenshot", "cursor path"].map((item) => (
              <span
                key={item}
                className="rounded-full border border-border/70 bg-elevated/75 px-2.5 py-1 text-[11px] font-medium text-muted-foreground"
              >
                {item}
              </span>
            ))}
          </div>
          <div className="mt-4 grid gap-2">
            <div className="rounded-[1rem] border border-accent/20 bg-accent-muted/60 px-3 py-2.5 text-sm leading-6">
              <span className="mb-1 inline-flex items-center gap-2 text-xs font-semibold text-accent">
                <ShieldCheck className="size-3.5" />
                Fix target
              </span>
              <p>Replay the critical step and hand the UI-state mismatch to the fix agent.</p>
            </div>
            <div className="flex min-h-10 items-center gap-2 rounded-[0.95rem] border border-foreground/10 bg-foreground px-3 font-mono text-[11px] text-background">
              <Terminal className="size-3.5 shrink-0 text-background/50" />
              <span className="text-background/50">latest</span>
              <span className="min-w-0 truncate text-background/80">
                dom_snapshot warning visible
              </span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function EvidenceCard() {
  return (
    <Card className="lg:col-span-1">
      <CardHeader>
        <CardTitle>Evidence card</CardTitle>
        <CardDescription>Short, attributable, and connected to replay state.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-[1.25rem] border border-warning/30 bg-warning/10 p-4">
          <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-warning">
            <AlertTriangle className="size-4" />
            Critical step
          </div>
          <p className="text-sm leading-6 text-foreground">
            The DOM warning was visible before the agent claimed the booking matched the user goal.
          </p>
          <p className="mt-4 font-mono text-xs text-muted-foreground">seq 14 - dom_snapshot</p>
        </div>
      </CardContent>
    </Card>
  );
}

function MetricCard() {
  return (
    <Card className="lg:col-span-1">
      <CardHeader>
        <CardTitle>Metric card</CardTitle>
        <CardDescription>Use sparingly, with clear labels and tabular values.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-[1.25rem] border border-border/75 bg-foreground p-4 text-background">
          <p className="text-xs font-medium uppercase tracking-[0.08em] text-background/60">Detected incidents</p>
          <p className="mt-5 text-5xl font-black tracking-[-0.05em]">03</p>
          <p className="mt-2 text-sm text-background/70">Across voice, browser, and chat fixtures.</p>
        </div>
      </CardContent>
    </Card>
  );
}

function ThreeAgentCard({
  name,
  Icon,
  event,
  tone,
}: {
  name: string;
  Icon: LucideIcon;
  event: string;
  tone: string;
}) {
  return (
    <div className="surface flex min-h-[22rem] flex-col rounded-[1.6rem] p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-2 text-sm font-semibold">
          <Icon className={cn("size-4", tone)} />
          {name}
        </span>
        <span className="rounded-full bg-elevated px-2.5 py-1 text-xs font-medium text-muted-foreground">
          test
        </span>
      </div>
      <div className="mt-5 flex flex-1 items-center justify-center rounded-[1.25rem] border border-border/75 bg-white/60">
        <div className="text-center">
          <Circle className={cn("mx-auto mb-3 size-7", tone)} />
          <p className="text-sm font-semibold">Fixture failed</p>
          <p className="mt-1 text-xs text-muted-foreground">Rerun after instrumentation</p>
        </div>
      </div>
      <div className="mt-3 rounded-[1rem] border border-border/80 bg-foreground p-3 font-mono text-[11px] leading-5 text-background/78">
        <p className="text-background/50">stream</p>
        <p className="mt-1 truncate">{event}</p>
      </div>
    </div>
  );
}

function TerminalStrip() {
  return (
    <div className="rounded-[1.35rem] border border-border/80 bg-foreground p-4 text-background shadow-[0_24px_60px_hsl(var(--shadow-color)/0.18)]">
      <div className="mb-3 flex items-center justify-between">
        <span className="inline-flex items-center gap-2 text-sm font-semibold">
          <Terminal className="size-4 text-accent" />
          Terminal stream
        </span>
        <span className="font-mono text-xs text-background/50">04 events</span>
      </div>
      <div className="space-y-1 font-mono text-xs leading-5 text-background/72">
        {TERMINAL_EVENTS.map((event) => (
          <p key={event} className="truncate">{event}</p>
        ))}
      </div>
    </div>
  );
}

function CodeBlock() {
  return (
    <div className="rounded-[1.35rem] border border-border/80 bg-panel/80 p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Code2 className="size-4 text-accent" />
        Instrumentation
      </div>
      <pre className="overflow-x-auto rounded-[1rem] bg-foreground p-4 text-xs leading-6 text-background/80">
        <code>{`uv add promptetheus

import promptetheus as pt

@pt.observe("acmemeet-browser-agent")
def run_agent(task):
    return agent.run(task)`}</code>
      </pre>
    </div>
  );
}

function IncidentRow() {
  return (
    <div className="rounded-[1.35rem] border border-border/80 bg-panel/80 p-4 shadow-sm">
      <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3">
        <span className="flex size-10 items-center justify-center rounded-full bg-destructive/10 text-destructive">
          <AlertTriangle className="size-5" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">Browser goal mismatch</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">Selected 02:00 after warning, claimed 2:00 PM.</p>
        </div>
        <span className="rounded-full bg-destructive/10 px-3 py-1 text-xs font-semibold text-destructive">
          critical
        </span>
      </div>
    </div>
  );
}

function FixPipeline() {
  const steps = [
    { label: "Bundle", detail: "Root cause and diff packaged", Icon: FileText },
    { label: "Patch", detail: "Time parser updates ready", Icon: Wand2 },
    { label: "Replay", detail: "Regression selects 14:00", Icon: ShieldCheck },
  ] as const;

  return (
    <div className="rounded-[1.35rem] border border-border/80 bg-panel/80 p-4 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <span className="text-sm font-semibold">Fix pipeline</span>
        <span className="rounded-full bg-success/10 px-3 py-1 text-xs font-semibold text-success">passed</span>
      </div>
      <div className="space-y-3">
        {steps.map(({ label, detail, Icon }, index) => (
          <div key={label} className="flex items-center gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-bold text-accent-foreground">
              {index + 1}
            </span>
            <Icon className="size-4 shrink-0 text-accent" />
            <div className="min-w-0">
              <p className="text-sm font-semibold">{label}</p>
              <p className="truncate text-xs text-muted-foreground">{detail}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MessageBubble({ side, text }: { side: "left" | "right"; text: string }) {
  return (
    <div className={cn("flex", side === "right" && "justify-end")}>
      <p
        className={cn(
          "max-w-[82%] rounded-[1.25rem] px-4 py-3 text-sm leading-6 shadow-sm",
          side === "right" ? "bg-accent text-accent-foreground" : "border border-border/80 bg-panel/80 text-foreground",
        )}
      >
        {text}
      </p>
    </div>
  );
}

function SystemSection({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[2rem] border border-white/70 bg-white/50 p-4 shadow-[0_28px_90px_hsl(var(--shadow-color)/0.1)] backdrop-blur-2xl sm:p-6">
      <div className="mb-5">
        <p className="mb-2 text-sm font-semibold text-accent">{eyebrow}</p>
        <h2 className="text-3xl font-black tracking-[-0.04em] sm:text-4xl">{title}</h2>
      </div>
      {children}
    </section>
  );
}
