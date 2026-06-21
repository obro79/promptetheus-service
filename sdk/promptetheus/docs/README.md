# Promptetheus Docs

## Active Plan

Read these when implementing or coordinating work:

- [Product Strategy](product-strategy.md)
- [Demo Plan](demo-plan.md)
- [SDK Architecture](sdk-architecture.md)
- [Promptetheus MCP](mcp.md)
- [Technical Architecture](architecture/technical-architecture.md)
- [Components](architecture/components.md)
- [Implementation Plan](architecture/implementation-plan.md)
- [Staged Scope](architecture/staged-scope.md)
- [PyPI Setup](architecture/pypi-setup.md)
- [Build Plan](build-plan.md)
- [Demo Data Plan](demo-data-plan.md)
- [Linear Execution Plan](linear-execution-plan.md)

## Supporting Material

Use these for context, pitch refinement, and examples:

- [Competitive Landscape](research/competitive-landscape.md)
- [Reference Examples](reference/reference-examples.md)
- [Office Hours + CEO Review](reviews/office-hours-ceo-review.md)

## Archive

- [Archived Full Draft](archive/archive-start-full.md)

## Current Architecture Snapshot

```text
Python SDK
  ├── local transport -> .promptetheus/ files -> promptetheus dev
  └── cloud transport -> Promptetheus Cloud
                            ├── incident inbox
                            ├── replay evidence
                            ├── connected repo/docs
                            ├── fix-agent PR workflow
                            └── regression replay
```

The demo spine remains:

```text
Browser agent failure
  -> screen recording + trace
  -> goal-state attribution
  -> incident detail
  -> fix-agent PR preview
  -> regression replay
```
