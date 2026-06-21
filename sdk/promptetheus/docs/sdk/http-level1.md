# Level 1 — Raw HTTP integration (P10.4–P10.7)

Any stack can POST schema-conformant JSON to the locked 14-endpoint API. No Python SDK required.

## Base URL

- Local: `http://127.0.0.1:4318`
- Hosted: Railway URL (P4.10 — **State-0 defer**)

## Auth

```http
Authorization: Bearer pt_dev_key
```

Dev defaults: see [auth-onboarding.md](../architecture/auth-onboarding.md).

## Create a trace

```bash
curl -sS -X POST http://127.0.0.1:4318/api/traces \
  -H "Authorization: Bearer pt_dev_key" \
  -H "Content-Type: application/json" \
  -d '{"user_goal":"Book a room for Tuesday","agent":"demo-agent","id":"trace_curl_1"}'
```

## Append events (batch)

```bash
curl -sS -X POST http://127.0.0.1:4318/api/traces/trace_curl_1/events \
  -H "Authorization: Bearer pt_dev_key" \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "type": "user_message",
      "session_id": "trace_curl_1",
      "timestamp": "2026-01-01T00:00:00Z",
      "seq": 0,
      "idempotency_key": "trace_curl_1:dev:0",
      "payload": {"content": "Book Tuesday"}
    }]
  }'
```

## Upload artifact metadata

```bash
curl -sS -X POST http://127.0.0.1:4318/api/traces/trace_curl_1/artifacts \
  -H "Authorization: Bearer pt_dev_key" \
  -H "Content-Type: application/json" \
  -d '{
    "content_type": "image/png",
    "size_bytes": 512,
    "filename": "shot.png",
    "artifact_type": "screenshot"
  }'
```

## Analyze (console JWT)

```bash
curl -sS -X POST http://127.0.0.1:4318/api/traces/trace_curl_1/analyze \
  -H "Authorization: Bearer pt_console_token"
```

## Single-event POST

Send one event object (not wrapped in `events`) for minimal clients. Malformed envelope → **422**.

## See also

- [technical-architecture.md](../architecture/technical-architecture.md#api-contract-the-locked-endpoint-table)
- Python SDK quickstart in [packages/promptetheus/README.md](../../packages/promptetheus/README.md)
