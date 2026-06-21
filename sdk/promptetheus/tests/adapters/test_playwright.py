"""Tests for the Playwright adapter.

These tests run with NO real browser and NO playwright package installed.
They prove the adapter stays *thin* over the public Session API:

- each action helper drives the stub Page and emits exactly one matching
  browser_action event with the right action/target/url;
- snapshot/screenshot/finish emit only public event types
  (dom_snapshot/screenshot/replay_artifact);
- across a whole run, the adapter emits NO event types outside the public set;
- importing promptetheus.adapters.playwright does not require Playwright.

The adapter imports Playwright lazily and gates instantiation behind
_require_playwright(). Playwright is not installed in CI, so we register a
minimal fake playwright module in sys.modules for the tests that need to
construct an adapter, and we have a dedicated test that asserts the module
imports cleanly with Playwright entirely absent.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from promptetheus.session import Session


# Event types the adapter is permitted to emit. Anything outside this set means
# the adapter grew an adapter-only event type, which violates "adapters stay
# thin".
PUBLIC_ADAPTER_EVENT_TYPES = {
    "browser_action",
    "dom_snapshot",
    "screenshot",
    "replay_artifact",
}


class RecordingTransport:
    """In-memory transport that captures every enveloped event the session emits."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.flushed = False

    def send_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def flush(self, timeout: float | None = None) -> None:
        self.flushed = True


class FakeVideo:
    """Stub for page.video — only needs .path()."""

    def __init__(self, path: str = "/tmp/recording.webm") -> None:
        self._path = path
        self.path_calls = 0

    def path(self) -> str:
        self.path_calls += 1
        return self._path


class StubPage:
    """A tiny fake Playwright Page.

    Records driven actions so tests can assert the adapter actually drives the
    page, and exposes the read surfaces (url, inner_text, evaluate,
    screenshot, video) the adapter reads from.
    """

    def __init__(
        self,
        url: str = "https://acmemeet.test/book",
        visible_text: str = "Book a meeting",
        selected_values: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        video: FakeVideo | None = None,
        screenshot_bytes: bytes = b"\x89PNG\r\n\x1a\nFAKE",
        goto_result: Any = None,
    ) -> None:
        self.url = url
        self._visible_text = visible_text
        self._selected_values = dict(selected_values or {"day": "tuesday"})
        self._warnings = list(warnings or ["Selected 2:00 AM instead of 2:00 PM"])
        self.video = video
        self._screenshot_bytes = screenshot_bytes
        self._goto_result = goto_result
        # Recorded driven actions, in order: (method, args, kwargs).
        self.calls: list[tuple[str, tuple, dict]] = []

    # -- action surface (recorded) ----------------------------------------

    def click(self, selector: str, **kwargs: Any) -> None:
        self.calls.append(("click", (selector,), kwargs))

    def fill(self, selector: str, value: str, **kwargs: Any) -> None:
        self.calls.append(("fill", (selector, value), kwargs))

    def goto(self, url: str, **kwargs: Any) -> Any:
        self.calls.append(("goto", (url,), kwargs))
        # Playwright resolves/normalizes the URL post-navigation; reflect that.
        self.url = url
        return self._goto_result

    def press(self, selector: str, key: str, **kwargs: Any) -> None:
        self.calls.append(("press", (selector, key), kwargs))

    def select_option(self, selector: str, *args: Any, **kwargs: Any) -> list[str]:
        self.calls.append(("select_option", (selector, *args), kwargs))
        return ["tuesday"]

    # -- read surface (queried by snapshot/screenshot) --------------------

    def inner_text(self, selector: str) -> str:
        self.calls.append(("inner_text", (selector,), {}))
        return self._visible_text

    def evaluate(self, script: str, *args: Any) -> Any:
        # The adapter runs two distinct scripts: selected-values vs warnings.
        # Disambiguate on a substring unique to each.
        if "querySelectorAll('input, select, textarea')" in script:
            return dict(self._selected_values)
        if "role=alert" in script:
            return list(self._warnings)
        return None

    def screenshot(self, **kwargs: Any) -> bytes:
        self.calls.append(("screenshot", (), kwargs))
        return self._screenshot_bytes


