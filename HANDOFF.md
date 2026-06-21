# Handoff — wiring Devin into the heal loop

_For the dev taking the coding-agent (Devin) integration. Everything upstream of
the "fix" step is implemented and running; this doc is the seam you plug into._

## TL;DR

The whole pipeline is live and real **up to the fix step**:

```
chat agent (silent UI) ──SDK──▶ FastAPI ingest ──auto-analyze──▶ incident
       │                                                            │
       └── trace events                          console /logs (live) ──┐
                                                                        ▼
                              heal loop:  diagnose ──▶ verify (eval) ──▶ PR
                                             ▲
                                    YOU REPLACE THIS with Devin
```

Today `diagnose` runs a **deterministic `FixAgentRunner`** that writes a guard
diff, and `pr_step` opens a real PR (or a fallback preview). Your job: swap the
fix step to **dispatch the incident to Devin**, let Devin fix the real bug in the
agent repo, and return the **real PR** Devin opens.

## The real bug Devin fixes

- Repo: **`github.com/kusum-bhattarai/demo-chat-agent`**
- File: **`refund.py`** → `compute_refund()` multiplies every refund by a stale
  `REFUND_RATE = 10`, so the agent issues **$200** for a **$20** order.
- Correct fix: set `REFUND_RATE = 1` (or refund the eligible amount directly) →
  the agent issues $20 and the `goal_check` passes.
- Devin needs **repo access** to this repo + a target branch.

## The seam (where you plug in)

All paths under `packages/promptetheus/promptetheus/server/fix_agent/`:

| File · symbol | What it is | What to do |
| --- | --- | --- |
| `runner.py` · `FixAgentRunner.run(bundle) -> FixAgentResult` | The deterministic fix runner | Add a `DevinRunner` with the **same interface**; it calls the Devin API and returns a `FixAgentResult` carrying Devin's PR/diff |
| `runner.py` · `build_incident_bundle(store, incident)` | Builds the **fix brief** | Your Devin prompt is derived from this — see shape below |
| `loop.py` · `diagnose_step(bundle, runner, …)` | Calls `runner.run(...)` | Point it at `DevinRunner` (env/flag-gated so the deterministic path stays as fallback) |
| `loop.py` · `pr_step(incident, bundle, fix)` | Opens the PR | When Devin opens its own PR, return that instead of creating one |
| `orchestrator.py` · `_run_agentspan(...)` | Agentspan durable execution wrapping the loop | The Devin dispatch should be the Agentspan-orchestrated step ("Agentspan dispatches → Devin fixes") |

Keep the runner interface intact so the in-process loop, the Agentspan path, and
the tests all keep working; gate Devin behind an env var (e.g.
`PROMPTETHEUS_FIX_RUNNER=devin`) so the deterministic fallback remains the
stage-safe default.

## The fix brief — `build_incident_bundle(...)` returns

```python
{
  "incident": {id, workspace_id, project_id, label, severity, status, confidence, session_count},
  "source": "...",                  # agent origin tag
  "representative_session_id": "...",
  "user_goal": "Refund the customer the correct amount for their order",
  "critical_step_seq": 16,
  "root_cause": "the action at step 16 contradicted the user's stated goal …; "
                "root cause: no final outcome verification before claiming success.",
  "events": [ ...redacted events around the critical step (retrieval $20, tool_call $200, goal_check)... ],
  "allowed_paths": ["agents/"],     # security boundary for any generated change
  "connected_repo": { project_id, repo, allowed_paths, stub },
  "regression_case": {...},
  ...
}
```

Turn `root_cause` + the `retrieval`-vs-`tool_call` evidence into the Devin
prompt: "Refund issued $200 for a $20-refundable order; locate and fix the
over-refund in the repo." Point `connected_repo.repo` at `demo-chat-agent`.

## `FixAgentResult` (what `DevinRunner.run` must return)

`runner.py` → fields: `plan`, `diff`, `metadata`, `summary`, `changed_files`,
`runner` (set to `"devin"`), `confidence`, `evidence_refs`, `fallback=False`.
Put Devin's session id + PR url in `metadata` so the console can link them.

## Verify step (after Devin's PR)

`verifier.py` → `verify()` runs the **LLM-as-judge eval** (before→after) + a
regression re-run. Keep it as-is for the first cut — it already gates the PR. If
there's time, add a real check that re-runs `compute_refund` on Devin's branch
and asserts $20.

## Surfacing the real PR in the console

The heal report's `pr` flows to the self-heal panel (`apps/console/.../incidents/
detail/self-heal-panel.tsx` → `PrCard`). Set `pr.pr_url` to Devin's PR and the
panel renders an "Open PR ↗" link. The agent-dispatch animation
(`agent-fix-sequence.tsx`) already narrates "dispatched to Devin → … → opened
PR"; back its final step with the real Devin PR url.

## Run it locally (3 processes)

```bash
# 1) FastAPI ingest/heal gateway (backend venv)
.venv/bin/python -m uvicorn promptetheus.server.app:create_app --factory --port 4318

# 2) chat agent web UI (its own venv), wired to the gateway
cd demo-chat-agent
PROMPTETHEUS_ENDPOINT=http://127.0.0.1:4318 PROMPTETHEUS_API_KEY=pt_dev_key \
  PROMPTETHEUS_CONSOLE_TOKEN=pt_console_token \
  .venv/bin/python -m uvicorn server:app --port 8000

# 3) console
pnpm --dir apps/console dev   # needs apps/console/.env.local (API url + pt_console_token)
```

Click through a refund at `localhost:8000` → the run + incident appear at
`localhost:3000/logs` → "Self-heal" runs the loop (your Devin runner). Dev auth:
console token `pt_console_token`, ingest api key `pt_dev_key`, workspace `ws_dev`,
project `proj_dev`.

## Env you'll add

- `DEVIN_API_KEY` (+ whatever base url the Devin API needs)
- `PROMPTETHEUS_FIX_RUNNER=devin` to switch the runner on
- Devin connected to `kusum-bhattarai/demo-chat-agent`
