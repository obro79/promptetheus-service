# ADR 0001: Decorator-first SDK surface

- **Status:** Proposed
- **Date:** 2026-06-12
- **Deciders:** SDK workstream
- **Supersedes:** the explicit-`Session`-first framing in [sdk-architecture.md](../../sdk-architecture.md)
  (Session is retained, demoted to the layer underneath — see Decision).
- **Amended by:** [ADR 0002](0002-sdk-contract-hardening.md) — the `Session` layer underneath is
  now a context manager over a generic `session.event()` core with typed helpers as sugar; the
  lifecycle guarantee described in Rung 1 is provided by `Session.__exit__` itself, with
  `@pt.observe` as its decorator form.

## Context

The planned SDK (see [sdk-architecture.md](../../sdk-architecture.md)) exposes an explicit,
imperative event emitter: `trace.start()` returns a `Session`, and the author calls
`session.tool_call(...)`, `session.dom_snapshot(...)`, `session.goal_check(...)`, etc. — a dozen-plus
helpers, one per event type. This is faithful to the frozen schema but it asks the agent author to
thread a `session` handle through their code and hand-place every emit. For an existing agent,
adopting Promptetheus means editing the whole call graph.

We want a surface where instrumenting an *existing* agent costs one line and no rewrites, while still
allowing full-fidelity control where it matters. Three facts about this product shape the answer:

1. **Most high-value events are not function-shaped.** `dom_snapshot`, `screenshot`,
   `replay_artifact`, and `goal_check` are *observations of state at a moment*, not call boundaries.
   No decorator can wrap "look at the page right now." So a decorator-only SDK is impossible; an
   explicit emit path must exist underneath.
2. **The flagship demo path is already adapter-driven.** The browser-agent demo gets its events from
   the Playwright adapter auto-instrumenting `Page`, not from the author decorating their own
   functions. Auto-instrumentation, not manual emits, is the real ergonomic story.
3. **Detection runs server-side.** Detectors live in FastAPI analysis modules, so `goal_check`
   (the "2:00 AM vs 2:00 PM" verdict) can be *derived downstream* from raw signal + the stated goal,
   rather than emitted by the agent. The author supplies the goal once; the SDK captures raw signal;
   the mismatch is computed later. This removes the one event auto-instrumentation could never infer.

This is the same auto-instrumentation pattern proven by Sentry, OpenTelemetry, Logfire, and
Langfuse's `@observe`.

## Decision

Make a **decorator the primary SDK surface**, backed by the existing `Session` API as the layer it
desugars to. Expose the SDK as a three-rung ladder the author climbs *down* only as far as needed.

### Rung 1 — the tag (let it watch)

```python
import promptetheus as pt

@pt.observe(user_goal="Book Tuesday 2pm Pacific, stop at confirm", project_id="proj_acmemeet")
def run_agent():
    ...
```

A decorator factory on the agent entry point. It opens a session, activates auto-instrumentation for
detected libraries (Playwright `Page`, LLM clients), and flushes on exit. Most agents never leave
this rung. Depth of capture scales with the **adapter catalog** — for a stack with no adapter yet,
the tag still records the function boundary (args in, return/exception out), and richer capture
arrives when that adapter is written.

### Rung 2 — the wrap (name a step)

```python
@pt.tool
def search_availability(day):
    ...
```

A decorator on a specific function when the auto-trace is too coarse and the author wants that call
to appear as a labeled `tool_call` (args + result/error). Backwards-compatible, still decorator-shaped.

### Rung 3 — the handle (say the thing that isn't a function)

```python
pt.current().dom_snapshot(url=page.url, visible_text=text, selected_values=values)
pt.current().state_change(name="cart_total", before=10, after=12)
```

The explicit `Session` API, reached via the ambient handle, for observation events and custom domain
events that have no call boundary to wrap. This is the current `Session` surface — unchanged, just no
longer the front door.

### What ties the rungs together

- **Ambient session via `contextvars`.** The tag sets the active session; wraps and handle calls
  *inside* attach to it automatically. The author never picks a path up front and never re-wires —
  they start at the tag and drop a wrap or handle in the *same session* only where they want more.
- **Process-global patch, context-gated emission.** Auto-instrumentation patches libraries at import
  (global monkeypatch); the decorator gates *emission* to "only while a session is active in this
  context." So the honest adoption cost is "import promptetheus + decorate the entry point," not
  literally zero code — but it is one line and no call-graph edits.

## Consequences

### Positive

- Instrumenting an existing agent is one decorator and no rewrites; removing it is deleting one line.
- Progressive disclosure: the API stays out of the way until the author asks it not to.
- The console is agnostic to which rung produced an event — every rung emits the same event types.
- `goal_check` moving server-side means the author states the goal once and never hand-writes verdicts.

### Negative / risks

- "Tag it and it just works" is bounded by the adapter catalog. We must be explicit in docs that
  unsupported stacks get function-boundary depth until an adapter exists, to avoid overpromising.
- Global monkeypatching of third-party libraries is inherently fragile across library versions and
  must be defensively written and version-tested.
- Ambient `contextvars` state needs care across threads, async tasks, and subprocess boundaries.

### Guardrails (binding)

- **Off = no-op, never crash.** `@pt.tool` or `pt.current()` with no active session silently does
  nothing. This is what makes "tag it, ship it, remove it" actually free and keeps the backwards-
  compatibility promise even when Promptetheus is not initialized.
- **Every rung desugars to the frozen Session events.** The tag and the wrap invent no new event
  types and no hidden server behavior — they emit through `Session` (per ADR 0002, ultimately
  through the single `session.event()` primitive, which validates against the frozen schema).
  This keeps the [technical-architecture.md](../technical-architecture.md) contract intact and the
  "adapters stay thin over Session" invariant honored. A schema change still updates both
  `schema.py` and `schema.ts` in the same commit.

## Alternatives considered

- **Explicit `Session` as the front door (status quo).** Faithful and flexible, but adoption means
  editing the whole call graph. Kept as Rung 3, not as the primary surface.
- **Decorators only.** Impossible: observation events (`dom_snapshot`, `screenshot`, `goal_check`)
  have no function boundary to wrap. An explicit emit path must exist.
- **Two paths split on verbosity (terse vs explicit).** Rejected — the real split is on *intent*
  ("let it watch" vs "tell it exactly"), which is what the rung ladder encodes.

## Build sequencing

Rung 3 (`Session`) and the Playwright adapter are already must-build for State 0 and are unchanged.
Rung 1 (`@pt.observe` + auto-instrumentation activation) and Rung 2 (`@pt.tool`/`@pt.step`) layer on
top and slot into the "should build after the spine is stable" tier, alongside the LangChain handler.
Adoption cost and capture depth are docs-visible promises — track them as the adapter catalog grows.
