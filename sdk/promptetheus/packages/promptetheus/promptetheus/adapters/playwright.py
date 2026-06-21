"""Playwright adapter for Promptetheus.

A thin wrapper over a Playwright Page and the public Promptetheus
Session API. The adapter performs the Playwright
action and emits the matching browser_action event through the existing
Session helpers. It introduces no adapter-only event types and no
server-side behavior — anything it does, a caller could do by hand with the
public session.* helpers.

Playwright is an optional dependency. It is imported lazily inside methods, so
importing this module without Playwright installed must not fail. The helper
methods raise the missing-dependency error only if you actually drive a page,
and snapshot/screenshot/finish degrade gracefully (logged, never
raised) to preserve the SDK's never-crash guarantee.
"""

from __future__ import annotations

import logging
import time
from types import TracebackType
from typing import TYPE_CHECKING, Any

from ._base import require_extra

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from playwright.sync_api import Page

    from ..session import Session

logger = logging.getLogger("promptetheus")


class PlaywrightAdapter:
    """Instrument a Playwright Page against a Promptetheus Session.

    The adapter wraps a live Page and a Session. Its helper methods
    (click, fill, goto, press, select_option) are faithful
    pass-throughs: they perform the Playwright action and emit the matching
    session.browser_action(action, target, url) event — they are not a new
    API surface.

    snapshot and screenshot read from the live page and hand the result
    to the corresponding Session artifact helper. finish resolves the
    Playwright .webm video path and emits a replay_artifact event with an
    event_time_map that maps each emitted browser_action sequence number
    to its millisecond offset into the recording.

    The adapter can be used as a context manager; __exit__ calls finish
    so the replay artifact is finalized even if the block raises.
    """

    def __init__(
        self,
        page: "Page",
        session: "Session | None" = None,
        *,
        recording_started_at: float | None = None,
    ) -> None:
        # Import lazily so importing this module never requires Playwright. The
        # check only runs when an adapter is actually instantiated against a page.
        require_extra("playwright", "playwright", "PlaywrightAdapter")

        if session is None:
            from ..session import current

            session = current()  # type: ignore[assignment]

        self.page = page
        self.session = session
        # Wall-clock anchor (time.monotonic seconds) for the recording, used
        # to compute per-action millisecond offsets for event_time_map. The
        # Playwright video starts when the browser context is created, which is
        # before this adapter exists; pass recording_started_at (a
        # time.monotonic() reading taken at context creation) to anchor
        # offsets to the true video t=0. When omitted we anchor to "now" and
        # offsets are relative to instrumentation start (best-effort).
        self._recording_anchor_explicit = recording_started_at is not None
        self._recording_started_at = (
            recording_started_at
            if recording_started_at is not None
            else time.monotonic()
        )
        # Maps str(seq) -> int ms offset for each emitted browser_action.
        self._event_time_map: dict[str, int] = {}
        self._finished = False

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> "PlaywrightAdapter":
        # Reset the recording anchor on entry so offsets are measured from the
        # point instrumentation begins — unless the caller passed an explicit
        # recording_started_at anchored to the real video t=0, which we keep.
        if not self._recording_anchor_explicit:
            self._recording_started_at = time.monotonic()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self.finish()
        return False

    # -- internal helpers --------------------------------------------------

    def _now_ms(self) -> int:
        """Milliseconds elapsed since the recording anchor."""
        return int((time.monotonic() - self._recording_started_at) * 1000)

    def _emit_action(
        self,
        action: str,
        target: str,
        url: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Emit a browser_action and record its recording offset.

        Never raises into the caller: session.browser_action already
        swallows transport errors, and we guard the time-map bookkeeping too.
        metadata carries action-specific detail (e.g. the pressed key) that
        does not belong in the fixed browser_action payload schema.
        """
        try:
            event = self.session.browser_action(
                action=action, target=target, url=url, metadata=metadata
            )
            seq = event.get("seq") if isinstance(event, dict) else None
            if seq is not None:
                self._event_time_map[str(seq)] = self._now_ms()
        except Exception:  # pragma: no cover - defensive; helpers already swallow
            logger.exception(
                "Promptetheus Playwright adapter failed emitting browser_action"
            )

    def _current_url(self) -> str | None:
        try:
            return self.page.url
        except Exception:  # pragma: no cover - defensive
            return None

    # -- action pass-throughs ---------------------------------------------

    def click(self, selector: str, **kwargs: Any) -> None:
        """Click selector and emit a browser_action for it."""
        self.page.click(selector, **kwargs)
        self._emit_action("click", selector, self._current_url())

    def fill(self, selector: str, value: str, **kwargs: Any) -> None:
        """Fill selector with value and emit a browser_action."""
        self.page.fill(selector, value, **kwargs)
        self._emit_action("fill", selector, self._current_url())

    def goto(self, url: str, **kwargs: Any) -> Any:
        """Navigate to url and emit a browser_action for it."""
        result = self.page.goto(url, **kwargs)
        # After navigation, report the page's resolved URL when available.
        self._emit_action("goto", url, self._current_url() or url)
        return result

    def press(self, selector: str, key: str, **kwargs: Any) -> None:
        """Press key on selector and emit a browser_action."""
        self.page.press(selector, key, **kwargs)
        self._emit_action("press", selector, self._current_url(), metadata={"key": key})

    def select_option(self, selector: str, value: Any = None, **kwargs: Any) -> Any:
        """Select an option on selector and emit a browser_action."""
        if value is not None:
            result = self.page.select_option(selector, value, **kwargs)
        else:
            result = self.page.select_option(selector, **kwargs)
        self._emit_action("select", selector, self._current_url())
        return result

    # -- snapshots / artifacts --------------------------------------------

    def snapshot(self) -> dict[str, Any] | None:
        """Capture a DOM snapshot of the live page via session.dom_snapshot.

        Reads visible body text, currently-selected form values, and visible
        warning/error text. Failures are logged and swallowed (returns None)
        so observing the page never crashes the agent.
        """
        try:
            url = self.page.url
            visible_text = self._read_visible_text()
            selected_values = self._read_selected_values()
            warnings = self._read_warnings()
        except Exception:
            logger.exception(
                "Promptetheus Playwright adapter failed building dom_snapshot"
            )
            return None

        return self.session.dom_snapshot(
            url=url,
            visible_text=visible_text,
            selected_values=selected_values,
            warnings=warnings,
        )

    def screenshot(self, **kwargs: Any) -> dict[str, Any] | None:
        """Capture page screenshot bytes and hand them to session.screenshot.

        Failures are logged and swallowed (returns None).
        """
        try:
            image_bytes = self.page.screenshot(**kwargs)
        except Exception:
            logger.exception(
                "Promptetheus Playwright adapter failed capturing screenshot"
            )
            return None
        return self.session.screenshot(image_bytes)

    def finish(self) -> dict[str, Any] | None:
        """Finalize the replay artifact from the Playwright .webm video.

        Resolves page.video.path() and emits a replay_artifact event with
        artifact_type="screen_recording" and the accumulated
        event_time_map (str(seq) -> int ms). Idempotent; safe to call
        from both an explicit call and __exit__. Failures are logged and
        swallowed (returns None).
        """
        if self._finished:
            return None
        self._finished = True

        try:
            video = getattr(self.page, "video", None)
            if video is None:
                # No recording was configured on this context; nothing to emit.
                return None
            source = video.path()
        except Exception:
            logger.exception(
                "Promptetheus Playwright adapter failed resolving video path"
            )
            return None

        if not source:
            return None

        return self.session.replay_artifact(
            source=str(source),
            artifact_type="screen_recording",
            event_time_map=dict(self._event_time_map),
        )

    # -- low-level page readers (best-effort) -----------------------------

    def _read_visible_text(self) -> str:
        try:
            return self.page.inner_text("body")
        except Exception:  # pragma: no cover - defensive
            return ""

    def _read_selected_values(self) -> dict[str, Any]:
        """Collect values of filled inputs and selected <select> options.

        Best-effort: evaluates a small DOM script. Returns an empty dict if the
        page cannot be evaluated.
        """
        script = """
        () => {
            const out = {};
            const named = (el, i) => el.name || el.id || (el.tagName.toLowerCase() + '_' + i);
            const secretPattern = /(password|passwd|pwd|token|secret|auth|csrf|xsrf|credential|api[-_]?key|access[-_]?key|session)/i;
            const attr = (el, name) => (el.getAttribute(name) || '');
            const isSensitive = (el) => {
                const type = (el.type || '').toLowerCase();
                if (type === 'password' || type === 'hidden') return true;
                const name = attr(el, 'name');
                const id = attr(el, 'id');
                const autocomplete = attr(el, 'autocomplete').toLowerCase();
                if (secretPattern.test(name) || secretPattern.test(id)) return true;
                if (
                    autocomplete.includes('password') ||
                    autocomplete.includes('one-time-code') ||
                    autocomplete.includes('token') ||
                    autocomplete.includes('auth') ||
                    autocomplete.includes('csrf') ||
                    autocomplete.startsWith('cc-')
                ) return true;
                return false;
            };
            const fields = Array.from(document.querySelectorAll('input, select, textarea'));
            fields.forEach((el, i) => {
                if (isSensitive(el)) return;
                const tag = el.tagName.toLowerCase();
                if (tag === 'select') {
                    out[named(el, i)] = el.value;
                } else if (el.type === 'checkbox' || el.type === 'radio') {
                    if (el.checked) out[named(el, i)] = el.value;
                } else if (el.value !== undefined && el.value !== '') {
                    out[named(el, i)] = el.value;
                }
            });
            return out;
        }
        """
        try:
            result = self.page.evaluate(script)
        except Exception:  # pragma: no cover - defensive
            return {}
        return dict(result) if isinstance(result, dict) else {}

    def _read_warnings(self) -> list[str]:
        """Collect visible warning/error text from common alert containers.

        Best-effort: looks at [role=alert] and common error/warning class
        substrings. Returns an empty list if the page cannot be evaluated.
        """
        script = """
        () => {
            const sel = '[role=alert], .error, .warning, .alert, [class*="error"], [class*="warning"]';
            const seen = new Set();
            const out = [];
            document.querySelectorAll(sel).forEach((el) => {
                const text = (el.innerText || '').trim();
                if (text && !seen.has(text)) { seen.add(text); out.push(text); }
            });
            return out;
        }
        """
        try:
            result = self.page.evaluate(script)
        except Exception:  # pragma: no cover - defensive
            return []
        if not isinstance(result, list):
            return []
        return [str(item) for item in result if str(item).strip()]


__all__ = ["PlaywrightAdapter"]
