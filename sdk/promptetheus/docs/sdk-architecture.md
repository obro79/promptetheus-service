# SDK Architecture

This document defines the developer-facing SDK contract: public API, transports, delivery and
retry behavior, and adapters. The current package is still a published `0.0.1` stub; this is the
target SDK surface for the real MVP.

Related decisions:

- [ADR 0001](architecture/adr/0001-decorator-first-sdk.md) — `@pt.observe` decorator as the
  eventual front door; the `Session` API below is the layer every rung desugars to.
- [ADR 0002](architecture/adr/0002-sdk-contract-hardening.md) — lifecycle, delivery, idempotency,
  and artifact-upload decisions reflected in this doc.

Invariants:

- `packages/promptetheus/promptetheus/schema.py` is the event-schema source of truth.
- `apps/console/src/lib/schema.ts` mirrors the Python schema and must stay parity-tested.
- The SDK talks to FastAPI using the same authenticated API as raw HTTP integrations.
- The SDK never writes canonical product storage directly. It only spools failed deliveries locally
  and replays them through FastAPI.
- **The SDK must never crash or block the host agent.** Emission is non-blocking; all transport
  errors are logged and swallowed, never raised into user code.

## Package

```bash
pip install promptetheus
promptetheus dev
```

`promptetheus dev` starts or points to the local development environment. State 0's canonical demo
can run hosted on Railway/Vercel/Supabase or locally against configured Supabase credentials.

## Public API

The session is a context manager. `__exit__` guarantees a terminal event even when the agent
crashes — which is exactly when a failure-observability SDK must not lose the session:

```python
from promptetheus import trace

with trace.start(
    agent="browser-agent",
    user_goal="Book Tuesday at 2pm Pacific, but stop at confirmation",
    project_id="proj_acmemeet",
    api_key=os.environ["PROMPTETHEUS_API_KEY"],
) as session:
    session.user_message(content=user_goal)
    session.browser_action(action="click", target="button[data-day='tuesday']", url=page.url)
    session.dom_snapshot(url=page.url, visible_text=visible_text, selected_values=selected_values)
    session.screenshot(page.screenshot())                    # SDK owns upload + event emission
    session.goal_check(passed=False, mismatches=["Selected 2:00 AM instead of 2:00 PM"])
    session.end(status="failed")
# on unhandled exception: __exit__ emits session_end(status="failed", error=...) and flushes
# on clean exit without explicit end(): __exit__ emits session_end(status="completed") and flushes
```

- `session_id` is optional; the SDK generates a ULID when omitted. Callers may pass their own for
  correlation with external systems.
- Explicit `session.end(status)` remains available for statuses the exit path can't infer
  (e.g. `"aborted"`); `__exit__` is the safety net, not the only path.

### Layered surface: generic core + typed sugar

The transport knows exactly one emission primitive:

- `session.event(type, payload, metadata=None)` — validates against `schema.py`, stamps the
  envelope, enqueues.

Every typed helper below is a thin wrapper over `session.event()` — nicer signatures and
validation, nothing more. This keeps the frozen contract small (envelope + schema, not 13 method
signatures), lets adapters and early users emit schema-valid event types the SDK has no helper for
yet, and structurally enforces "adapters stay thin": an adapter cannot do anything `session.event()`
cannot.

Must-build typed helpers:

- `trace.start(agent, user_goal, session_id=None, project_id=None, api_key=None, transport="auto", redact=None, metadata=None, ...)`
- `session.user_message(content, metadata=None)`
- `session.agent_message(content, metadata=None)`
- `session.tool_call(tool_name, arguments, call_id=None, metadata=None)`
- `session.tool_result(call_id, result=None, error=None, metadata=None)`
- `session.retrieval(query, documents, metadata=None)`
- `session.browser_action(action, target, url=None, metadata=None)`
- `session.dom_snapshot(url, visible_text, selected_values=None, warnings=None, metadata=None)`
- `session.screenshot(source, metadata=None)` — `source` is bytes or a path; see Artifacts.
- `session.replay_artifact(source, artifact_type, event_time_map, metadata=None)`
- `session.llm_call(model, input_tokens=None, output_tokens=None, latency_ms=None, messages_ref=None, prompt_ref=None, metadata=None)`
- `session.goal_check(passed, mismatches=None, metadata=None)`
- `session.state_change(name, before=None, after=None, metadata=None)`
- `session.score(name, value, comment=None, source=None, metadata=None)`
- `session.error(error, error_type=None, handled=None, metadata=None)`
- `session.metric(name, value, unit=None, metadata=None)`
- `session.end(status, error=None)`
- `session.flush(timeout=None)` — block until the queue and spool drain or `timeout` elapses.

