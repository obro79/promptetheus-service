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
      <section className="relative isolate px-4 py-6 sm:px-6 lg:px-8">
        <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[36rem] bg-[linear-gradient(180deg,hsl(var(--glow-accent)/0.32),transparent_76%)]" />
        <div className="mx-auto flex max-w-7xl flex-col gap-6">
          <TopSample />
          <Hero />
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
    <section className="grid min-h-[26rem] overflow-hidden rounded-[2rem] border border-white/70 bg-white/60 shadow-[0_36px_120px_hsl(var(--shadow-color)/0.14)] backdrop-blur-2xl lg:grid-cols-[minmax(0,0.95fr)_minmax(360px,0.7fr)]">
      <div className="flex flex-col justify-center p-6 sm:p-10 lg:p-12">
        <p className="mb-5 inline-flex w-fit items-center gap-2 rounded-full border border-border/80 bg-panel/80 px-3 py-1.5 text-sm font-medium text-muted-foreground shadow-sm">
          <Sparkles className="size-4 text-accent" />
          Cluely-inspired Promptetheus UI system
        </p>
        <h1 className="max-w-3xl text-5xl font-black leading-[0.92] tracking-[-0.04em] text-foreground sm:text-6xl lg:text-7xl">
          A light assistant interface for agent repair.
        </h1>
        <p className="mt-6 max-w-2xl text-base leading-7 text-muted-foreground sm:text-lg">
          Blue signal color, floating panels, rounded desktop windows, and compact evidence streams
          for the next Promptetheus demo rebuild.
        </p>
        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Button size="lg">
            <Play />
            Play demo
          </Button>
          <Button size="lg" variant="secondary">
            View components
            <ArrowRight />
          </Button>
        </div>
      </div>
      <div className="relative min-h-[28rem] overflow-hidden bg-[linear-gradient(155deg,hsl(var(--accent-muted)),hsl(0_0%_100%/0.2))] p-5">
        <div className="absolute inset-x-8 top-8 rounded-[1.6rem] border border-white/80 bg-panel/75 p-3 shadow-[0_26px_80px_hsl(var(--shadow-color)/0.16)] backdrop-blur-2xl">
          <div className="mb-3 flex items-center gap-2">
            <span className="size-3 rounded-full bg-destructive/70" />
            <span className="size-3 rounded-full bg-warning/70" />
            <span className="size-3 rounded-full bg-success/70" />
            <span className="ml-2 h-7 flex-1 rounded-full border border-border/70 bg-white/60" />
          </div>
          <div className="grid gap-2">
            <div className="h-24 rounded-[1.1rem] border border-border/70 bg-white/80 p-4">
              <div className="h-3 w-32 rounded-full bg-foreground/12" />
              <div className="mt-3 h-2 w-full rounded-full bg-accent/20" />
              <div className="mt-2 h-2 w-3/4 rounded-full bg-accent/14" />
            </div>
            <div className="grid grid-cols-3 gap-2">
              {["01:00", "02:00", "14:00"].map((time) => (
                <div
                  key={time}
                  className={cn(
                    "rounded-2xl border px-3 py-4 text-center text-sm font-semibold",
                    time === "02:00"
                      ? "border-destructive/35 bg-destructive/10 text-destructive"
                      : time === "14:00"
                        ? "border-success/35 bg-success/10 text-success"
                        : "border-border/70 bg-white/70 text-muted-foreground",
                  )}
                >
                  {time}
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="absolute bottom-8 right-6 w-[min(22rem,calc(100%-3rem))] rounded-[1.5rem] border border-white/80 bg-foreground p-4 text-background shadow-[0_30px_90px_hsl(var(--shadow-color)/0.28)]">
          <div className="mb-3 flex items-center justify-between gap-3">
            <span className="inline-flex items-center gap-2 text-sm font-semibold">
              <ShieldCheck className="size-4 text-accent" />
              Promptetheus detected
            </span>
            <span className="rounded-full bg-white/10 px-2 py-1 text-[11px]">critical</span>
          </div>
          <p className="text-sm leading-6 text-background/78">
            User asked for 2:00 PM. The browser agent selected 02:00 and ignored the page warning.
          </p>
        </div>
      </div>
    </section>
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
        <CardDescription>Surface plus attached stream, designed for the demo grid.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-[1.25rem] border border-border/75 bg-white/75 p-4">
          <div className="mb-6 flex items-center justify-between">
            <span className="inline-flex items-center gap-2 text-sm font-semibold">
              <Monitor className="size-4 text-accent" />
              Browser Agent
            </span>
            <span className="rounded-full bg-destructive/10 px-2.5 py-1 text-xs font-medium text-destructive">
              failed
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {["1 AM", "2 AM", "2 PM"].map((slot) => (
              <div
                key={slot}
                className={cn(
                  "rounded-2xl border px-2 py-3 text-center text-xs font-semibold",
                  slot === "2 AM" ? "border-destructive/35 bg-destructive/10 text-destructive" : "border-border bg-panel",
                )}
              >
                {slot}
              </div>
            ))}
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
