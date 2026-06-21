"""Reconstruct a run tree from a flat event stream.

A Promptetheus session is a flat, ordered list of events. Each event carries an
envelope with seq, type, timestamp, payload and (optionally) span_id and
parent_id. Spans are opened and closed by state_change events whose payload name
is span_start and span_end; those marker events and every event emitted between
them carry the span's span_id, and the span's enclosing span is named by
parent_id.

This module turns that flat list back into a forest of SpanNode objects suitable
for inspection or printing. It is deliberately forgiving: events with no span
attach to a synthetic root, out-of-order and unclosed spans are tolerated, and
malformed input never raises. build_trace_tree returns the root spans in the
order they first appear; render_tree prints an indented text tree in the same
style as the CLI replay command.

Symbols are referred to by bare name throughout: SpanNode, build_trace_tree,
render_tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

__all__ = ["SpanNode", "build_trace_tree", "build_trace_forest", "render_tree"]


@dataclass(frozen=True)
class SpanNode:
    """An immutable node in a reconstructed run tree.

    span_id is the id of this span, or None for the synthetic root that holds
    span-less events. parent_id is the enclosing span's id (None at the top
    level). name is a best-effort label taken from the span_start payload
    (span_name, falling back to name). start_seq and end_seq are the seq numbers
    of the span_start and span_end marker events when known, else None.
    duration_ms is taken from the span_end payload when present. children holds
    nested SpanNode objects in first-seen order. events holds the raw event
    dicts that fell directly under this span, including its own span_start and
    span_end markers, ordered by seq.
    """

    span_id: str | None
    parent_id: str | None = None
    name: str | None = None
    start_seq: int | None = None
    end_seq: int | None = None
    duration_ms: float | None = None
    children: list["SpanNode"] = field(default_factory=list)
    events: list[Mapping[str, Any]] = field(default_factory=list)

    @property
    def is_synthetic_root(self) -> bool:
        """True for the synthetic root that collects events with no span."""
        return self.span_id is None


# Mutable scratch node used while reconstructing; converted to a frozen SpanNode
# at the end so the public type stays immutable.
class _Builder:
    __slots__ = (
        "span_id",
        "parent_id",
        "name",
        "start_seq",
        "end_seq",
        "duration_ms",
        "children",
        "events_with_order",
        "_first_seq",
    )

    def __init__(self, span_id: str | None) -> None:
        self.span_id: str | None = span_id
        self.parent_id: str | None = None
        self.name: str | None = None
        self.start_seq: int | None = None
        self.end_seq: int | None = None
        self.duration_ms: float | None = None
        self.children: list["_Builder"] = []
        # Events are stored alongside a sort key (seq, arrival index) so the
        # frozen node can present them in a stable, seq-ordered sequence.
        self.events_with_order: list[tuple[tuple[float, int], Mapping[str, Any]]] = []
        # Order key: the seq (or arrival index) at which this span was first seen,
        # used to preserve sibling order deterministically.
        self._first_seq: float | None = None

    def freeze(self) -> SpanNode:
        ordered_events = [
            ev for _, ev in sorted(self.events_with_order, key=lambda item: item[0])
        ]
        return SpanNode(
            span_id=self.span_id,
            parent_id=self.parent_id,
            name=self.name,
            start_seq=self.start_seq,
            end_seq=self.end_seq,
            duration_ms=self.duration_ms,
            children=[child.freeze() for child in self.children],
            events=ordered_events,
        )


def _as_mapping(event: Any) -> Mapping[str, Any] | None:
    return event if isinstance(event, Mapping) else None


def _seq_of(event: Mapping[str, Any], fallback: int) -> int:
    raw = event.get("seq")
    if isinstance(raw, bool):
        return fallback
    if isinstance(raw, int):
        return raw
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _span_marker(event: Mapping[str, Any]) -> str | None:
    """Return span_start or span_end if this event is a span marker, else None."""
    if event.get("type") != "state_change":
        return None
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return None
    name = payload.get("name")
    if name in ("span_start", "span_end"):
        return name
    return None


def _span_name(event: Mapping[str, Any]) -> str | None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return None
    label = payload.get("span_name")
    if isinstance(label, str) and label:
        return label
    name = payload.get("name")
    return name if isinstance(name, str) and name else None


def _duration_ms(event: Mapping[str, Any]) -> float | None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("duration_ms")
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def build_trace_forest(events: Iterable[Any]) -> list[SpanNode]:
    """Reconstruct the forest of root spans from a flat event stream.

    Returns the top-level SpanNode objects in first-seen order. Events that carry
    no span_id are collected under a single synthetic root (span_id None) which is
    placed in the forest only if such events exist. Unclosed spans, out-of-order
    events, missing parents, and malformed entries are all tolerated; this never
    raises.
    """

    builders: dict[str | None, _Builder] = {}
    order_counter = 0

    def get_builder(span_id: str | None) -> _Builder:
        builder = builders.get(span_id)
        if builder is None:
            builder = _Builder(span_id)
            builders[span_id] = builder
        return builder

    for index, raw_event in enumerate(events):
        event = _as_mapping(raw_event)
        if event is None:
            continue
        order_counter += 1
        seq = _seq_of(event, fallback=index)

        raw_span = event.get("span_id")
        span_id: str | None = (
            raw_span if isinstance(raw_span, str) and raw_span else None
        )

        raw_parent = event.get("parent_id")
        parent_id: str | None = (
            raw_parent if isinstance(raw_parent, str) and raw_parent else None
        )

        builder = get_builder(span_id)
        if builder._first_seq is None:
            builder._first_seq = float(seq)
        # An event names the span's parent; remember it (the marker is the most
        # authoritative source but any event in the span agrees).
        if span_id is not None and parent_id is not None:
            builder.parent_id = parent_id

        marker = _span_marker(event)
        if marker == "span_start" and span_id is not None:
            builder.start_seq = seq
            label = _span_name(event)
            if label is not None:
                builder.name = label
            if parent_id is not None:
                builder.parent_id = parent_id
        elif marker == "span_end" and span_id is not None:
            builder.end_seq = seq
            if builder.name is None:
                label = _span_name(event)
                if label is not None:
                    builder.name = label
            dur = _duration_ms(event)
            if dur is not None:
                builder.duration_ms = dur

        builder.events_with_order.append(((float(seq), order_counter), event))

    # Break parent cycles before linking. A self-parent or a longer cycle
    # (a -> b -> a) would otherwise leave every span in the cycle pointing at a
    # parent that exists in builders, so none of them would ever be appended to
    # roots and they would vanish. Walk each span's parent chain; if it loops
    # back on itself, sever the back-edge by clearing parent_id on the span that
    # closes the loop so it surfaces as a root and nothing is lost.
    for span_id, builder in builders.items():
        if span_id is None:
            continue
        visited: set[str | None] = {span_id}
        current = builder
        while True:
            parent_id = current.parent_id
            if parent_id is None or parent_id not in builders:
                break
            if parent_id in visited:
                # parent_id closes a cycle reachable from this span. Clear the
                # parent on the span that points back into the visited set so
                # the loop is opened and the span becomes a root.
                builders[parent_id].parent_id = None
                break
            visited.add(parent_id)
            current = builders[parent_id]

    # Link children to parents. A span whose parent is unknown (missing or never
    # opened) attaches to the synthetic root so nothing is lost.
    roots: list[_Builder] = []
    synthetic_needed = None in builders

    for span_id, builder in builders.items():
        if span_id is None:
            continue
        parent_id = builder.parent_id
        if parent_id is not None and parent_id in builders:
            builders[parent_id].children.append(builder)
        else:
            roots.append(builder)

    if synthetic_needed:
        roots.append(builders[None])

    def order_key(b: _Builder) -> tuple[float, str]:
        first = b._first_seq if b._first_seq is not None else float("inf")
        # Synthetic root sorts by its events; tie-break on a stable string.
        return (first, "" if b.span_id is None else b.span_id)

    roots.sort(key=order_key)
    for builder in builders.values():
        builder.children.sort(key=order_key)

    return [builder.freeze() for builder in roots]


# build_trace_tree is the documented entry point; build_trace_forest is an alias
# kept for callers that prefer the more explicit "forest" name.
def build_trace_tree(events: Iterable[Any]) -> list[SpanNode]:
    """Reconstruct the forest of root spans from a flat event stream.

    Alias of build_trace_forest. Returns the root SpanNode objects in first-seen
    order. See build_trace_forest for the full tolerance contract; this never
    raises on malformed input.
    """

    return build_trace_forest(events)


def _node_label(node: SpanNode) -> str:
    if node.is_synthetic_root:
        return "(root)"
    name = node.name or "span"
    parts = [name]
    if node.span_id:
        parts.append(f"span={node.span_id}")
    if node.duration_ms is not None:
        parts.append(f"duration_ms={node.duration_ms!r}")
    return " ".join(parts)


def _event_line(event: Mapping[str, Any]) -> str:
    etype = event.get("type", "?")
    payload = event.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    seq = event.get("seq", "?")
    return f"[{seq}] {etype}{_event_detail(str(etype), payload)}"


def _event_detail(etype: str, payload: Mapping[str, Any]) -> str:
    """A short human detail string for one event, mirroring the CLI replay style."""
    keys = {
        "agent_message": ("content",),
        "user_message": ("content",),
        "tool_call": ("tool_name",),
        "tool_result": ("call_id",),
        "llm_call": ("model",),
        "browser_action": ("action", "target"),
        "goal_check": ("passed",),
        "state_change": ("name",),
        "score": ("name", "value"),
        "metric": ("name", "value"),
        "error": ("message",),
        "session_end": ("status",),
    }.get(etype, ())
    parts = [f"{k}={payload[k]!r}" for k in keys if k in payload]
    return (" " + " ".join(parts)) if parts else ""


def render_tree(roots: Iterable[SpanNode], *, show_events: bool = True) -> str:
    """Render a forest of SpanNode objects as an indented text tree.

    Indentation uses two spaces per level, matching the CLI replay command. Each
    span is printed on its own line as its label; when show_events is true the
    raw events under a span are printed beneath it, again indented. Synthetic
    roots that only hold flat events render their events without an extra span
    header line. Never raises.
    """

    lines: list[str] = []

    def walk(node: SpanNode, depth: int) -> None:
        indent = "  " * depth
        child_depth = depth
        if not node.is_synthetic_root:
            lines.append(f"{indent}{_node_label(node)}")
            child_depth = depth + 1
        if show_events:
            event_indent = "  " * child_depth
            for event in node.events:
                if _span_marker(event) is not None:
                    # Skip the span's own start/end markers in the rendered body;
                    # the span header line already represents them.
                    continue
                lines.append(f"{event_indent}{_event_line(event)}")
        for child in node.children:
            walk(child, child_depth)

    for root in roots:
        walk(root, 0)

    return "\n".join(lines)