Helpers take an explicit `metadata: dict | None` parameter, not `**metadata` kwargs — open kwargs
collide with future schema fields and make signatures unevolvable.

`session.end(status)` emits a dedicated terminal `session_end` event (not an overloaded
`state_change`) and flushes pending events. FastAPI treats `session_end` as the canonical
session-status transition; detection and the console key off it directly.

`llm_call` records model, prompt/messages references, token counts, and latency. It intentionally
stores references instead of raw prompt/message content so adapters can keep large or sensitive
payloads out of the event stream.

`score`, `error`, and `metric` are first-class SDK helper event types. They provide lightweight
run feedback, failure signals, and numeric measurements without turning Promptetheus into a generic
analytics or eval platform.

## Agent Runtime Coordination

`AgentRuntime` is the SDK surface for short-lived, service-backed coordination that can improve an
agent while it is running. It is not canonical storage and it does not import or talk to Redis
directly. The SDK calls FastAPI runtime endpoints; the service owns the Redis or in-memory runtime
backend.

```python
from promptetheus import AgentRuntime

runtime = AgentRuntime(session.session_id)
runtime.remember("hypothesis", {"summary": "auth header may be missing"})
result = runtime.record_tool_call(
    "pytest",
    command="pytest tests/server",
    status="failed",
    error="401 from trace create",
)
if result["seen_recently"]:
    hint = result.get("hint") or runtime.next_hint()
```

The first runtime slice supports:

- `remember(kind, value, metadata=None)` for transient working memory.
- `get_memory(limit=20)` for recent runtime context.
- `record_tool_call(...)` for repeated-action detection and dedupe hints.
- `heartbeat(...)` for live phase/current-file/current-hypothesis state.
- `next_hint()` for service-generated guidance.

Runtime calls are best-effort by contract. If the service is offline, the planned endpoints are not
available yet, or a response is malformed, the SDK logs at debug level and returns safe fallbacks.
Runtime payloads are redacted with the built-in redactor before they leave the process because tool
arguments and stderr often contain secrets.

## Event Envelope

Every emission carries the base envelope:

```python
{
    "type": "browser_action",
    "session_id": "sess_01J9XQ...",
    "timestamp": "2026-06-12T12:34:56.000Z",   # client clock; informational only
    "seq": 12,
    "idempotency_key": "sess_01J9XQ...:b3f2:12",
    "payload": {...}
}
```

Rules:

- `seq` is monotonic per session, assigned under a lock before enqueue (thread-safe by contract).
- **Ordering is by `(session_id, seq)`, never by `timestamp`.** Client clocks are untrusted; the
  server stamps its own `received_at` on ingest.
- `idempotency_key` is `<session_id>:<instance_nonce>:<seq>`. The per-process instance nonce is
  generated at `trace.start()`; it prevents key collisions when a crashed process restarts, reuses
  a caller-supplied `session_id`, and restarts `seq` at 0.
- `idempotency_key` is stable across retries and spool replay.
- Helper names map one-to-one to event types; `end()`/`__exit__` emit `session_end`.
- Replay artifacts reference `artifact_id`/`storage_path`; FastAPI derives signed URLs.

## Delivery Model

Emission must never slow down or break the agent being observed:

- Helper calls validate, stamp the envelope, enqueue, and return immediately (non-blocking).
- A background flusher thread batches the queue and POSTs to FastAPI with exponential backoff
  (capped), preserving idempotency keys.
- The in-memory queue is bounded. On overflow the SDK spills to the spool — it never blocks the
  caller and never silently drops without logging.
- `session.end()` / `__exit__` flush in-memory batches and attempt one immediate spool replay; an
  `atexit` hook performs a last-resort bounded flush for sessions never explicitly ended.
- Transport exceptions are logged via the `promptetheus` logger and swallowed. No SDK call raises
  into user code (programming errors like schema-invalid payloads fail fast in dev mode only).

## Transport Modes

The event API does not change when transports change.

`transport="auto"` uses HTTP only when a project API key is configured. Endpoint
resolution then follows this precedence:

1. Explicit `endpoint=` argument.
2. `PROMPTETHEUS_API_URL` environment variable.
3. `~/.promptetheus/config.toml`.
4. Hosted Promptetheus API default.

When no API key is configured, auto mode writes to the local spool instead of
making unauthenticated hosted requests.

