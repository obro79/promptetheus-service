# Promptetheus

Promptetheus is debugging infrastructure for AI agents.

It is not a LangChain or LangGraph replacement. It is a Python-first SDK, local replay console, and hosted team workspace that instruments whatever agent stack developers already use, captures rich traces, detects likely failures, replays the exact bad step, and packages the fix for a coding agent.

## Core Loop

1. Observe the agent run.
2. Detect suspicious behavior.
3. Replay the exact session.
4. Attribute the critical failure step.
5. Generate a fix bundle.
6. Hand the fix to a coding agent.
7. Replay regression cases to prove the issue is prevented.

## Product Model

Promptetheus has two modes:

- **Local/open-source:** the SDK writes traces and replay artifacts to local `.promptetheus/` files, and `promptetheus dev` serves a local replay console.
- **Cloud/team:** the SDK sends authenticated events to Promptetheus Cloud, where teams get shared trace storage, incident clustering, alerts, repo integrations, fix-agent PRs, regression replay, RBAC, audit logs, retention controls, PII redaction, and Slack digests.

## Flagship Demo

The hackathon demo uses a browser agent because browser failures are visual, traceable, and painful.

The demo shows a browser agent booking a demo for Tuesday at 2pm Pacific. The agent selects 2:00 AM, ignores a timezone warning, and claims success. Promptetheus records the screen, streams trace events, detects the goal mismatch, replays the failure, generates a fix brief, and shows a PR preview plus regression replay.

## Docs

- [Docs Index](docs/README.md)
- [Product Strategy](docs/product-strategy.md)
- [Demo Plan](docs/demo-plan.md)
- [SDK Architecture](docs/sdk-architecture.md)
- [Technical Architecture](docs/architecture/technical-architecture.md)
- [Components](docs/architecture/components.md)
- [Implementation Plan](docs/architecture/implementation-plan.md)
- [Staged Scope](docs/architecture/staged-scope.md)
- [Build Plan](docs/build-plan.md)
- [Demo Data Plan](docs/demo-data-plan.md)
- [Linear Execution Plan](docs/linear-execution-plan.md)

## Current Decision

Build the hackathon submission as:

- `promptetheus` Python SDK
- `promptetheus dev`
- Local `.promptetheus/` trace and artifact store
- Browser-agent / Playwright adapter
- Side-by-side demo console
- Screen-recording replay artifact
- Failure detector and critical-step attribution
- Fix-agent PR handoff
- Before/after regression replay

## Business Shape

Open source gets adoption:

- Python SDK
- Local replay console
- Basic failure detectors
- Browser-agent adapter

Promptetheus Cloud is the paid product:

- Team workspaces
- Production trace storage
- Search across sessions
- Incident clustering over time
- Alerts when agent failures spike
- CI regression replay
- GitHub/Linear/Jira integrations
- Connected repo onboarding
- Agent-generated fix plans and PRs
- RBAC, audit logs, retention controls
- PII redaction
- SOC2-friendly deployment story
- Slack incident digests
