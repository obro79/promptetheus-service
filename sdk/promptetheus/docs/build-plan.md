# Build Plan

## Must Build

1. `promptetheus` Python SDK
2. Browser-agent / Playwright Python adapter
3. Local ingestion API
4. Side-by-side demo console
5. Screen-recording replay artifact support
6. Sample browser-agent sessions
7. Live trace stream
8. Failure detector workbench
9. Critical failure step detection
10. Root cause and fix generator
11. Fix-agent handoff with PR preview
12. Before/after regression replay
13. Local-vs-cloud transport story in the pitch

## Should Build

- Tool-call and browser-action timeline
- Goal mismatch and ignored warning evidence chips
- User impact heat
- Generated Linear/GitHub issue draft
- Prompt patch / guard rule output
- `.promptetheus/` local file browser in the console
- Mock Promptetheus Cloud workspace panel

## Nice To Have

- Live judge-triggered browser-agent task
- Prompt injection incident
- Slack alert mock
- LangChain or LangGraph adapter
- Real GitHub PR creation
- Cloud ingestion stub with API key

## 24-Hour Execution Plan

### Hour 0-2: Setup

- Create Next.js app
- Set up Tailwind/shadcn
- Define trace schema
- Scaffold `promptetheus` Python package

### Hour 2-5: SDK + Ingestion

- Implement `trace.start()`
- Implement trace event helpers
- Implement local file transport under `.promptetheus/`
- Implement local ingestion endpoints
- Implement replay artifact upload/save for screen recordings
- Seed browser-agent sessions

### Hour 5-9: Side-by-Side Demo Console

- Left pane browser-agent run
- Right pane live trace stream
- Evidence chips lighting up as events arrive
- Screen recording, screenshot, and DOM snapshot panels
- Critical failure highlight

### Hour 9-12: Replay View

- Timeline UI
- Message/tool/browser/retrieval events
- Synchronized screen recording replay
- Failure freeze-frame
- Original goal vs observed browser state comparison

### Hour 12-15: Classification

- Implement rule-based labels
- Add LLM classifier if stable
- Store session status and labels

### Hour 15-16: Lightweight Incident Aggregation

- Group sessions by failure label
- Show severity
- Show representative examples

### Hour 16-18: Fix Generator

- Generate root cause
- Generate suggested fix
- Generate regression test
- Generate fix-agent task brief

### Hour 18-20: Fix Agent + Regression Replay

- Mock or real coding-agent PR preview
- Show files changed and test added
- Show repo onboarding as already connected for the demo
- Implement before/after pass-rate simulation
- Show failed sessions becoming passing or user-confirmation cases

### Hour 20-22: Demo Polish

- Add AcmeMeet browser-demo branding
- Smooth transitions
- Seed impressive data
- Make UI feel production-grade

### Hour 22-24: Backup + Submission

- Record backup demo
- Prepare fallback screenshots
- Finalize Devpost copy
- Practice 3-minute pitch

## Do Not Build

- Full multi-tenant auth
- Real customer support integrations
- Real Linear/Jira OAuth
- Full GitHub app installation flow
- Complex vector DB infrastructure
- Full eval platform
- Full policy language
- Full agent framework
- Multi-agent orchestration
- Deep observability backend
- Generic analytics dashboard
- Real production deployment complexity
