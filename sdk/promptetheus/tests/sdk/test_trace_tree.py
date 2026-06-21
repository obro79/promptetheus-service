from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.trace_tree import (  # noqa: E402
    SpanNode,
    build_trace_forest,
    build_trace_tree,
    render_tree,
)


def _ev(seq, etype, payload=None, *, span_id=None, parent_id=None):
    event = {
        "type": etype,
        "session_id": "s1",
        "timestamp": "2026-06-15T00:00:00Z",
        "seq": seq,
        "idempotency_key": f"k{seq}",
        "payload": payload or {},
    }
    if span_id is not None:
        event["span_id"] = span_id
        event["parent_id"] = parent_id
    return event


def _span_start(seq, span_id, name, parent_id=None):
    return _ev(
        seq,
        "state_change",
        {"name": "span_start", "span_name": name},
        span_id=span_id,
        parent_id=parent_id,
    )


def _span_end(seq, span_id, name, parent_id=None, duration_ms=None):
    payload = {"name": "span_end", "span_name": name}
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    return _ev(seq, "state_change", payload, span_id=span_id, parent_id=parent_id)


def _names(nodes):
    return [n.name for n in nodes]


def test_build_tree_alias_matches_forest():
    events = [_span_start(0, "a", "outer"), _span_end(1, "a", "outer")]
    a = build_trace_tree(events)
    b = build_trace_forest(events)
    assert _names(a) == _names(b) == ["outer"]


def test_nesting_parent_chain():
    events = [
        _span_start(0, "a", "outer"),
        _span_start(1, "b", "inner", parent_id="a"),
        _ev(2, "agent_message", {"content": "deep"}, span_id="b", parent_id="a"),
        _span_end(3, "b", "inner", parent_id="a"),
        _span_end(4, "a", "outer"),
    ]
    roots = build_trace_forest(events)
    assert len(roots) == 1
    outer = roots[0]
    assert outer.span_id == "a"
    assert outer.parent_id is None
    assert len(outer.children) == 1
    inner = outer.children[0]
    assert inner.span_id == "b"
    assert inner.parent_id == "a"
    contents = [e["payload"].get("content") for e in inner.events]
    assert "deep" in contents


def test_siblings_preserve_order():
    events = [
        _span_start(0, "first", "first"),
        _span_end(1, "first", "first"),
        _span_start(2, "second", "second"),
        _span_end(3, "second", "second"),
        _span_start(4, "third", "third"),
        _span_end(5, "third", "third"),
    ]
    roots = build_trace_forest(events)
    assert _names(roots) == ["first", "second", "third"]


def test_missing_parent_attaches_to_root_level():
    # parent "ghost" was never opened; the span must still surface, not vanish.
    events = [
        _span_start(0, "child", "orphan", parent_id="ghost"),
        _ev(1, "agent_message", {"content": "hi"}, span_id="child", parent_id="ghost"),
        _span_end(2, "child", "orphan", parent_id="ghost"),
    ]
    roots = build_trace_forest(events)
    assert len(roots) == 1
    assert roots[0].span_id == "child"
    assert roots[0].name == "orphan"


def test_unclosed_span_still_built():
    events = [
        _span_start(0, "a", "outer"),
        _ev(1, "tool_call", {"tool_name": "search"}, span_id="a", parent_id=None),
        # no span_end emitted
    ]
    roots = build_trace_forest(events)
    assert len(roots) == 1
    node = roots[0]
    assert node.span_id == "a"
    assert node.start_seq == 0
    assert node.end_seq is None
    tool_calls = [e for e in node.events if e["type"] == "tool_call"]
    assert len(tool_calls) == 1


def test_self_parent_cycle_surfaces_as_root():
    # A span that names itself as parent must not vanish.
    events = [_span_start(0, "a", "loop", parent_id="a")]
    roots = build_trace_forest(events)
    span_ids = {r.span_id for r in roots}
    assert "a" in span_ids