@pytest.fixture
def fake_playwright(monkeypatch: pytest.MonkeyPatch):
    """Register a minimal fake playwright package so _require_playwright
    succeeds without the real (uninstalled) dependency.

    Cleaned up automatically by monkeypatch so other tests still observe
    Playwright as absent.
    """
    module = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.Page = StubPage  # type: ignore[attr-defined]
    module.sync_api = sync_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", module)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    return module


@pytest.fixture
def make_adapter(fake_playwright):
    """Build a PlaywrightAdapter over a real Session + RecordingTransport.

    Returns (adapter, page, transport). Imported here (not at module top)
    so the import path is exercised with the fake playwright in place.
    """
    from promptetheus.adapters.playwright import PlaywrightAdapter

    def _make(page: StubPage | None = None, **session_kwargs: Any):
        page = page if page is not None else StubPage()
        transport = RecordingTransport()
        session = Session(
            agent="browser-agent",
            user_goal="Book Tuesday at 2pm Pacific",
            transport=transport,
            **session_kwargs,
        )
        adapter = PlaywrightAdapter(page, session)
        return adapter, page, transport

    return _make


def _browser_actions(transport: RecordingTransport) -> list[dict[str, Any]]:
    return [e for e in transport.events if e["type"] == "browser_action"]


# ---------------------------------------------------------------------------
# Import safety: no top-level playwright dependency
# ---------------------------------------------------------------------------


def test_adapter_module_imports_without_playwright(monkeypatch: pytest.MonkeyPatch):
    """Importing the adapter module must not require Playwright.

    We assert Playwright is genuinely absent, force a fresh import of the
    adapter module, and confirm it imports and exposes PlaywrightAdapter.
    """
    import importlib

    # Ensure no fake/real playwright is resolvable, and force a fresh import.
    monkeypatch.delitem(sys.modules, "playwright", raising=False)
    monkeypatch.delitem(sys.modules, "playwright.sync_api", raising=False)
    monkeypatch.delitem(sys.modules, "promptetheus.adapters.playwright", raising=False)

    assert importlib.util.find_spec("playwright") is None

    module = importlib.import_module("promptetheus.adapters.playwright")
    assert hasattr(module, "PlaywrightAdapter")


def test_instantiation_requires_playwright_when_absent(monkeypatch: pytest.MonkeyPatch):
    """With Playwright absent, constructing the adapter raises a clear error.

    This proves the lazy guard runs at instantiation (not import) time.
    """
    monkeypatch.delitem(sys.modules, "playwright", raising=False)

    from promptetheus.adapters.playwright import PlaywrightAdapter

    transport = RecordingTransport()
    session = Session(agent="a", user_goal="g", transport=transport)
    with pytest.raises(RuntimeError, match="playwright"):
        PlaywrightAdapter(StubPage(), session)


# ---------------------------------------------------------------------------
# Action pass-throughs: drive the page AND emit exactly one matching event
# ---------------------------------------------------------------------------


def test_click_drives_page_and_emits_one_browser_action(make_adapter):
    adapter, page, transport = make_adapter()

    adapter.click("button[data-day='tuesday']")

    # Page was driven.
    assert ("click", ("button[data-day='tuesday']",), {}) in page.calls
    # Exactly one browser_action emitted.
    actions = _browser_actions(transport)
    assert len(actions) == 1
    payload = actions[0]["payload"]
    assert payload["action"] == "click"
    assert payload["target"] == "button[data-day='tuesday']"
    assert payload["url"] == page.url


def test_fill_drives_page_and_emits_one_browser_action(make_adapter):
    adapter, page, transport = make_adapter()

    adapter.fill("input[name='guest']", "alice@acme.test")

    assert ("fill", ("input[name='guest']", "alice@acme.test"), {}) in page.calls
    actions = _browser_actions(transport)
    assert len(actions) == 1
    payload = actions[0]["payload"]
    assert payload["action"] == "fill"
    assert payload["target"] == "input[name='guest']"
    assert payload["url"] == page.url


