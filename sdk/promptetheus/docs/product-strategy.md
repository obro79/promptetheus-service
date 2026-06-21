# Product Strategy

## Positioning

Promptetheus is the debugging loop for production AI agents.

It should not be positioned as generic AI observability. Logs, traces, metrics, evals, and replay are necessary infrastructure, but they are the substrate. The differentiated product is what Promptetheus does with that data: detect likely failures, explain the root cause, and prevent recurrence with regression tests.

## One-Line Pitch

Promptetheus is an observability and replay platform that detects failed AI agent sessions, explains the root cause, and turns them into regression tests.

## Business Thesis

The open-source SDK is the adoption wedge. Promptetheus Cloud is the business.

Hobbyists and individual developers should be able to install the SDK, run the local replay console, and debug agents for free. Teams running agents in production should pay for shared history, collaboration, alerting, compliance, and integration into their engineering workflow.

Refined thesis:

> Promptetheus is open-source debugging infrastructure for agent developers, with a hosted incident-response platform for teams running agents in production.

Primary buyer:

- AI platform lead
- Developer tools lead
- Support automation lead
- Head of AI product
- Engineering manager owning production agents

Urgent pain:

> My agent is in production, customers or users are seeing bad outcomes, and I cannot tell which sessions failed, why they failed, or whether my fix actually worked.

## Developer Tool Track Framing

For the Berkeley AI Hackathon dev tool track, Promptetheus should be framed as AI agent infrastructure:

1. Observe: capture messages, tool calls, retrieval, browser actions, state changes, latency, errors, screenshots, screen recordings, and user feedback.
2. Detect: identify likely failures from behavior, goal mismatch, sentiment, repetition, unresolved intent, wrong tool use, retrieval mismatch, ignored warnings, or explicit complaints.
3. Replay: show the exact agent run, including screen recording and trace.
4. Attribute: locate the critical failure step and explain why it caused the bad outcome.
5. Fix: suggest a prompt patch, tool fix, state update, escalation rule, policy guard, or code change.
6. Prevent: turn the failure into a regression test or eval and replay the session after the fix.

## Packaging

Promptetheus should not replace LangChain, LangGraph, OpenAI Agents SDK, Vercel AI SDK, browser-use, or custom agent frameworks.

It should be a Python-first drop-in debugging layer:

```bash
pip install promptetheus
promptetheus dev
```

Product shape:

- Open-source SDK
- Normalized agent trace schema
- Framework adapters
- Local replay console
- Session replay artifacts with screen recordings
- Hosted Promptetheus Cloud for teams

Open source core:

- SDK
- Trace schema
- Local replay console
- Screen-recording replay artifact support
- Basic detectors
- Browser-agent adapter
- Regression replay primitives

Hosted/team product later:

- Team workspaces
- Production trace storage
- Search across sessions
- Production clustering
- Alerts when agent failures spike
- CI regression replay
- GitHub/Linear/Jira integrations
- Repo onboarding for watched agent codebases
- Agentic remediation: generate plans, open PRs, and attach regression replays
- RBAC, audit logs, retention controls
- PII redaction
- SOC2-friendly deployment story
- Slack incident digests

## Local vs Cloud Product Model

Free/local mode:

- SDK stores traces, logs, screenshots, DOM snapshots, and replay artifacts on the developer's machine.
- `promptetheus dev` reads local files and serves the replay console.
- This is ideal for hobbyists, prototypes, and local debugging.
- No account, no hosted storage, no team collaboration.

Cloud/team mode:

- SDK sends authenticated POST requests to Promptetheus Cloud.
- Promptetheus Cloud stores production traces, replay artifacts, derived incidents, and regression results.
- Teams get shared workspaces, cross-session search, clustering, alerts, Slack digests, CI integration, and compliance controls.
- Connected repos let Promptetheus hand incidents to a coding agent that plans a fix, opens a PR, and links the replay/regression evidence.

Cloud mode is the monetizable product because production teams pay for shared operational memory, not just local debugging.

## Promptetheus Cloud Product Surface

Promptetheus Cloud should be organized around six product surfaces.

### 1. Workspace & Projects

Purpose: give teams one shared place for all production agent behavior.

Features:

- Team workspace
- Projects per product or agent
- Environment tags: `dev`, `staging`, `prod`
- Agent registry: agent name, version, framework, repo, owner
- API keys per project/environment
- Usage view: sessions, events, replay artifact storage

Why it is paid:
Teams need shared operational memory. Local files do not solve collaboration, history, access control, or production retention.

### 2. Production Ingestion

Purpose: receive events and replay artifacts from production agents.

Features:

