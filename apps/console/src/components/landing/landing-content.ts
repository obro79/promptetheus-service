import {
  LineChart,
  Repeat2,
  ShieldCheck,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

// Primary edit surface for landing copy, nav, cards, and mockup labels.
export const landingNavItems = [
  { label: "Agents", href: "#agents" },
  { label: "Incident loop", href: "#incident-loop" },
  { label: "Proof", href: "#proof" },
  { label: "Docs", href: "/docs" },
] as const;

export const landingHero = {
  title: "When agents fail in production, know why",
  body:
    "Promptetheus records messy agent runs, detects likely failures, replays the exact bad step, and packages a verified fix path for the coding agent.",
  primaryCta: { label: "See the demo", href: "/demo" },
  secondaryCta: { label: "Open console", href: "/incidents" },
} as const;

export const landingSections = {
  agents: {
    eyebrow: "Agent coverage",
    title: "Every workflow fails through evidence",
    body:
      "Browser, chat, and voice agents look different in production, but their failures still reduce to observable moments: actions, turns, transcripts, tools, state, artifacts, and outcomes.",
  },
  proof: {
    eyebrow: "Proof",
    title: "Credibility without turning the homepage into a dashboard",
  },
  incidentLoop: {
    eyebrow: "Incident loop",
    title: "From trace to regression in one incident loop",
    body:
      "Observe the production run, isolate the bad step, replay the evidence, package the fix, and keep the regression target around.",
  },
  caseFile: {
    eyebrow: "Case file",
    title: "The homepage promise resolves into a fix-ready incident",
    body:
      "The console turns live traces into a compact case file: failure volume, critical replay, evidence, fix bundle, and regression status.",
  },
  finalCta: {
    eyebrow: "Demo gate",
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
    label: "incident loop",
    body: "Observe, detect, replay, attribute, patch, and prevent without switching tools.",
  },
] as const;

export const landingAgents: Array<{
  kind: "browser" | "chat" | "voice";
  assetLabel: string;
  title: string;
  task: string;
  failure: string;
  evidence: string;
  fixAction: string;
  videoSrc?: string;
  posterSrc?: string;
}> = [
  {
    kind: "browser",
    assetLabel:
      "Animated browser-agent replay showing a wrong click, ignored warning, and pinned evidence cards",
    title: "Browser agents",
    task: "Complete a checkout or booking flow",
    failure: "Wrong click after an ignored UI warning",
    evidence: "DOM state, screenshot, cursor path, warning text",
    fixAction: "Replay the critical step and hand the UI-state mismatch to the fix agent",
  },
  {
    kind: "chat",
    assetLabel:
      "Animated chat-agent replay showing conversation drift, matching sessions, and turn evidence",
    title: "Chat agents",
    task: "Resolve a customer support issue",
    failure: "Conversation drift and repeated stale advice",
    evidence: "User turn, agent turn, cluster count, unresolved outcome",
    fixAction: "Replay the bad turn and package the prompt/tool context that caused the loop",
  },
  {
    kind: "voice",
    assetLabel:
      "Animated voice-agent trace showing waveform, transcript, silence, and failed handoff evidence",
    title: "Voice agents",
    task: "Handle a live escalation",
    failure: "Missed handoff after silence and escalation language",
    evidence: "Transcript segment, silence duration, tool handoff result, latency",
    fixAction: "Pin the transcript and failed handoff as a regression target",
  },
];

export const landingIncidentLoopSteps = [
  {
    label: "Wrap the run",
    body: "Add Promptetheus around the existing agent entrypoint.",
  },
  {
    label: "Stream every signal",
    body:
      "Capture messages, tool calls, model outputs, artifacts, browser state, transcript state, and outcome checks.",
  },
  {
    label: "Detect the bad step",
    body:
      "Mark false success claims, drift, policy contradictions, state mismatches, and failed handoffs.",
  },
  {
    label: "Replay the evidence",
    body: "Open the exact step with trace context, artifact context, and outcome mismatch.",
  },
  {
    label: "Package the fix",
    body: "Generate a fix brief with root cause, patch context, and the regression target.",
  },
  {
    label: "Prevent repeats",
    body: "Queue a regression replay so the same failure mode cannot silently return.",
  },
] as const;

export const landingIncidentLoopStreamEvents = [
  {
    type: "message",
    body: "user: book Tuesday 2:00 PM Pacific",
    meta: "+12ms",
    tone: "prompt",
  },
  {
    type: "tool_call",
    body: "browser.navigate checkout.acme.test",
    meta: "+24ms",
    tone: "tool",
  },
  {
    type: "browser_action",
    body: "click li[data-time='02:00']",
    meta: "+31ms",
    tone: "tool",
  },
  {
    type: "message",
    body: "agent: booked 2pm slot",
    meta: "+38ms",
    tone: "model",
  },
  {
    type: "goal_check",
    body: "selected slot != requested slot",
    meta: "+48ms",
    tone: "warning",
  },
  {
    type: "replay_artifact",
    body: "dom snapshot + screenshot pinned",
    meta: "+57ms",
    tone: "artifact",
  },
  {
    type: "state",
    body: "checkout warning still visible",
    meta: "+63ms",
    tone: "state",
  },
  {
    type: "message",
    body: "detect: false success claim",
    meta: "+71ms",
    tone: "warning",
  },
] as const;

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
