# ADR 0003: AgentRuntime client for service-backed runtime coordination

- **Status:** Proposed
- **Date:** 2026-06-20
- **Deciders:** SDK workstream + service runtime owner
- **Relates to:** [ADR 0002](0002-sdk-contract-hardening.md),
  [sdk-architecture.md](../../sdk-architecture.md), and the Promptetheus service FastAPI contract.

## Context

Promptetheus needs to help agents while they are running, not only analyze them after the fact.
Redis is a good fit for short-lived coordination data: recent failed tool calls, working memory,
live heartbeat state, and hints that steer an agent away from repeated bad actions. That does not
change the storage boundary: Supabase remains canonical for trace events, incidents, artifacts,
audit logs, fix-agent output, and regression results.

The SDK should expose this runtime capability without importing Redis, requiring a Redis client, or
writing around the FastAPI gateway. The current service does not yet expose runtime endpoints, so
SDK support must be forward-compatible and safe when those endpoints are absent.

## Decision

Add a public `AgentRuntime` SDK client that calls planned FastAPI runtime endpoints:

- `POST /api/traces/{id}/runtime/memory`
- `GET /api/traces/{id}/runtime/memory`
- `POST /api/traces/{id}/runtime/tool-call`
- `POST /api/traces/{id}/runtime/heartbeat`
- `GET /api/traces/{id}/runtime/hint`

The SDK resolves endpoint and API key with the same precedence as trace delivery: explicit args,
environment, then config file. It uses the Python standard library HTTP stack to preserve the SDK's
zero required dependencies.

All runtime calls are best-effort. Missing endpoints, offline service, malformed responses, and
serialization issues are logged at debug level and return safe fallbacks. The runtime client also
redacts payloads with the existing default redactor before sending.

## Consequences

Positive:

- Agent authors get a stable SDK surface for live memory, dedupe, heartbeats, and hints.
- The SDK remains independent of Redis and keeps FastAPI as the only remote write boundary.
- Early adopters can ship the SDK before the service-side Redis runtime is deployed.

Risks:

- Until the service implements the runtime endpoints, the methods are no-ops except for debug logs.
- Runtime payloads can contain sensitive tool arguments or stderr, so redaction is mandatory even
  though Redis state is short-lived.
- The service contract must preserve best-effort semantics; runtime outages must not break trace
  delivery or host agents.

## Follow-up

Implement the matching service runtime layer behind FastAPI with Redis as an optional backend and
in-memory fallback for tests/local dev. Redis state should expire by default and any durable outcome
must still be written through the existing Supabase-backed service paths.