- Authenticated event ingestion
- Batched event upload
- Replay artifact upload
- Local SDK spooling when cloud delivery fails
- PII redaction before storage
- Sampling controls for high-volume agents
- Retention policies by project/environment

V1 scope:
Authenticated `POST` ingestion, trace storage, replay upload, basic redaction, and retention settings.

Not V1:
Full streaming infrastructure, multi-region artifact storage, and enterprise VPC deployment.

### 3. Incident Inbox

Purpose: turn raw traces into prioritized work.

Features:

- Failure detection
- Incident clustering over time
- Severity scoring
- Impact summary
- Top affected agents
- Regression status
- Owner assignment
- Status: `new`, `triaged`, `fixing`, `verified`, `ignored`

The key object is not a log. It is an incident:

```text
Incident = repeated failure pattern + affected sessions + root cause hypothesis + replay evidence + fix path
```

### 4. Replay & Search

Purpose: let engineers understand what happened without reading raw logs.

Features:

- Screen recording replay
- Trace timeline
- Tool calls
- Browser actions
- DOM snapshots
- Model messages
- State changes
- Goal checks
- Search across sessions
- Filters by agent, label, environment, version, user impact, and date

This is the core trust-builder. If the replay is good, the rest of the product feels real.

### 5. Alerts & Team Workflow

Purpose: get failures to the right humans quickly.

Features:

- Slack incident digest
- Spike alerts: "browser_goal_mismatch up 3x in last hour"
- Daily/weekly failure summaries
- Linear/GitHub/Jira issue creation
- Owner routing by agent or repo
- Incident comments and status history

V1 scope:
Slack digest and fake/real Linear or GitHub issue creation.

Not V1:
PagerDuty, complex escalation policies, on-call rotations.

### 6. Fix-Agent & Regression

Purpose: close the loop from production failure to reviewable code change.

Features:

- Connected repo onboarding
- Connected docs and knowledge sources
- Incident-to-fix brief
- Coding-agent plan generation
- PR preview
- Open PR against connected repo
- Regression test generation
- CI regression replay
- Link PR, incident, replay, and verification result
- MCP server or context bundle for exposing incident evidence to coding agents

This is the highest-leverage paid feature because it turns Promptetheus from "debugging viewer" into "agent reliability workflow."

V1 scope:
Connected repo as a demo object, connected docs as a simulated context source, generated fix brief, PR preview, and simulated or optional real PR.

Not V1:
Fully autonomous production code changes. Keep human review in the loop.

Agentic remediation flow:

```text
Incident
  ├── replay artifact
  ├── trace events
  ├── root-cause hypothesis
  ├── failing regression case
  ├── connected repo
  └── connected docs
        │
        ▼
Promptetheus MCP / context package
        │
        ▼
Coding agent
  ├── reads incident evidence
  ├── searches repo/docs
  ├── writes fix plan
  ├── opens PR
  └── links PR back to incident
```

The product should stay human-in-the-loop. Promptetheus should make it easy to dispatch an agent, review its plan, review its PR, and mark the incident as addressed by that PR.

### 7. Admin, Security, Compliance

Purpose: make production teams comfortable sending agent traces.

Features:

- RBAC
- Audit logs
- PII redaction
- Data retention controls
- SSO/SAML later
- SOC2-friendly controls
- Self-hosted/VPC later

V1 scope:
PII redaction story, project API keys, and retention settings.

Not V1:
Formal SOC2, enterprise SSO, VPC deployment.

Pricing intuition:

- Free: local SDK, local replay console, basic detectors.
- Team: shared cloud workspace, searchable trace history, incident clustering, alerts, integrations.
- Growth: usage-based by stored sessions, trace volume, or replay artifacts.
- Enterprise: SSO, RBAC, audit logs, PII controls, custom retention, self-hosted or VPC deployment.

CEO-review take:

Local debugging is a feature. Production incident response is the business. The hackathon demo should show the local SDK because that proves developer adoption, but the pitch should close on Promptetheus Cloud because that proves monetization.

## Differentiation

Compared to generic logs: logs show events. Promptetheus shows incidents and replayable sessions.

Compared to LangSmith/Langfuse/Phoenix: those tools are strong for tracing, evals, and debugging LLM apps. Promptetheus focuses on production failure triage for agents: behavioral failure detection, critical-step attribution, screen replay, fix generation, and regression replay.

Compared to Sentry: Sentry catches software exceptions. Promptetheus catches agent experience failures where the system technically works but the agent violates the goal.

Core sentence:

> Most observability tools tell you what your agent did. Promptetheus tells you which runs failed, why they failed, and what to fix next.