def test_two_cycle_keeps_all_spans():
    # a.parent=b and b.parent=a form a 2-cycle; both spans must still appear.
    events = [
        _span_start(0, "a", "first", parent_id="b"),
        _span_start(1, "b", "second", parent_id="a"),
    ]
    roots = build_trace_forest(events)

    def collect(nodes):
        seen = set()
        for n in nodes:
            if n.span_id is not None:
                seen.add(n.span_id)
            seen |= collect(n.children)
        return seen

    reachable = collect(roots)
    assert reachable == {"a", "b"}


def test_three_cycle_keeps_all_spans():
    # a -> b -> c -> a; every span must remain reachable from some root.
    events = [
        _span_start(0, "a", "first", parent_id="c"),
        _span_start(1, "b", "second", parent_id="a"),
        _span_start(2, "c", "third", parent_id="b"),
    ]
    roots = build_trace_forest(events)

    def collect(nodes):
        seen = set()
        for n in nodes:
            if n.span_id is not None:
                seen.add(n.span_id)
            seen |= collect(n.children)
        return seen

    reachable = collect(roots)
    assert reachable == {"a", "b", "c"}


def test_duration_ms_passthrough():
    events = [
        _span_start(0, "a", "outer"),
        _span_end(1, "a", "outer", duration_ms=42),
    ]
    roots = build_trace_forest(events)
    assert roots[0].duration_ms == 42.0


def test_flat_events_go_under_synthetic_root():
    events = [
        _ev(0, "user_message", {"content": "hello"}),
        _ev(1, "agent_message", {"content": "hi"}),
    ]
    roots = build_trace_forest(events)
    assert len(roots) == 1
    root = roots[0]
    assert root.is_synthetic_root
    assert root.span_id is None
    assert len(root.events) == 2


def test_mixed_flat_and_spanned():
    events = [
        _ev(0, "user_message", {"content": "go"}),
        _span_start(1, "a", "work"),
        _ev(2, "agent_message", {"content": "in-span"}, span_id="a", parent_id=None),
        _span_end(3, "a", "work"),
    ]
    roots = build_trace_forest(events)
    span_ids = {r.span_id for r in roots}
    assert "a" in span_ids
    assert None in span_ids


def test_out_of_order_events_tolerated():
    # span_end arrives before span_start in the raw list; seq still orders things.
    events = [
        _span_end(3, "a", "outer", duration_ms=10),
        _ev(2, "agent_message", {"content": "mid"}, span_id="a", parent_id=None),
        _span_start(1, "a", "outer"),
    ]
    roots = build_trace_forest(events)
    assert len(roots) == 1
    node = roots[0]
    assert node.name == "outer"
    assert node.start_seq == 1
    assert node.end_seq == 3
    assert node.duration_ms == 10.0
    # events presented in seq order
    seqs = [e["seq"] for e in node.events]
    assert seqs == sorted(seqs)


def test_malformed_input_never_raises():
    garbage = [None, 42, "not a dict", {"no": "envelope"}, {"type": "x"}]
    roots = build_trace_forest(garbage)
    # Non-mappings are dropped; the lone mapping(s) land under synthetic root.
    assert isinstance(roots, list)
    text = render_tree(roots)
    assert isinstance(text, str)


def test_empty_input():
    assert build_trace_forest([]) == []
    assert render_tree([]) == ""


def test_render_tree_indents_nested_spans():
    events = [
        _span_start(0, "a", "outer"),
        _ev(1, "agent_message", {"content": "x"}, span_id="a", parent_id=None),
        _span_start(2, "b", "inner", parent_id="a"),
        _ev(3, "agent_message", {"content": "y"}, span_id="b", parent_id="a"),
        _span_end(4, "b", "inner", parent_id="a"),
        _span_end(5, "a", "outer"),
    ]
    roots = build_trace_forest(events)
    text = render_tree(roots)
    lines = text.splitlines()
    # outer span header at depth 0
    assert lines[0].startswith("outer")
    # inner span header indented under outer (two spaces per level)
    inner_line = [ln for ln in lines if ln.strip().startswith("inner")][0]
    assert inner_line.startswith("  inner")


def test_span_node_is_frozen():
    node = SpanNode(span_id="a")
    try:
        node.span_id = "b"  # type: ignore[misc]
    except Exception as exc:  # frozen dataclass raises FrozenInstanceError
        assert "cannot assign" in str(exc).lower() or exc.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("SpanNode should be immutable")