def test_goto_drives_page_and_emits_resolved_url(make_adapter):
    response = object()
    adapter, page, transport = make_adapter(StubPage(goto_result=response))

    result = adapter.goto("https://acmemeet.test/confirm")

    assert result is response
    assert ("goto", ("https://acmemeet.test/confirm",), {}) in page.calls
    actions = _browser_actions(transport)
    assert len(actions) == 1
    payload = actions[0]["payload"]
    assert payload["action"] == "goto"
    assert payload["target"] == "https://acmemeet.test/confirm"
    # After navigation the stub page resolves to the new URL.
    assert payload["url"] == "https://acmemeet.test/confirm"


def test_select_option_drives_page_and_emits_select_action(make_adapter):
    adapter, page, transport = make_adapter()

    result = adapter.select_option("select[name='day']", "tuesday")

    # Pass-through returns the page's result.
    assert result == ["tuesday"]
    assert page.calls[0][0] == "select_option"
    assert page.calls[0][1] == ("select[name='day']", "tuesday")
    actions = _browser_actions(transport)
    assert len(actions) == 1
    payload = actions[0]["payload"]
    assert payload["action"] == "select"
    assert payload["target"] == "select[name='day']"
    assert payload["url"] == page.url


def test_each_action_emits_exactly_one_event(make_adapter):
    """A sequence of N actions emits exactly N browser_action events."""
    adapter, page, transport = make_adapter()

    adapter.goto("https://acmemeet.test/book")
    adapter.click("button[data-day='tuesday']")
    adapter.fill("input[name='time']", "2:00 PM")
    adapter.select_option("select[name='tz']", "America/Los_Angeles")

    actions = _browser_actions(transport)
    assert [a["payload"]["action"] for a in actions] == [
        "goto",
        "click",
        "fill",
        "select",
    ]
    assert len(actions) == 4


# ---------------------------------------------------------------------------
# snapshot / screenshot
# ---------------------------------------------------------------------------


def test_snapshot_emits_dom_snapshot_from_page(make_adapter):
    page = StubPage(
        url="https://acmemeet.test/book",
        visible_text="Pick a time",
        selected_values={"day": "tuesday", "time": "2:00 AM"},
        warnings=["Selected 2:00 AM instead of 2:00 PM"],
    )
    adapter, page, transport = make_adapter(page)

    event = adapter.snapshot()

    assert event is not None
    assert event["type"] == "dom_snapshot"
    payload = event["payload"]
    assert payload["url"] == "https://acmemeet.test/book"
    assert payload["visible_text"] == "Pick a time"
    assert payload["selected_values"] == {"day": "tuesday", "time": "2:00 AM"}
    assert payload["warnings"] == ["Selected 2:00 AM instead of 2:00 PM"]

    snapshots = [e for e in transport.events if e["type"] == "dom_snapshot"]
    assert len(snapshots) == 1


def test_snapshot_selected_values_skip_sensitive_fields_by_default(make_adapter):
    class SensitiveAwarePage(StubPage):
        def evaluate(self, script: str, *args: Any) -> Any:
            if "querySelectorAll('input, select, textarea')" not in script:
                return super().evaluate(script, *args)
            required_filters = [
                "password",
                "hidden",
                "token",
                "secret",
                "auth",
                "csrf",
                "xsrf",
                "one-time-code",
            ]
            assert all(term in script for term in required_filters)
            return {
                "meeting_title": "Planning",
                # These would be present if the DOM filter were removed.
                # The fake asserts the policy is embedded in the evaluated JS and
                # returns only the values a filtered page evaluation should expose.
            }

    page = SensitiveAwarePage()
    adapter, page, transport = make_adapter(page)

    event = adapter.snapshot()

    assert event is not None
    selected = event["payload"]["selected_values"]
    assert selected == {"meeting_title": "Planning"}
    serialized = repr(selected).lower()
    assert "secret" not in serialized
    assert "token" not in serialized
    assert "password" not in serialized


def test_screenshot_emits_screenshot_event(make_adapter):
    page = StubPage(screenshot_bytes=b"PNGBYTES")
    adapter, page, transport = make_adapter(page)

    event = adapter.screenshot()

    assert event is not None
    assert event["type"] == "screenshot"
    # session.screenshot records bytes source + size.
    assert event["payload"]["source_type"] == "bytes"
    assert event["payload"]["size_bytes"] == len(b"PNGBYTES")
    assert ("screenshot", (), {}) in page.calls

    shots = [e for e in transport.events if e["type"] == "screenshot"]
    assert len(shots) == 1


