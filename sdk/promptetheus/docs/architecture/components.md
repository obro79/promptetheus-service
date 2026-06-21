# Components

Each component below has one owner boundary (per [linear-execution-plan.md](../linear-execution-plan.md)), a defined interface, and explicit non-goals. If two workstreams need to touch the same component, the contract in [technical-architecture.md](technical-architecture.md) is the negotiation surface — not the code.

## 1. Python SDK (`packages/promptetheus/promptetheus/`)

**Responsibility:** the developer-facing instrumentation API. `trace.start()` returns a `Session` with event helpers; the transport delivers events without the caller caring where they go.

**Public interface:**

- `trace.start(agent, session_id, user_goal, transport="local"|"cloud", ...)`
- `session.message()`, `session.tool_call()`, `session.tool_result()`
- `session.browser_action()`, `session.dom_snapshot()`, `session.screenshot()`
- `session.replay_artifact()`, `session.goal_check()`, `session.state_change()`
- `session.end(status)`

**Internals:**

- `schema.py` — TypedDict event definitions, the cross-component source of truth.
- `transport/local.py` — batched HTTP POSTs to the local FastAPI server; falls back to direct `.promptetheus/` file writes if the server is unreachable (demo never blocks on a dead server).
- `transport/cloud.py` — stub: same API, batched authenticated POSTs + local spool. Exists to make the local-vs-cloud pitch real in code; does not need a live backend.

**Does not:** analyze traces, render anything, or know about incidents.

## 2. Playwright Adapter (`promptetheus/adapters/playwright.py`)

**Responsibility:** drop-in instrumentation for browser agents. Wraps a Playwright `Page` so clicks, fills, and navigations auto-emit `browser_action`; helpers capture `dom_snapshot` and `screenshot`; manages video recording start/stop and emits the `replay_artifact` with the `event_time_map`.

**Design note:** ergonomics modeled on LangSmith's `wrap_openai` — wrap the object the developer already has, telemetry falls out for free. Playwright is the flagship adapter, not a special case: it must stay a thin layer over the public `Session` API so future adapters (LangChain/LangGraph, OpenAI Agents SDK) follow the same pattern.

**Does not:** make agent decisions or alter page behavior.

## 3. FastAPI Ingestion Server (`promptetheus/server/`)

**Responsibility:** the only writer to `.promptetheus/`. Receives events and artifacts, persists them, rebroadcasts live events over SSE, and serves read endpoints + static artifacts to the console. It is also the public integration surface: any agent in any language can POST schema-conformant events directly (Level 1 of the integration ladder in [technical-architecture.md](technical-architecture.md#integration-surfaces-generalizability-ladder)) — the Python SDK gets no private API.

**Interface:** the 9-endpoint contract in [technical-architecture.md](technical-architecture.md#ingestion-api-contract).

**Does not:** run detectors or LLMs. Analysis results are computed by the console and stored here via `PUT /api/traces/{id}/analysis`. Keeping this server dumb keeps it stable while the analysis engine iterates.

## 4. CLI (`promptetheus/cli.py`)

**Responsibility:** `promptetheus dev` — start the FastAPI server, start (or point to) the console, print URLs. One command boots the whole demo environment with fixed ports and CORS preconfigured.

**Does not:** contain business logic. Thin process orchestration only.

## 5. Next.js Console (`apps/console/`)

**Responsibility:** every pixel of the product. One app, five surfaces:

| Route | Surface |
| --- | --- |
| `/demo` | Side-by-side demo console: AcmeMeet pane left, live SSE trace stream right, evidence chips, critical-step freeze-frame, root-cause panel, Fix button |
| `/sessions/[id]` | Replay view: timeline synced to screen recording, DOM/screenshot panels, goal-vs-observed comparison |
| `/incidents`, `/incidents/[id]` | Incident inbox + detail: clusters, severity, fix-agent dispatch, PR preview, before/after regression replay |
| `/cloud` | Promptetheus Cloud mock: workspace, API keys, connected repo card, Slack digest, retention/PII settings |
| `/acmemeet` | The fake booking page the browser agent drives (timezone-warning behavior built in) |

**Does not:** read `.promptetheus/` from disk. All data access goes through the FastAPI HTTP API so live and seeded sessions behave identically.

## 6. Analysis Engine (`apps/console/src/server/analysis/`)

**Responsibility:** turn raw traces into failure analysis and fix bundles. Exposed as console API routes:

- `/api/analyze` — rule-based detectors first (goal mismatch from `goal_check` + DOM selected values, ignored-warning from visible warning text, false-success-claim from agent message vs goal check), then optional LLM classification. Produces `failure.json`: labels, critical step, confidence.
- `/api/generate-fix` — LLM-generated root cause, fix brief, regression test, and fix-agent task brief. Deterministic canned fallbacks for the primary demo session so the demo never blocks on an API outage.
- `/api/replay-regression` — before/after pass-rate simulation (12/12 fail → 10/12 pass + 2 user-confirmation).

**Does not:** persist anything itself — results are PUT back to FastAPI.

## 7. AcmeMeet Demo Page (`apps/console/app/acmemeet/`)

**Responsibility:** the deterministic failure stage. A booking page with day picker, time picker (where 2:00 AM sits adjacent to 2:00 PM), timezone selector, and a timezone warning that appears when AM is selected for a PM-intent flow. Stable `data-*` selectors so the scripted agent never flakes.

**Does not:** contain any Promptetheus logic. It is the customer's app in the story.

## 8. Scripted Browser Agent (`agents/browser-agent/`)

**Responsibility:** a Playwright Python script instrumented with the SDK adapter that deterministically reproduces the flagship failure: opens AcmeMeet, clicks Tuesday, selects 2:00 AM, ignores the warning, claims success, fails the goal check. Records video, emits the full event sequence from [demo-data-plan.md](../demo-data-plan.md).

**Does not:** use a real LLM during the live demo (an LLM-driven variant is a nice-to-have for the "live judge task"). Determinism beats authenticity on stage.

## 9. Seed Script (`scripts/seed.py`)

**Responsibility:** generate the 5 supporting incident clusters (~87 sessions: goal mismatch 27, ignored warning 21, false success 18, wrong element 14, forbidden action 7) with metadata, events, and pre-computed analysis, written through the ingestion API so the inbox looks production-real.

**Does not:** generate video artifacts for every session — representative sessions reference a small set of pre-recorded clips.

## Ownership Map

| Component | Workstream ([linear-execution-plan.md](../linear-execution-plan.md)) |
| --- | --- |
| SDK, adapter, transports, CLI | B — Python SDK |
| FastAPI server, schemas, seed script | C — Local Ingestion & Storage |
| Demo console, replay view, AcmeMeet, browser agent | A — Demo Spine |
| Cloud mock | D — Cloud Mock |
| Analysis engine, incidents UI, PR preview | E — Fix-Agent PR Workflow |
| Shared components, visual system | F — Visual Polish |
