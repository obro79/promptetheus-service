# Integration Plan — Major Branch Merge

This document catalogs all unmerged feature branches, their scope, conflicts,
and a proposed merge order for the major integration.

## Branch Inventory

### Tier 1 — Core backend features (merge first, foundation for others)

| Branch | Commits | Scope | Key Files |
|--------|---------|-------|-----------|
| `feat/self-heal-tests-console-agentspan` | 5 | Heal loop tests, Lambda source, real Agentspan orchestration, LLM-as-judge eval gate, eval scoreboard (console + API), Sentry wiring | `server/fix_agent/loop.py`, `server/fix_agent/orchestrator.py`, `server/evals/`, `server/observability/`, `apps/console/evals/`, `apps/console/incidents/detail/self-heal-panel.tsx` |
| `feat/sentry-wire` | 1 | Sentry init + heal-loop transaction spans | `server/observability/telemetry.py`, `server/app.py`, `server/fix_agent/loop.py` |

**Note**: `feat/sentry-wire` is a strict subset of `feat/self-heal-tests-console-agentspan` (same commit message). Merge `self-heal-tests-console-agentspan` first; sentry-wire becomes a no-op.

### Tier 2 — Redis vector memory + Devin runner + auto-heal triggers

| Branch | Commits | Scope | Key Files |
|--------|---------|-------|-----------|
| `devin/1782025011-redis-vector-devin-runner` | 4 | Redis vector similarity (expanded memory.py), Devin runner (Devin API sessions), event-driven auto-heal triggers, standalone demo script | `server/fix_agent/memory.py`, `server/fix_agent/runners/devin.py`, `server/fix_agent/triggers.py`, `server/app.py`, `server/fix_agent/loop.py` |
| `devin/1782030770-tf-redis-vectorset` | 3 | Terraform module for AWS EC2 Redis 8 (Vector Sets) + SSH/SSM access | `infra/terraform/redis-vectorset/` |

**Conflicts expected**: Both `devin/redis-vector` and `self-heal-tests` modify `loop.py`, `memory.py`, `app.py`. The `devin` branch adds triggers + Devin runner; `self-heal-tests` adds eval gate + audit spans. These must be manually reconciled.

### Tier 3 — Console UX (live logs, agent animation, dashboard)

| Branch | Commits | Scope | Key Files |
|--------|---------|-------|-----------|
| `feat/live-chat-agent-pipeline` | 2 | Live logs from API (auto-refresh poller), agent-fix-sequence animation, agent-agnostic root cause display, agent selector in heal panel | `apps/console/logs/page.tsx`, `components/incidents/detail/agent-fix-sequence.tsx`, `components/incidents/detail/self-heal-panel.tsx`, `lib/live-data.ts`, `lib/sample-heal.ts` |
| `of/logs-dashboard-pass2` | 4 | 3-pane forensic logs console: runs panel, trace panel, agent nav, URL state | `components/logs/logs-dashboard.tsx` (major rewrite), `logs-runs-panel.tsx`, `logs-trace-panel.tsx`, `logs-agent-nav.tsx` |

**Conflicts expected**: Both `live-chat-agent-pipeline` and `logs-dashboard-pass2` modify `logs/page.tsx` and `logs-dashboard.tsx`. The pass2 branch rewrites the dashboard completely (1463 lines removed), so the live-data integration from `live-chat-agent-pipeline` must be re-applied on top of the new layout.

Also: `live-chat-agent-pipeline` and `self-heal-tests-console-agentspan` both modify `self-heal-panel.tsx` — the `live-chat` version adds agent selector + animated sequence; the `self-heal-tests` version adds eval display + confidence meter. Both must be combined.

### Tier 4 — Deploy fixes (pick the winner)

