# Promptetheus — Current Architecture (as of main + unmerged branches)

## System Overview

Promptetheus instruments AI-agent runs, detects likely failures, replays the
exact bad step, and packages a fix for a coding agent (Claude Code, Devin, or
deterministic fallback). A human merges; no auto-merge.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Agent / SDK                                                             │
│  Instruments agent runs, posts traces via HTTP                           │
│  (OpenTelemetry-style spans, tool calls, goal checks)                    │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ POST /api/traces
                                   │ POST /api/traces/{id}/events
                                   │ POST /api/traces/{id}/artifacts
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  FastAPI Ingestion Gateway (:4318 locally / Railway in prod)             │
│  packages/promptetheus/promptetheus/server/                              │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐   │
│  │ app.py — 14 locked endpoints (frozen contract)                    │   │
│  │  • Trace ingestion (POST /api/traces, events, artifacts)          │   │
│  │  • Session/event reads (GET /api/sessions, /api/sessions/{id})    │   │
│  │  • Analysis trigger (POST /api/traces/{id}/analyze)               │   │
│  │  • Incident CRUD (GET/PATCH /api/incidents)                       │   │
│  │  • Self-heal trigger (POST /api/incidents/{id}/heal)              │   │
│  │  • Regression runs (POST /api/incidents/{id}/regression-runs)     │   │
│  │  • Eval scoreboard (GET /api/evals/scoreboard)                    │   │
│  │  • Project/workspace settings                                     │   │
│  │  • SSE live stream (GET /api/stream)                              │   │
│  │  • Health (GET /health)                                           │   │
│  └───────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌─────────────────────┐  ┌──────────────────────┐  ┌────────────────┐  │
│  │ analysis/           │  │ fix_agent/            │  │ regression/    │  │
│  │  • detectors.py     │  │  • loop.py (bounded)  │  │  • runner.py   │  │
│  │  • engine.py        │  │  • orchestrator.py    │  │  (replay the   │  │
│  │  (pattern matchers  │  │  • runners/           │  │   failing case)│  │
│  │   → incidents)      │  │    ├─ claude.py       │  └────────────────┘  │
│  └─────────────────────┘  │    ├─ devin.py (*)    │                      │
│                           │    ├─ deterministic.py │  ┌────────────────┐  │
│  ┌─────────────────────┐  │    └─ codex.py        │  │ evals/         │  │
│  │ github/             │  │  • verifier.py        │  │  • judge.py    │  │
│  │  Opens real PRs on  │  │  • memory.py (Redis)  │  │  • runner.py   │  │
│  │  connected repos    │  │  • triggers.py (*)    │  │  (LLM-as-judge │  │
│  └─────────────────────┘  └──────────────────────┘  │   scoreboard)  │  │
│                                                      └────────────────┘  │
│  ┌─────────────────────┐  ┌──────────────────────┐  ┌────────────────┐  │
│  │ db/                 │  │ observability/        │  │ stream.py      │  │
│  │  • factory.py       │  │  • telemetry.py      │  │ (SSE hub for   │  │
│  │  • postgres.py      │  │  (Sentry init +      │  │  live events)  │  │
│  │  • store.py (proto) │  │   heal transactions) │  └────────────────┘  │
│  └─────────────────────┘  └──────────────────────┘                      │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ reads/writes
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Supabase (Postgres + Storage + Auth + RLS)                              │
│  db/migrations/                                                          │
│  • Sessions, events, incidents, analysis results, audit log              │
│  • Private artifacts bucket (replay videos, screenshots)                 │
│  • RLS: workspace isolation                                              │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Next.js Console (:3000 locally / Vercel in prod)                        │
│  apps/console/                                                           │
│                                                                          │
│  Pages:                                                                  │
│  ├── /               (landing + demo)                                    │
│  ├── /incidents      (failure inbox: list → detail → self-heal panel)    │
│  ├── /sessions       (session replay with trace timeline)                │
│  ├── /logs           (live logs dashboard with auto-refresh) (*)         │
│  ├── /evals          (LLM-as-judge scoreboard) (*)                       │
│  ├── /agents         (agent registry)                                    │
│  ├── /settings       (API keys, repo connection, retention)              │
│  ├── /docs           (embedded API reference + quickstart)               │
│  └── /demo           (3-min demo flow)                                   │
│                                                                          │
│  Key components:                                                         │
│  • SelfHealPanel — "Self-heal" button → POST /api/incidents/{id}/heal    │
│  • AgentFixSequence — animated step-by-step agent working vis (*)        │
│  • LogsAutoRefresh — client poller for live ingestion (*)                │
│  • EvalScoreboard — aggregated fix-quality metrics (*)                   │
│                                                                          │
│  Auth: Supabase JWT from localStorage OR env console token               │
│  API client: apps/console/src/lib/promptetheus-api.ts                    │
└──────────────────────────────────────────────────────────────────────────┘

