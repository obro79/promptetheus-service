"""Shared helpers for the Promptetheus integration adapters.

Every adapter wraps an optional third-party framework and translates its events
onto the public Session API. They share the same scaffolding, which lived
duplicated across a dozen files; it is consolidated here:

- require_extra: lazy-import a framework and raise a clear, consistent error
  naming the pip extra when it is absent.
- extract_token_usage: pull (input_tokens, output_tokens) out of the many usage
  shapes providers return (OpenAI prompt/completion, Anthropic input/output,
  LangChain usage_metadata, plain dicts), tolerantly.
- BoundedRunState: a per-run correlation map (start -> end) that is capped so a
  long-lived adapter cannot accumulate orphaned entries without bound.
- run_key / coerce_arguments / safe_str: small normalizers.

None of these import a third-party library at module load; importing this module
(or any adapter) never requires an extra to be installed.
"""

from __future__ import annotations

import collections
import importlib
from typing import Any, Iterator


def require_extra(import_name: str, extra: str, who: str) -> Any:
    """Import and return a framework module, or raise a clear missing-extra error.

    Called only when an adapter is actually used, so importing the adapter module
    never requires the optional dependency. import_name is the module to import
    (e.g. litellm), extra is the pip extra (e.g. litellm), who is the public
    adapter symbol named in the error (e.g. LiteLLMAdapter).
    """

    try:
        return importlib.import_module(import_name)
    except Exception as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            f"{who} requires the optional '{extra}' extra. "
            f"Install it with: pip install 'promptetheus[{extra}]'"
        ) from exc


def _get(obj: Any, name: str) -> Any:
    """Attribute or mapping lookup, tolerant of either shape."""
    if isinstance(obj, collections.abc.Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_token_usage(source: Any) -> tuple[int | None, int | None]:
    """Best-effort (input_tokens, output_tokens) from a provider usage object.

    Handles the common shapes without requiring any provider library:
    - OpenAI: usage.prompt_tokens / usage.completion_tokens
    - Anthropic: usage.input_tokens / usage.output_tokens
    - LangChain: usage_metadata.input_tokens / output_tokens
    - plain dicts using any of the above keys
    Returns (None, None) for anything unrecognized. Never raises.
    """

    try:
        usage = source
        # Unwrap a nested usage / usage_metadata holder if present.
        for attr in ("usage", "usage_metadata", "token_usage"):
            nested = _get(source, attr)
            if nested is not None:
                usage = nested
                break
        if usage is None:
            return None, None

        input_tokens = (
            _coerce_int(_get(usage, "input_tokens"))
            if _get(usage, "input_tokens") is not None
            else _coerce_int(_get(usage, "prompt_tokens"))
        )
        output_tokens = (
            _coerce_int(_get(usage, "output_tokens"))
            if _get(usage, "output_tokens") is not None
            else _coerce_int(_get(usage, "completion_tokens"))
        )
        return input_tokens, output_tokens
    except Exception:  # pragma: no cover - usage extraction must never raise
        return None, None


def run_key(run_id: Any) -> str:
    """Stable string key for a framework run id (often a uuid.UUID)."""
    return str(run_id) if run_id is not None else "unknown"


def coerce_arguments(raw: Any) -> dict[str, Any]:
    """Normalize tool-call arguments into a dict for the tool_call payload.

    Accepts a dict (returned as-is), a JSON string (parsed when possible), or
    anything else (wrapped under an "input" key). Never raises.
    """

    if isinstance(raw, collections.abc.Mapping):
        return dict(raw)
    if isinstance(raw, str):
        try:
            import json

            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {"input": raw}
    if raw is None:
        return {}
    return {"input": raw}


def safe_str(value: Any) -> str | None:
    """Coerce to a non-empty string, or None. Never raises.

    A value whose __str__ raises (some framework objects do) is treated as
    absent rather than propagating, matching the per-adapter helpers this
    replaced.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    try:
        text = str(value)
    except Exception:
        return None
    return text or None


class BoundedRunState:
    """A capped, insertion-ordered map for per-run adapter state.

    Adapters correlate a start callback with its end callback by run id. If an
    end never fires (cancellation), the entry would leak; this evicts the oldest
    entry once the cap is hit so the map stays bounded over a long-lived adapter.
    Thread-unfriendly callers should guard externally; framework callbacks are
    typically single-threaded per run.
    """

    def __init__(self, max_size: int = 1024) -> None:
        self._max = max(1, int(max_size))
        self._data: collections.OrderedDict[str, Any] = collections.OrderedDict()

    def set(self, key: str, value: Any) -> None:
        while len(self._data) >= self._max and key not in self._data:
            self._data.popitem(last=False)  # evict oldest
        self._data[key] = value

    def pop(self, key: str, default: Any = None) -> Any:
        return self._data.pop(key, default)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)


__all__ = [
    "BoundedRunState",
    "coerce_arguments",
    "extract_token_usage",
    "require_extra",
    "run_key",
    "safe_str",
]