### Local dev

```python
session = trace.start(
    agent="browser-agent",
    user_goal=user_goal,
    transport="auto",
    endpoint="http://localhost:4318",
    api_key=os.environ["PROMPTETHEUS_API_KEY"],
)
```

### Hosted

```python
session = trace.start(
    agent="browser-agent",
    user_goal=user_goal,
    transport="auto",
    api_key=os.environ["PROMPTETHEUS_API_KEY"],
    project_id="proj_acmemeet",
)
```

## Spool

Failed deliveries are written to a local spool (default `.promptetheus/spool/`):

- Format: one JSONL file per session, append-only, events already enveloped and redacted.
- The spool is not canonical storage. It is replayed through FastAPI on retry or explicit import.
- The spool has a configurable size cap; on hitting it, oldest fully-delivered files are pruned
  first, and further overflow is logged loudly.
- **Dead-letter rule:** transient failures (network, 5xx, 429) retry with backoff indefinitely up
  to the cap. The server uses per-event accept/reject semantics on batch POSTs
  (`{accepted, rejected: [{index, idempotency_key, reason}]}`), so only individually rejected
  events move to dead-letter storage; accepted events in the same batch are never retried or
  lost. Whole-request permanent rejections (revoked key, 401/403) dead-letter the batch.

  **State-0 note:** the durable transport writes `{session_id}.deadletter.jsonl` at the spool
  root today. The target layout `spool/dead-letter/` is deferred until hosted spool migration.
- Replay preserves `(session_id, seq)` order and idempotency keys.

## Artifacts

The SDK owns the upload dance; callers hand it bytes or a path:

```python
session.screenshot(page.screenshot())                      # bytes
session.replay_artifact("trace.webm", artifact_type="screen_recording", event_time_map=etm)
```

- The SDK stages the file, uploads via `POST /api/traces/{id}/artifacts`, then emits the
  `screenshot`/`replay_artifact` event referencing the returned `artifact_id`/`storage_path` —
  upload + event as one logical operation, with retry handled in the transport.
- Local staged files exist only until FastAPI accepts the upload (or they dead-letter with the
  same rules as events).
- Event payloads never contain public artifact URLs; FastAPI derives signed URLs server-side.

## Authentication & Redaction

- SDK ingestion uses `Authorization: Bearer <project_api_key>`.
- API keys are project-scoped and resolve to `workspace_id`/`project_id` server-side.
- The SDK must never receive Supabase service-role keys or GitHub installation tokens.
- Redaction is a first-class parameter: `trace.start(..., redact=fn)`. The hook runs **before
  enqueue**, so redacted values never reach the in-memory queue, the spool file, or the wire —
  a security property, not a convenience.

## Playwright Adapter

The Playwright adapter wraps a `Page` and stays thin over `Session`.

Responsibilities:

- Auto-emit `browser_action` for clicks, fills, navigation, and submits.
- Capture DOM snapshots with selected values and visible warnings.
- Hand screenshots and replay `.webm` files to the `Session` artifact helpers (the SDK uploads).
- Emit `screenshot` and `replay_artifact` events with artifact identity and `event_time_map`.
- Preserve page behavior; no agent decision logic.

Non-goals:

- No adapter-only event types (structurally enforced: adapters emit through `session.event()` and
  the typed helpers only).
- No server-side behavior hidden in the adapter.
- No direct writes to Supabase or `.promptetheus/` canonical files.

## Interop Adapters

Must build for State 0:

- Playwright Python adapter.
- Generic raw HTTP ingestion docs and examples.

Should build after the spine is stable:

- `@pt.observe` / `@pt.tool` decorator surface ([ADR 0001](architecture/adr/0001-decorator-first-sdk.md)).
- LangChain/LangGraph callback handler (first consumer of the reserved `llm_call` event).
- LangSmith-compatible run-tree ingestion adapter.

Later:

- OpenAI Agents SDK.
- TypeScript SDK for Vercel AI SDK and browser-native apps.
- CrewAI and custom framework helpers.

## `promptetheus dev`

`promptetheus dev` should:

- Start FastAPI locally or point it at the hosted Railway API.
- Start or point to the Next.js console.
- Validate Supabase/FastAPI/Vercel env configuration.
- Print API and console URLs.
- Offer `--seed` to run `scripts/seed.py` through FastAPI.
- Surface the spool location, dead-letter contents, and replay status.
- Shut down child processes cleanly on Ctrl-C.

It should not claim the SDK/server are production-ready while the package is still the `0.0.1` stub.