(*) = exists on unmerged feature branches, not yet on main
```

## Optional Infrastructure (degrades gracefully without)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Redis (REDIS_URL)                                                       │
│  • Fix memory: past incident→fix pairs with vector similarity            │
│    (Voyage embeddings or lexical fallback)                                │
│  • Heal timeline: Redis Streams (XADD/XRANGE) for live heal progress     │
│  • Dedup: in-flight markers prevent duplicate auto-heal runs             │
│  Without Redis: all features silently no-op; loop works identically      │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│  Anthropic API (ANTHROPIC_API_KEY)                                        │
│  • Claude runner: real fix generation via claude-opus-4-8                      │
│  • LLM critique: second Claude call to verify fix quality                │
│  • Eval judge: LLM-as-judge scoring                                      │
│  Without key: deterministic fallback runner + regression-only gate        │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│  Agentspan (optional orchestrator wrapper)                               │
│  • Durable execution: heal loop wrapped as Agentspan @tool               │
│  • Provides execution_id / workflow graph for demo artifacts              │
│  • Falls back to in-process if SDK missing or server unreachable         │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│  Sentry (SENTRY_DSN)                                                     │
│  • Heal-loop transaction tracing                                         │
│  • Eval verdict spans                                                    │
│  • Error reporting                                                       │
└──────────────────────────────────────────────────────────────────────────┘
```

## Self-Heal Loop (the core product flow)

```
User clicks "Self-heal incident" in console
         │
         ▼
POST /api/incidents/{id}/heal
         │
         ▼
┌─── orchestrator.py ───────────────────────────────────┐
│  Selects: inprocess (default) or agentspan             │
│                                                        │
│  ┌─── loop.py (bounded, max N attempts) ───────────┐  │
│  │                                                   │  │
│  │  1. Build redacted incident bundle                │  │
│  │  2. Query Redis for similar past fix (warm start) │  │
│  │  3. diagnose_step() → runner.run(bundle)          │  │
│  │     ├─ ClaudeRunner (claude-opus-4-8, structured)      │  │
│  │     ├─ DevinRunner (Devin API session) (*)        │  │
│  │     └─ DeterministicRunner (fallback)             │  │
│  │  4. verify_step() → verifier.verify()             │  │
│  │     ├─ LLM critique (Claude second opinion)       │  │
│  │     └─ Regression replay (re-run failing case)    │  │
│  │  5. If verified → pr_step() → open GitHub PR      │  │
│  │     If NOT verified → loop back to step 3         │  │
│  │       (with critique as context)                  │  │
│  │  6. After all attempts: escalate or PR opened     │  │
│  │                                                   │  │
│  │  Each attempt: audit + timeline_publish (Redis)   │  │
│  └───────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
         │
         ▼
HealReport → console renders trail, PR link, regression results
```

## Deployment Topology

| Component | Local | Production |
|-----------|-------|------------|
| FastAPI server | `uvicorn :4318` | Railway (Dockerfile) |
| Next.js console | `pnpm dev :3000` | Vercel |
| Database | InMemoryStore | Supabase Postgres |
| Artifact storage | Local filesystem | Supabase Storage |
| Auth | Dev tokens (`pt_dev_key`, `pt_console_token`) | Supabase Auth + JWT |
| Redis | Optional `localhost:6379` | AWS EC2 Redis 8 (Terraform) |
| Observability | None | Sentry |

## Environment Variables

### Server (FastAPI / Railway)
| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` / `SUPABASE_DB_URL` | Prod | Postgres connection |
| `PROMPTETHEUS_STORE` | No | `postgres` or `memory` (auto-detected) |
| `ANTHROPIC_API_KEY` | No | Claude runner + critique + eval |
| `REDIS_URL` | No | Fix memory + timeline |
| `VOYAGE_API_KEY` | No | Vector embeddings (falls back to lexical) |
| `SENTRY_DSN` | No | Error/perf tracking |
| `SUPABASE_URL` | Prod | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Prod | Supabase admin key |
| `SUPABASE_JWT_SECRET` | Prod | JWT verification |
| `PROMPTETHEUS_SERVER_TOKEN` | Prod | Internal auth token |
| `PROMPTETHEUS_CONSOLE_ORIGINS` | Prod | CORS (default: localhost:3000) |
| `PROMPTETHEUS_AUTO_HEAL` | No | `1` to enable event-triggered auto-heal (*) |
| `PROMPTETHEUS_FIX_AGENT_RUNNER` | No | `claude`, `devin`, `deterministic` |
| `PROMPTETHEUS_FIX_AGENT_MODEL` | No | Override Claude model |
| `PROMPTETHEUS_ORCHESTRATOR` | No | `inprocess` or `agentspan` |
| `PROMPTETHEUS_HEAL_MAX_ATTEMPTS` | No | Default 3 |
| `GITHUB_TOKEN` | No | For opening real PRs |
| `GITHUB_REPO` | No | Target repo for PRs |

### Console (Next.js / Vercel)
| Variable | Required | Purpose |
|----------|----------|---------|
| `NEXT_PUBLIC_PROMPTETHEUS_API_URL` | Yes | FastAPI URL |
| `NEXT_PUBLIC_PROMPTETHEUS_CONSOLE_TOKEN` | Dev | Bearer token for API |
| `NEXT_PUBLIC_SUPABASE_PROJECT_REF` | Prod | Supabase JWT discovery |

## Key Contracts

1. **Event schema**: Python TypedDicts in `packages/promptetheus/promptetheus/schema.py`
   (source of truth) mirrored as Zod in `apps/console/src/lib/schema.ts`
2. **14 locked endpoints**: Frozen API table in `docs/architecture/technical-architecture.md`
3. **Fix output**: NEW-FILE unified diffs confined to `allowed_paths`
4. **Security**: Incident bundles are redacted (no secrets/PII in fix-agent prompts)
5. **Degradation**: Every optional dependency has a safe no-op fallback