| Branch | Commits | Description |
|--------|---------|-------------|
| `fix/deploy-distdir` | 1 | `NEXT_DIST_DIR=.next-build` for Vercel output discovery |
| `fix/deploy-hoisted` | 1 | `node-linker=hoisted` for Vercel pnpm resolve |
| `fix/deploy-pnpm` | 1 | Install pnpm in deploy workflow |
| `fix/deploy-standalone` | 1 | Standalone hoisted install for Vercel prebuilt |
| `fix/deploy-tracing` | 1 | Revert hoisted, use `outputFileTracingRoot` |
| `fix/deploy-verceljson` | 1 | Add `vercel.json` with `buildCommand: next build` |

**These are iterative attempts** at fixing the Vercel deployment. Based on current `main` (which has `vercel.json` already), the likely winner is `fix/deploy-distdir` (sets `NEXT_DIST_DIR`). The others are superseded or redundant. Need to verify which one Vercel actually needs.

### Tier 5 — Other (already merged content or cosmetic)

| Branch | Commits | Scope |
|--------|---------|-------|
| `of/add-chat-video` | 1 | Chat demo videos (already in main via PR #26) |
| `of/demo-page` | 2 | Demo page updates |
| `of/logs-dashboard-pass2` | 4 | See Tier 3 |

---

## Proposed Merge Order

```
Step 1: feat/self-heal-tests-console-agentspan → main
   └─ Brings: heal loop tests, eval gate, Agentspan orchestration,
      eval scoreboard API + console page, Sentry, Lambda example
   └─ Subsumes: feat/sentry-wire (delete after)
   └─ Conflicts: None (clean rebase expected)

Step 2: devin/1782025011-redis-vector-devin-runner → main
   └─ Brings: Redis vector memory, Devin runner, auto-heal triggers
   └─ Conflicts: loop.py (eval audit + triggers), memory.py (expanded),
      app.py (trigger hook in event ingestion)
   └─ Resolution: Merge both sets of changes; triggers fire AFTER eval
      audit is written; memory.py takes the expanded version

Step 3: devin/1782030770-tf-redis-vectorset → main
   └─ Brings: Terraform for Redis 8 EC2
   └─ Conflicts: Only .gitignore (trivial)

Step 4: of/logs-dashboard-pass2 → main
   └─ Brings: 3-pane forensic logs with trace overlay
   └─ Conflicts: logs-dashboard.tsx is a full rewrite; clean if merged
      before live-chat-agent-pipeline

Step 5: feat/live-chat-agent-pipeline → main
   └─ Brings: Live data API reads, auto-refresh poller, agent-fix-sequence
      animation, agent selector in heal panel
   └─ Conflicts: self-heal-panel.tsx (combine agent selector + eval display),
      logs/page.tsx (apply live-data on top of pass2 layout)
   └─ This is the UX crown jewel for the demo

Step 6: fix/deploy-distdir → main (or whichever deploy fix is needed)
   └─ Test on Vercel to confirm; delete the other fix/ branches
```

## Conflict Matrix

Files touched by multiple branches that WILL conflict:

| File | Branches | Resolution Strategy |
|------|----------|-------------------|
| `server/fix_agent/loop.py` | self-heal-tests, devin-runner | Both add code; combine eval gate + trigger hook |
| `server/fix_agent/memory.py` | self-heal-tests (tests), devin-runner (expanded) | Take devin-runner's expanded version; ensure tests still pass |
| `server/app.py` | self-heal-tests (+eval endpoint), devin-runner (+trigger in events) | Additive; both register new endpoint/hook |
| `self-heal-panel.tsx` | self-heal-tests, live-chat-agent-pipeline | Combine: agent selector from live-chat + eval/confidence from self-heal-tests |
| `logs/page.tsx` | logs-dashboard-pass2, live-chat-agent-pipeline | Apply live-data integration onto the pass2 rewrite |
| `logs-dashboard.tsx` | logs-dashboard-pass2, live-chat-agent-pipeline | pass2 is a rewrite; live-chat changes must be re-applied |

## Handoff Notes — feat/live-chat-agent-pipeline

This branch adds the **demo-critical UX**: when the user triggers heal from the
console, they see a real-time animated sequence of the coding agent (Claude Code
or Devin) working the fix step by step.

### What it adds:
1. **`agent-fix-sequence.tsx`** — animated step list: Dispatched → Branch → Read
   bundle → Located root cause → Edited file → Ran regression → Opened PR.
   Configurable agent (Claude Code or Devin).

2. **Agent selector in `self-heal-panel.tsx`** — dropdown to pick which coding
   agent handles the fix (Claude Code / Devin). Sends the choice to the backend.

3. **`lib/live-data.ts`** — fetches sessions, events, analysis from the live
   FastAPI server (not the bundled seed data). Returns null when API unreachable.

4. **`LogsAutoRefresh`** — client component that calls `router.refresh()` on a
   4-second interval when live data is flowing.

5. **Server: `detectors.py`** — adds agent-agnostic root-cause extraction (marks
   incident runs as failed regardless of which agent framework produced them).

6. **Server: `app.py`** — adds `GET /api/logs/live` endpoint for live log reads.

### Integration requirements:
- The animated sequence needs `HealReport` type to include `incident_id`,
  `pr.changed_files`, and `pr.branch`. These already exist in the types on
  `self-heal-tests`.
- The agent selector (`CodingAgent` type) must be wired to the backend's
  `PROMPTETHEUS_FIX_AGENT_RUNNER` env var or passed in the heal request body.
- The live-data fetch path must work with the 3-pane logs layout from
  `logs-dashboard-pass2`.

### What still needs building for full integration:
- Backend: accept `runner` param in `POST /api/incidents/{id}/heal` body so the
  console agent selector actually routes to the chosen runner.
- Backend: the Devin runner (`devin/redis-vector` branch) must be available for
  the "Devin" option to do real work.
- Console: merge the animated sequence with the eval display from
  `self-heal-tests` — show animation DURING the heal, then reveal the full
  verified report (eval scores, regression flip, PR) AFTER.

---

## Pre-Merge Checklist

For each merge step:

- [ ] Checkout the branch, rebase onto current main
- [ ] Resolve conflicts per the strategy above
- [ ] Run tests: `python -m pytest tests/ -q`
- [ ] Run typecheck: `cd packages/promptetheus && python -m mypy` + `cd apps/console && pnpm exec tsc --noEmit`
- [ ] Run schema parity: `python scripts/generate_schema_ts.py && git diff --exit-code apps/console/src/lib/schema.ts`
- [ ] Verify demo gate: seed + trigger heal from UI
- [ ] Create PR for Devin Review

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `logs-dashboard.tsx` rewrite causes loss of live-data features | High | Medium | Merge pass2 BEFORE live-chat; re-apply live features on new layout |
| `self-heal-panel.tsx` triple-conflict | High | Low | Clear ownership: eval from tests branch, animation from live-chat |
| Devin runner untested in integration | Medium | High | Test with mock Devin API first; real Devin needs `PROMPTETHEUS_DEVIN_API_TOKEN` |
| Deploy fix branches conflict with each other | Low | Low | Only pick one; delete the rest |
| Redis dependency in prod without Terraform | Medium | Medium | Merge Terraform early; can also use managed Redis (ElastiCache) instead |

---

## After the Merge

Post-integration, the stack will support:

1. **UI trigger**: Click "Self-heal" → pick agent → animated progress → verified PR
2. **Auto-heal trigger**: Events land → failure detected → background heal loop fires
3. **Multi-runner**: Claude Code, Devin, or deterministic fallback
4. **Fix memory**: Redis-backed similarity lookup → warm-start from past fixes
5. **Live timeline**: Redis Streams → console real-time heal progress
6. **Eval scoreboard**: LLM-as-judge aggregated metrics across all heals
7. **3-pane logs**: Forensic drill-down with live ingestion + auto-refresh
8. **Observability**: Sentry transactions on every heal loop + eval span
9. **Infrastructure**: Terraform Redis 8 EC2 for vector similarity