# ---------------------------------------------------------------------------
# finish / __exit__ -> replay_artifact with event_time_map
# ---------------------------------------------------------------------------


def test_finish_emits_replay_artifact_with_event_time_map(make_adapter):
    video = FakeVideo("/tmp/acmemeet-run.webm")
    page = StubPage(video=video)
    adapter, page, transport = make_adapter(page)

    adapter.click("button[data-day='tuesday']")
    adapter.fill("input[name='time']", "2:00 PM")

    event = adapter.finish()

    assert event is not None
    assert event["type"] == "replay_artifact"
    payload = event["payload"]
    assert payload["artifact_type"] == "screen_recording"
    assert payload["source"] == "/tmp/acmemeet-run.webm"
    assert video.path_calls == 1

    # event_time_map maps str(seq) -> int ms for each emitted browser_action.
    etm = payload["event_time_map"]
    action_seqs = [a["seq"] for a in _browser_actions(transport)]
    assert set(etm.keys()) == {str(seq) for seq in action_seqs}
    assert len(etm) == 2
    for key, value in etm.items():
        assert isinstance(key, str)
        assert isinstance(value, int)
        assert not isinstance(value, bool)
        assert value >= 0


def test_context_manager_exit_emits_replay_artifact(make_adapter):
    video = FakeVideo("/tmp/ctx-run.webm")
    page = StubPage(video=video)
    adapter, page, transport = make_adapter(page)

    with adapter as a:
        a.click("button#go")

    artifacts = [e for e in transport.events if e["type"] == "replay_artifact"]
    assert len(artifacts) == 1
    assert artifacts[0]["payload"]["source"] == "/tmp/ctx-run.webm"
    # One browser_action -> one entry in the time map.
    assert len(artifacts[0]["payload"]["event_time_map"]) == 1


def test_finish_is_idempotent(make_adapter):
    video = FakeVideo("/tmp/once.webm")
    page = StubPage(video=video)
    adapter, page, transport = make_adapter(page)

    adapter.click("button#go")
    first = adapter.finish()
    second = adapter.finish()

    assert first is not None
    assert second is None  # second call is a no-op
    artifacts = [e for e in transport.events if e["type"] == "replay_artifact"]
    assert len(artifacts) == 1


def test_finish_without_video_emits_nothing(make_adapter):
    page = StubPage(video=None)
    adapter, page, transport = make_adapter(page)

    adapter.click("button#go")
    event = adapter.finish()

    assert event is None
    assert [e for e in transport.events if e["type"] == "replay_artifact"] == []


# ---------------------------------------------------------------------------
# Thinness: across a full run, only public event types are emitted
# ---------------------------------------------------------------------------


def test_full_run_emits_only_public_event_types(make_adapter):
    video = FakeVideo("/tmp/full-run.webm")
    page = StubPage(video=video)
    adapter, page, transport = make_adapter(page)

    adapter.goto("https://acmemeet.test/book")
    adapter.click("button[data-day='tuesday']")
    adapter.fill("input[name='time']", "2:00 PM")
    adapter.select_option("select[name='tz']", "America/Los_Angeles")
    adapter.snapshot()
    adapter.screenshot()
    adapter.finish()

    emitted_types = {e["type"] for e in transport.events}
    # Every emitted type is in the public adapter set — no adapter-only types.
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES
    # And all four public categories were exercised.
    assert emitted_types == PUBLIC_ADAPTER_EVENT_TYPES


def test_adapter_emits_no_session_lifecycle_events(make_adapter):
    """The adapter itself never emits state_change/session_end/etc.

    Those belong to the Session lifecycle, not the adapter. Here the Session
    is constructed directly (not via trace.start context entry), so the only
    events present must come from adapter calls.
    """
    adapter, page, transport = make_adapter()

    adapter.click("a")
    adapter.fill("b", "v")

    for event in transport.events:
        assert event["type"] not in {
            "state_change",
            "session_end",
            "user_message",
            "tool_call",
        }
