"""Shared fixtures/helpers for the self-healing fix-agent tests.

A fake Anthropic client lets the Claude runner and the verifier be exercised
without the `anthropic` dependency reaching the network or needing a key. The
fake mirrors the SDK surface the production code actually uses:
`client.messages.parse(..., output_format=Model)` -> object with `.parsed_output`.
"""

from __future__ import annotations

from typing import Any


class _FakeResponse:
    def __init__(self, parsed: Any) -> None:
        self.parsed_output = parsed


class _FakeMessages:
    def __init__(self, parsed: Any, calls: list[dict[str, Any]], error: Exception | None) -> None:
        self._parsed = parsed
        self._calls = calls
        self._error = error

    def parse(self, **kwargs: Any) -> _FakeResponse:
        self._calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return _FakeResponse(self._parsed)


class FakeAnthropic:
    """Stand-in for `anthropic.Anthropic()` capturing the parse() call args."""

    def __init__(self, parsed: Any, calls: list[dict[str, Any]], error: Exception | None) -> None:
        self.messages = _FakeMessages(parsed, calls, error)


def install_fake_anthropic(
    monkeypatch: Any,
    *,
    parsed: Any = None,
    error: Exception | None = None,
) -> list[dict[str, Any]]:
    """Patch `anthropic.Anthropic` + set a key; return the captured parse calls.

    Pass `parsed` for the structured `.parsed_output`, or `error` to make every
    parse() raise (the API-error path the production code must absorb).
    """

    import anthropic

    calls: list[dict[str, Any]] = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(
        anthropic,
        "Anthropic",
        lambda *a, **k: FakeAnthropic(parsed, calls, error),
    )
    return calls


def new_file_diff(path: str) -> str:
    """A minimal well-formed new-file unified diff touching `path`."""

    return (
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1,2 @@\n"
        "+# generated guard\n"
        "+assert True\n"
    )
