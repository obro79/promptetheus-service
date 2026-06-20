import {
  LineChart,
  Repeat2,
  ShieldCheck,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

// Primary edit surface for landing copy, nav, cards, and mockup labels.
export const landingNavItems = [
  { label: "Use cases", href: "#use-cases" },
  { label: "How it works", href: "#how-it-works" },
  { label: "Results", href: "#results" },
  { label: "Docs", href: "/docs" },
] as const;

export const landingHero = {
  eyebrow: "Production failures, replayed as evidence",
  title: "Purpose-built incident response for AI agents",
  body:
    "Promptetheus records messy agent runs, detects likely failures, replays the exact bad step, and packages a verified fix path for the coding agent.",
  primaryCta: { label: "See the demo", href: "/demo" },
  secondaryCta: { label: "Open console", href: "/incidents" },
} as const;

export const landingSections = {
  results: {
    eyebrow: "Results",
    title: "From bad run to fix-ready case file",
  },
  useCases: {
    eyebrow: "Use cases",
    title: "Debug every agent workflow with the same loop",
    body:
      "Browser, chat, and voice agents all fail through observable moments: clicks, turns, transcripts, tools, artifacts, and outcome signals.",
  },
  workflow: {
    eyebrow: "How it works",
    title: "From setup to prevention in one incident loop",
  },
  finalCta: {
    eyebrow: "Ready for the demo gate",
    title: "Show the failure, explain it, patch it, and prove it will not regress.",
    primaryCta: { label: "Run the demo", href: "/demo" },
    secondaryCta: { label: "Read API docs", href: "/docs" },
  },
} as const;

export const landingProofCards = [
  {
    value: "3m",
    label: "to first root cause",
    body: "Jump from a bad outcome to the exact step, input, state, and artifact that explain it.",
  },
  {
    value: "14",
    label: "locked API endpoints",
    body: "A contract-first backend keeps ingestion, analysis, replay, fixes, and regression runs aligned.",
  },
  {
    value: "1",
    label: "failure loop",
    body: "Observe, detect, replay, attribute, patch, and prevent without switching tools.",
  },
] as const;

export const landingUseCases: Array<{
  assetKind: "browser" | "chat" | "voice";
  assetLabel: string;
  title: string;
  description: string;
}> = [
  {
    assetKind: "browser",
    assetLabel: "Pastel product scene showing browser replay evidence cards around a glowing orb",
    title: "Browser agents",
    description:
      "Catch wrong clicks, ignored UI warnings, false success claims, and hidden state mismatches.",
  },
  {
    assetKind: "chat",
    assetLabel: "Pastel product scene showing chat drift and clustered unresolved sessions",
    title: "Chat agents",
    description:
      "Cluster unresolved conversations and replay the turn that sent the customer off path.",
  },
  {
    assetKind: "voice",
    assetLabel: "Animated voice trace showing a speaking agent, waveform, transcript, and escalation signals",
    title: "Voice agents",
    description:
      "Trace calls, transcripts, silence, tool handoffs, and escalation moments before they repeat.",
  },
];

export const landingWorkflowSteps: Array<{
  assetKind: "install" | "stream" | "dashboard" | "fix";
  assetLabel: string;
  eyebrow: string;
  title: string;
  body: string;
}> = [
  {
    assetKind: "install",
    assetLabel:
      "Animated terminal and editor showing uv installing Promptetheus, then adding an import and trace wrapper to existing code",
    eyebrow: "01",
    title: "Install and wrap the run",
    body:
      "Run uv add, keep the existing agent function, import Promptetheus, and add one trace wrapper.",
  },
  {
    assetKind: "stream",
    assetLabel: "High-velocity event stream showing WebSocket ingest, tool calls, state, artifacts, and failure signals",
    eyebrow: "02",
    title: "Stream every signal",
    body: "Capture prompts, tool calls, model outputs, artifacts, browser state, and reasoning summaries as trace events.",
  },
  {
    assetKind: "dashboard",
    assetLabel: "Animated dashboard card showing live sessions, failure clusters, and replay status",
    eyebrow: "03",
    title: "Watch the dashboard",
    body: "See live sessions, failure clusters, event timelines, and replay artifacts arrive in the console.",
  },
  {
    assetKind: "fix",
    assetLabel: "Animated pull request card showing replay evidence, checks, and fix PR creation",
    eyebrow: "04",
    title: "Replay and open the fix PR",
    body: "Replay the critical step, package the fix brief, and hand the patch target to a coding agent.",
  },
];

export const heroMockupTabs = ["Trace", "Replay", "Fix PR"] as const;

export const streamWorkflowEvents = [
  {
    type: "ws.recv",
    body: "session.checkout-481 event batch",
    meta: "18ms",
    tone: "state",
  },
  {
    type: "prompt",
    body: "refund policy + user request",
    meta: "24ms",
    tone: "prompt",
  },
  {
    type: "tool.call",
    body: "browser.click #refund-menu",
    meta: "31ms",
    tone: "tool",
  },
  {
    type: "model.delta",
    body: "reasoning summary chunk",
    meta: "44ms",
    tone: "model",
  },
  {
    type: "artifact",
    body: "dom snapshot + screenshot",
    meta: "57ms",
    tone: "artifact",
  },
  {
    type: "state",
    body: "checkout warning still visible",
    meta: "63ms",
    tone: "state",
  },
  {
    type: "signal.warn",
    body: "false success claim detected",
    meta: "71ms",
    tone: "warning",
  },
  {
    type: "redis.pub",
    body: "cluster replay index updated",
    meta: "88ms",
    tone: "summary",
  },
] as const;

export const heroSidebarItems: Array<{
  label: string;
  Icon: LucideIcon;
  active?: boolean;
}> = [
  { label: "Failure trends", Icon: LineChart },
  { label: "Active incident", Icon: TriangleAlert, active: true },
  { label: "Replay loop", Icon: Repeat2 },
  { label: "Regression shield", Icon: ShieldCheck },
];

export const heroMockup = {
  status: "System operational",
  failureVolumeTitle: "Failure volume",
  failureVolumeBody: "Sessions with unresolved outcome signals",
  failureVolumeSignal: "+12.8% signal",
  criticalReplayTitle: "Critical step replay",
  criticalReplayBody:
    "Wrong element clicked after a validation warning. Evidence attached with DOM state and replay artifact.",
  fixAgentTitle: "Fix agent bundle",
  fixAgentBody: "Patch context plus regression target",
} as const;

export const failureVolumeBars = [32, 58, 48, 76, 92, 64, 84, 112, 54, 73, 101, 86] as const;

export const landingMetricTiles = [
  { label: "Open incidents", statKey: "openIncidents", tone: "warning" },
  { label: "Fixed clusters", statKey: "fixedIncidents", tone: "success" },
] as const;

export const fixAgentChecklist = [
  "Root cause isolated",
  "Prompt patch drafted",
  "Regression replay queued",
] as const;
