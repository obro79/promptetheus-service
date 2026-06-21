# ADR 0002: SDK contract hardening (lifecycle, delivery, idempotency, artifacts)

- **Status:** Proposed
- **Date:** 2026-06-12
- **Deciders:** SDK workstream + Contracts owner
- **Relates to:** [ADR 0001](0001-decorator-first-sdk.md) (decorator front door),
  [sdk-architecture.md](../../sdk-architecture.md) (amended to reflect this ADR),
  [technical-architecture.md](../technical-architecture.md) (event schema contract).

## Context

A design review of the pre-freeze SDK contract found the architecture sound (FastAPI write
gateway, spool-as-buffer, seq + idempotency) but identified gaps that are cheap to fix in a doc
and expensive to fix after the schema and API surface freeze:

1. Session lifecycle was fully manual (`session.end()`), so a crashing agent — the product's core
   scenario — produced a dangling session with no terminal event.
2. The terminal event was an overloaded `state_change`, with server-side status update described as
   "may also… when the server supports that path."
3. `session.screenshot(artifact_id, storage_path)` required callers to perform the artifact upload
   themselves before emitting the event.
4. Thirteen helper methods mapping 1:1 to event types froze a wide surface; new event types implied
   SDK releases.
5. Delivery semantics (blocking? batching thread? overflow?) were unspecified.
6. `idempotency_key = session_id:seq` collides when a restarted process reuses a session_id and
   restarts seq at 0.
7. `**metadata` kwargs, undefined `transport="auto"` precedence, unspecified spool durability and
   poison-event handling, redaction as a "should," and no `llm_call` event type.

## Decision

1. **Session is a context manager.** `with trace.start(...) as session:` guarantees a terminal
   event: `__exit__` emits `session_end(status="failed", error=...)` on unhandled exception,
   `session_end(status="completed")` on clean exit. Explicit `end(status)` remains for statuses the
   exit path can't infer. This composes with ADR 0001: `@pt.observe` (Rung 1) is the decorator form
   of the same guarantee.
2. **`session_end` is a first-class event type** and a guaranteed FastAPI session-status transition
   from day one. `state_change` is no longer overloaded as the terminal sentinel.
3. **The SDK owns artifact upload.** `session.screenshot(bytes_or_path)` and
   `session.replay_artifact(source, ...)` stage, upload via `POST /api/traces/{id}/artifacts`, and
   emit the event referencing the returned identity — one logical operation.
4. **Generic core + typed sugar.** `session.event(type, payload, metadata=None)` is the only
   primitive the transport knows; all typed helpers are thin wrappers. The frozen contract is the
   envelope + schema, not 13 method signatures. This also structurally enforces "adapters stay
   thin."
5. **Non-blocking delivery is an invariant.** Helpers enqueue and return; a background flusher
   batches/POSTs/backs off; the queue is bounded with spill-to-spool on overflow; `flush(timeout)`
   is public; an `atexit` hook is the last resort. The SDK never raises transport errors into user
   code.
6. **Idempotency keys include a per-process instance nonce:** `<session_id>:<nonce>:<seq>`.
   Ordering is by `(session_id, seq)`, never client `timestamp`; the server stamps `received_at`.
7. **Smaller fixes, all binding:** `session_id` optional (SDK mints a ULID); explicit
   `metadata: dict | None` parameter instead of `**metadata`; `redact=fn` runs before enqueue so
   secrets never reach the spool; `transport="auto"` precedence is explicit arg → `PROMPTETHEUS_API_URL`
   → localhost probe; spool is JSONL-per-session with a size cap and a dead-letter directory for
   permanent 4xx rejections; `llm_call` is reserved in `schema.py` now (no helper in State 0).
8. **Per-event batch semantics (added by eng review 2026-06-12):** batch event POSTs return
   `{accepted, rejected: [{index, idempotency_key, reason}]}`. Only rejected events dead-letter;
   a poison event can no longer drag valid events (including `session_end`) into the dead-letter
   directory. Whole-request auth failures still dead-letter the batch.

## Consequences

### Positive

- Crashing agents — the flagship scenario — always produce a terminal event and a flushed trace.
- The SDK cannot degrade or break the host agent; observability stays a pure add-on.
- Adapters and raw-HTTP users can emit new schema-valid event types without an SDK release.
- Artifact integration drops from "implement the upload dance" to "pass bytes."
- Restart/replay correctness: no idempotency collisions, no poison-event spool wedging.

### Negative / risks

- `session.event()` as a public primitive means users can emit any schema-valid event; schema
  validation at enqueue is now load-bearing and must match FastAPI's validation exactly.
- Background flusher + atexit + context-manager interplay needs careful tests (double-flush,
  flush-after-dead-letter, interpreter shutdown ordering).
- Reserving `llm_call` without a shipped helper risks payload-shape drift; the reservation must
  include the full TypedDict, not just the type name.

### Contract impact

- `schema.py` / `schema.ts` add `session_end` and reserved `llm_call`; envelope documents the
  3-part idempotency key. Both files change in the same commit per the contract-first rule.
- FastAPI must treat `session_end` as the canonical status transition and validate the new key
  format (validation is on stability, not internal structure).

## Alternatives considered

- **Keep manual `end()` only** — rejected: loses exactly the failed sessions the product exists to
  capture.
- **Per-event-type methods as the frozen contract (status quo)** — rejected: wide freeze surface,
  SDK release per event type; kept as sugar instead.
- **Caller-managed artifact upload (status quo)** — rejected: leaks the server artifact contract
  into every integration.
- **Synchronous delivery with timeouts** — rejected: any blocking path eventually stalls an agent
  mid-run; observed-system impact must be structurally impossible, not just bounded.
