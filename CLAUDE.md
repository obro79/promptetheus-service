# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Current state (read this first)

This repo is the Promptetheus service repository. It excludes the Python SDK,
adapter integrations, local transport spool, and SDK-focused tests.

What actually exists today:

- `packages/promptetheus/promptetheus/server/` — FastAPI ingestion, analysis,
  fix-agent handoff, GitHub PR integration, MCP tools, storage, and regression
  fallback logic.
- `apps/console/` — Next.js console for sessions, replay, incidents, docs, and settings.
- `db/`, `infra/`, `scripts/`, `data/` — Supabase schema/RLS, deploy config,
  seed data, schema generation, and verification scripts.
- `tests/` — service, analysis, schema, DB, MCP, and regression tests.
- `docs/` — the full design: strategy, execution plan, technical contracts.

## Doc map (source of truth)

- **Build order, scope, ownership:** [docs/architecture/implementation-plan.md](docs/architecture/implementation-plan.md) — the Execution Plan. This is THE plan.
- **Contracts (event schema, locked 14-endpoint API table, storage layout, repo layout, Non-Goals):** [docs/architecture/technical-architecture.md](docs/architecture/technical-architecture.md).
- **Component responsibilities + interfaces + owners:** [docs/architecture/components.md](docs/architecture/components.md).
- **Strategy + hosted product architecture:** [docs/product-strategy.md](docs/product-strategy.md).
- **Staged scope + seams:** [docs/architecture/staged-scope.md](docs/architecture/staged-scope.md).
- **3-minute demo script + seed data:** [docs/demo-plan.md](docs/demo-plan.md).

Full index: [docs/README.md](docs/README.md).

## Architecture (the big picture)

Promptetheus instruments an agent run, detects likely failures, replays the exact bad step, and
packages a fix for a coding agent. State 0 is the real Supabase MVP:

```text
agent/SDK ──HTTP POST──▶ FastAPI ingestion (:4318/Railway) ──writes──▶ Supabase
                                  │                                      │
                                  └──SSE /api/stream──▶ Next.js console (:3000/Vercel)
                                                          └─triggers analysis/fix via FastAPI
```

Load-bearing invariants (violating these breaks the parallel build):

- **FastAPI is the write gateway for trace-derived state.** Sessions, events, artifacts, analysis
  results, incidents, PR links, and regression runs are written through FastAPI to Supabase.
  The SDK may spool failed deliveries under `.promptetheus/spool/`, but it must replay them through
  FastAPI; direct canonical file writes are not allowed.
- **Supabase is canonical storage.** Postgres stores structured trace/incident/regression state;
  private Supabase Storage stores replay artifacts; RLS enforces workspace isolation.
- **Analysis runs inside FastAPI, next to the data.** Detectors, fix-brief generation, fix-agent
  dispatch, GitHub PR, and regression logic live under
  `packages/promptetheus/promptetheus/server/{analysis,fix_agent,github,regression}/`. The console
  triggers these via FastAPI endpoints and renders results; it contains no detection logic.
- **Contract-first.** The event schema, the locked 14-endpoint API table, Supabase schema/RLS, and
  artifact contract are frozen before parallel work. The schema is defined twice — Python TypedDicts in
  `packages/promptetheus/promptetheus/schema.py` (source of truth) and zod in
  `apps/console/src/lib/schema.ts` — and any change must update **both** in the same commit.
## Layout

```text
packages/promptetheus/   # service package: FastAPI server + CLI
  promptetheus/
    schema.py            # TypedDict event definitions (source of truth)
    server/              # FastAPI write gateway + analysis/fix/regression modules
    cli.py               # promptetheus dev
apps/console/            # Next.js: demo, replay, incidents, workspace, AcmeMeet, API docs
db/migrations/           # Supabase schema + RLS policies
infra/                   # Railway/Vercel/Supabase config
scripts/seed.py          # incident-cluster seeder via FastAPI (~101 sessions, 7 clusters)
docs/                    # planning docs
```

## Commands

- **Python package** uses Python packaging; console uses Node + `pnpm` (Next.js + Tailwind +
  shadcn/ui). Develop on Python 3.14; the package declares `requires-python = ">=3.12"`.
- **Install + run:** `python -m pip install -e "packages/promptetheus[server,mcp]" && promptetheus dev`
  boots the local FastAPI ingestion gateway. CLI entry point is `promptetheus.cli:main`
  (`packages/promptetheus/pyproject.toml`).
- **Ports:** FastAPI ingestion on `:4318`, console on `:3000`; hosted equivalents are Railway and
  Vercel. SSE is authenticated and workspace-filtered.
- **Tests / lint:** `python -m pytest tests/server tests/analysis tests/fix_agent tests/regression tests/schema tests/db tests/mcp`
  and `pnpm --dir apps/console exec tsc --noEmit`.
- **Demo gate** is the end-to-end acceptance check — see the Execution Plan; if it breaks, all
  feature work stops until the spine is fixed.

## What not to build

Canonical Scope Boundaries: [docs/architecture/technical-architecture.md](docs/architecture/technical-architecture.md#scope-boundaries).
State 0 is now the **real MVP** (Supabase Postgres + Supabase Auth + Supabase Storage + RLS, FastAPI
on Railway, Next.js on Vercel, real GitHub PR, agnostic fix-agent). Anti-goals (never): full eval
platform, agent framework/orchestration, full policy DSL, generic analytics dashboard. Live-failure
paths ship a deterministic fallback toggle. Build order, the 30-epic backlog (P1–P30, ~10 issues
each), and acceptance criteria: [story-backlog.md](docs/architecture/story-backlog.md).

## Parallel work

Workstreams have non-overlapping owner boundaries (see the Execution Plan's Parallelization Rules).
Stay inside your workstream's directories; the contract in technical-architecture.md is the
negotiation surface, not the code.
