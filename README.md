# Promptetheus Service

Promptetheus service infrastructure for AI-agent debugging: FastAPI ingestion,
failure analysis, replay artifacts, Supabase-backed storage, and the Next.js
console.

This repository intentionally excludes the Python SDK, adapter integrations,
local transport spool, and SDK-focused tests. Ingestion clients talk to the
FastAPI API directly or through an SDK maintained separately.

## What is included

- `packages/promptetheus/promptetheus/server/` - FastAPI write gateway, analysis,
  fix-agent handoff, GitHub PR integration, MCP tools, storage, and regression
  fallback logic.
- `apps/console/` - Next.js console for sessions, replay, incidents, docs, and
  settings.
- `db/` and `infra/` - Supabase migrations/RLS and deploy configuration.
- `scripts/` and `data/` - seed data, schema generation, and migration checks.
- `tests/` - service, analysis, schema, DB, MCP, and console-adjacent contract
  tests.
- `docs/` - architecture, product, operations, UI, and demo planning docs.

## Local checks

```bash
python -m pip install -e "packages/promptetheus[dev,mcp]"
python -m pytest tests/server tests/analysis tests/fix_agent tests/regression tests/schema tests/db tests/mcp
pnpm install
pnpm --dir apps/console exec tsc --noEmit
```

## Runtime

- FastAPI service: `:4318`
- Console: `:3000`
- Storage: Supabase Postgres/Auth/Storage with RLS

## Self-host smoke dashboard

FastAPI exposes a tiny server-rendered dashboard at `/self-host` for local or
self-host smoke tests. It is enabled automatically for the in-memory dev store.
For Postgres-backed self-hosts, opt in explicitly:

```bash
export PROMPTETHEUS_SELF_HOST_DASHBOARD=1
export PROMPTETHEUS_API_URL=http://127.0.0.1:4318
export PROMPTETHEUS_API_KEY=pt_dev_key
```

Use `/self-host.json` for the same sessions/events snapshot as JSON.

## MCP credentials

The Promptetheus MCP server can read project-scoped sessions, trace events,
analysis, and incident context with the same project API key used by the SDK:

```bash
export PROMPTETHEUS_API_KEY=pt_live_...
```

Set `PROMPTETHEUS_CONSOLE_TOKEN` only for owner-only console workflows.

Start with [AGENTS.md](AGENTS.md) for repo-specific build guidance and
[docs/README.md](docs/README.md) for the documentation index.
