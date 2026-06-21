from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.propagation import (  # noqa: E402
    TraceContext,
    extract,
    inject,
    new_trace_context,
    session_kwargs_from_context,
)


def test_new_trace_context_is_valid():
    ctx = new_trace_context()
    assert len(ctx.trace_id) == 32 and all(c in "0123456789abcdef" for c in ctx.trace_id)
    assert len(ctx.parent_id) == 16
    assert ctx.trace_id != "0" * 32 and ctx.parent_id != "0" * 16


def test_inject_extract_round_trip():
    ctx = new_trace_context()
    headers = inject(ctx, {"content-type": "application/json"})
    assert headers["content-type"] == "application/json"  # preserves other headers
    assert headers["traceparent"].startswith("00-")
    got = extract(headers)
    assert got is not None
    assert got.trace_id == ctx.trace_id
    assert got.parent_id == ctx.parent_id


def test_extract_case_insensitive_header():
    ctx = new_trace_context()
    got = extract({"TraceParent": ctx.to_traceparent()})
    assert got is not None and got.trace_id == ctx.trace_id


def test_extract_tolerates_missing_and_malformed():
    assert extract(None) is None
    assert extract({}) is None
    assert extract({"traceparent": "garbage"}) is None
    assert extract({"traceparent": "00-xyz-abc-01"}) is None
    # all-zero ids are invalid
    assert extract({"traceparent": f"00-{'0'*32}-{'0'*16}-01"}) is None


def test_traceparent_format():
    ctx = TraceContext(trace_id="a" * 32, parent_id="b" * 16)
    assert ctx.to_traceparent() == f"00-{'a'*32}-{'b'*16}-01"


def test_session_kwargs_from_context():
    ctx = new_trace_context()
    kwargs = session_kwargs_from_context(ctx)
    assert kwargs["metadata"]["trace_id"] == ctx.trace_id
    assert kwargs["metadata"]["parent_span_id"] == ctx.parent_id
