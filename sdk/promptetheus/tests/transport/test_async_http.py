from __future__ import annotations

import asyncio

import pytest

httpx = pytest.importorskip("httpx")

from promptetheus import AsyncSession
from promptetheus.transport.async_http import AsyncHTTPTransport


class _CapturingApp:
    """Minimal ASGI app that records POST paths and JSON bodies."""

    def __init__(self, response_body: dict | None = None):
        self.requests = []
        self.response_body = response_body

    async def __call__(self, scope, receive, send):
        assert scope["type"] == "http"
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        import json as _json

        parsed = _json.loads(body) if body else None
        self.requests.append((scope["path"], parsed))
        response = self.response_body
        if response is None:
            response = {"accepted": len((parsed or {}).get("events", [])), "rejected": []}
        payload = _json.dumps(response).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": payload})


def test_async_http_transport_posts_trace_and_events():
    app = _CapturingApp()

    async def run():
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        transport = AsyncHTTPTransport("http://test", api_key="k", client=client)
        try:
            async with AsyncSession(
                agent="a", user_goal="g", session_id="s1", transport=transport
            ) as session:
                session.user_message("hello")
                session.tool_call("search", call_id="c1")
            await transport.aclose()
        finally:
            await client.aclose()

    asyncio.run(run())

    paths = [path for path, _ in app.requests]
    # The trace is created before its events.
    assert "/api/traces" in paths
    assert "/api/traces/s1/events" in paths
    assert paths.index("/api/traces") < paths.index("/api/traces/s1/events")

    # Events delivered for the session include the helper-emitted ones.
    event_posts = [body for path, body in app.requests if path == "/api/traces/s1/events"]
    delivered_types = {
        e["type"] for body in event_posts for e in body["events"]
    }
    assert "user_message" in delivered_types
    assert "tool_call" in delivered_types
    assert "session_end" in delivered_types


def test_async_http_transport_rebuffers_on_failure():
    transport = AsyncHTTPTransport("http://unreachable.invalid")

    async def run():
        transport.send_event(
            {
                "type": "user_message",
                "session_id": "s1",
                "timestamp": "t",
                "seq": 0,
                "idempotency_key": "s1:n:0",
                "payload": {"content": "hi"},
            }
        )
        # No server: flush fails, events are kept for retry rather than lost.
        await transport.flush()
        return list(transport._buffer)

    leftover = asyncio.run(run())
    assert any(r.get("type") == "user_message" for r in leftover)


def test_async_http_transport_rebuffers_ambiguous_2xx():
    app = _CapturingApp(response_body={"accepted": 0, "rejected": []})

    async def run():
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        transport = AsyncHTTPTransport("http://test", api_key="k", client=client)
        try:
            transport.send_event(
                {
                    "type": "user_message",
                    "session_id": "s1",
                    "timestamp": "t",
                    "seq": 1,
                    "idempotency_key": "s1:n:1",
                    "payload": {"content": "hi"},
                }
            )
            await transport.flush()
            return list(transport._buffer)
        finally:
            await client.aclose()

    leftover = asyncio.run(run())
    assert [event["seq"] for event in leftover] == [1]


def test_async_http_transport_keeps_rejected_events_retryable():
    app = _CapturingApp(
        response_body={
            "accepted": 1,
            "rejected": [
                {"index": 1, "idempotency_key": "s1:n:2", "reason": "schema_invalid"}
            ],
        }
    )

    async def run():
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        transport = AsyncHTTPTransport("http://test", api_key="k", client=client)
        try:
            for seq in (1, 2):
                transport.send_event(
                    {
                        "type": "user_message",
                        "session_id": "s1",
                        "timestamp": "t",
                        "seq": seq,
                        "idempotency_key": f"s1:n:{seq}",
                        "payload": {"content": "hi"},
                    }
                )
            await transport.flush()
            return list(transport._buffer)
        finally:
            await client.aclose()

    leftover = asyncio.run(run())
    assert [event["seq"] for event in leftover] == [2]


def test_async_http_transport_close_reports_pending_events():
    transport = AsyncHTTPTransport("http://unreachable.invalid")

    async def run():
        transport.send_event(
            {
                "type": "user_message",
                "session_id": "s1",
                "timestamp": "t",
                "seq": 0,
                "idempotency_key": "s1:n:0",
                "payload": {"content": "hi"},
            }
        )
        await transport.aclose()

    asyncio.run(run())

    assert transport.closed is True
    assert transport.closed_with_pending is True
    assert transport.pending_count == 1
