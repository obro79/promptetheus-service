"""AutoGen adapter for Promptetheus.

A thin bridge between AutoGen's conversable agents and the public Promptetheus
Session helpers. AutoGen (autogen-agentchat / pyautogen) drives a
conversation between agents that exchange messages and call registered tools /
functions. Each agent is a ConversableAgent exposing a register_reply hook:
register_reply(trigger, reply_func) installs a callback that AutoGen invokes,
in registration order, every time the agent is about to produce a reply.

This adapter installs one observe-only reply hook per agent. The hook reads the
incoming messages, emits an agent_message for the latest one and a
tool_call / tool_result pair for any tool/function call it carries, then
returns (False, None) so AutoGen falls through to the agent's real reply
logic unchanged. The hook never produces a reply itself, so it cannot alter the
conversation. It introduces no adapter-only event types and no server-side
behavior — everything it emits, a caller could emit by hand with the public
session.* helpers.

autogen is an optional dependency. Importing this module must NOT require it:
the library is touched only when AutoGenAdapter is constructed or an agent is
attached. Without the extra, those operations raise a clear RuntimeError naming
the autogen extra:

    from promptetheus.adapters import AutoGenAdapter

    adapter = AutoGenAdapter()          # default session = current()
    adapter.attach(assistant)           # install reply hook on an agent
    adapter.attach(user_proxy)
    try:
        user_proxy.initiate_chat(assistant, message="...")
    finally:
        adapter.detach_all()            # (also: with AutoGenAdapter() as a)

AutoGen's API has drifted across the pyautogen / autogen-agentchat / ag2
forks: the ConversableAgent class lives under different module paths and the
reply-hook signature gained keyword-only variants. This adapter therefore
feature-detects the agent surface (duck-typed register_reply) and calls the
hook defensively. It is REVIEW-VERIFIED, not lib-verified: autogen is not
installed in this environment, so the hook wiring and message shapes below were
checked against AutoGen's documented register_reply contract and ConversableAgent
message format rather than exercised against the live library. Hook callbacks
log and swallow all telemetry failures, so an instrumentation problem never
raises into AutoGen's own run loop.
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import TYPE_CHECKING, Any

from ._base import BoundedRunState, safe_str

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from ..session import NoopSession, Session

logger = logging.getLogger("promptetheus")


# Candidate import paths for AutoGen's ConversableAgent, newest fork first. The
# class moved across the pyautogen -> autogen -> ag2 forks; we try each in order
# and use the first that imports. Resolving the class is also how we confirm the
# extra is installed at construction time.
_CONVERSABLE_AGENT_PATHS = (
    ("autogen", "ConversableAgent"),
    ("autogen.agentchat", "ConversableAgent"),
    ("autogen.agentchat.conversable_agent", "ConversableAgent"),
    ("ag2", "ConversableAgent"),
    ("pyautogen", "ConversableAgent"),
)


def _require_autogen() -> Any:
    """Import and return AutoGen's ConversableAgent class, or raise a clear error.

    Tries each known module path. Raised only when the adapter is actually
    constructed, so importing this module never requires the optional autogen
    extra.
    """
    last_exc: BaseException | None = None
    for module_path, attr in _CONVERSABLE_AGENT_PATHS:
        try:
            import importlib

            module = importlib.import_module(module_path)
            cls = getattr(module, attr, None)
            if cls is not None:
                return cls
        except Exception as exc:  # pragma: no cover - exercised only without extra
            last_exc = exc

    raise RuntimeError(
        "AutoGenAdapter requires the optional 'autogen' extra. "
        "Install it with: pip install 'promptetheus[autogen]'"
    ) from last_exc


def _always_trigger(sender: Any = None) -> bool:
    """A register_reply trigger that matches every turn.

    AutoGen accepts a Callable[[Agent], bool] as a trigger and calls it with the
    sender; returning True always installs the hook for every reply turn. This is
    the cross-fork replacement for trigger=None, which AutoGen's _match_trigger
    treats as "matches only when sender is None" rather than "always".
    """
    return True


def _agent_name(agent: Any) -> str:
    """Best-effort display name for an AutoGen agent."""
    name = getattr(agent, "name", None)
    if isinstance(name, str) and name:
        return name
    return "agent"


def _last_message(messages: Any) -> Any:
    """Return the most recent message from an AutoGen messages list, or None.

    AutoGen passes the running conversation as a list of message dicts (each with
    role / content and, for tool turns, tool_calls or function_call). We
    observe only the latest entry so each hook invocation emits one turn rather
    than re-emitting the whole history.
    """
    if not isinstance(messages, (list, tuple)) or not messages:
        return None
    return messages[-1]


def _message_content(message: Any) -> str | None:
    """Extract the textual content from an AutoGen message, or None.

    AutoGen messages are dicts whose content may be a plain string or, for
    multimodal turns, a list of content parts; we stringify a non-empty value and
    leave None alone so empty tool-only turns emit no agent_message.
    """
    content = _get(message, "content")
    if content is None:
        return None
    if isinstance(content, str):
        return content or None
    return safe_str(content)


def _tool_calls(message: Any) -> list[Any]:
    """Return the tool/function calls carried by an AutoGen message.

    AutoGen's current shape uses tool_calls (a list, OpenAI tool-call style);
    older builds used a single function_call dict. We normalize both to a list
    so the caller emits one tool_call per entry.
    """
    tool_calls = _get(message, "tool_calls")
    if isinstance(tool_calls, (list, tuple)):
        return list(tool_calls)
    function_call = _get(message, "function_call")
    if function_call is not None:
        return [function_call]
    return []


def _tool_results(message: Any) -> list[Any]:
    """Return any tool/function responses carried by an AutoGen message.

    A tool-response turn has role "tool" (or "function") and carries the
    output under content, correlated by tool_call_id (or name on the older
    function shape). Non-tool turns yield an empty list.
    """
    role = safe_str(_get(message, "role"))
    if role not in ("tool", "function"):
        return []
    responses = _get(message, "tool_responses")
    if isinstance(responses, (list, tuple)):
        return list(responses)
    return [message]


class AutoGenAdapter:
    """Observe AutoGen conversable agents against a Promptetheus Session.

    Construct the adapter, attach it to each agent in the conversation, then run
    AutoGen normally; detach when done (or use it as a context manager):

        adapter = AutoGenAdapter(session)
        adapter.attach(assistant)
        adapter.attach(user_proxy)
        user_proxy.initiate_chat(assistant, message="book a room")
        adapter.detach_all()

    attach installs an observe-only reply hook via the agent's
    register_reply: the hook reads the latest message, emits the matching public
    events (agent_message, tool_call, tool_result), and returns
    (False, None) so AutoGen's real reply logic runs unchanged. The hook never
    produces a reply, so instrumentation cannot alter the conversation.

    session defaults to promptetheus.current (the active session, or a no-op
    session when none is active), so the adapter is safe to construct even
    outside an observed run.

    Raises:
        RuntimeError: if the optional autogen extra is not installed (resolved
            lazily at construction, never at module import).
    """

    def __init__(self, session: "Session | NoopSession | None" = None) -> None:
        if session is None:
            from ..session import current

            session = current()
        self.session = session

        # Resolve the agent class now so a missing extra fails fast and clearly,
        # before any agent work — mirroring the other framework adapters.
        self._conversable_agent_cls = _require_autogen()
        # Agents we attached a hook to, with the hook callable, for teardown.
        self._attached: list[tuple[Any, Any]] = []
        # Per-adapter (not per-agent) record of messages already emitted, so the
        # same logical turn observed by more than one attached agent's hook emits
        # exactly once. Bounded as an insertion-ordered ring; oldest keys evicted
        # first when the cap is hit.
        self._seen_messages = BoundedRunState()
        self._stopped = False

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> "AutoGenAdapter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self.detach_all()
        return False

    # -- attach / detach ---------------------------------------------------

    def attach(self, agent: Any) -> None:
        """Install the observe-only reply hook on an AutoGen agent.

        Uses the agent's register_reply(trigger, reply_func) hook. The trigger is
        a callable that always returns True, so the hook fires on every reply
        turn. AutoGen's _match_trigger treats trigger=None as "matches only when
        sender is None" (NOT "always"), which would silence the hook for normal
        agent-to-agent turns; a Callable[[Agent], bool] trigger that always
        returns True is the cross-fork way to match every turn. The hook is
        registered at position-0 so it observes before the real reply logic runs.
        Best-effort: an agent without register_reply is skipped with a log line
        rather than raising.
        """
        register_reply = getattr(agent, "register_reply", None)
        if not callable(register_reply):
            logger.debug(
                "Promptetheus AutoGen adapter: agent %r has no register_reply; skipping",
                _agent_name(agent),
            )
            return

        hook = self._make_hook(agent)
        try:
            # An always-true callable trigger fires the hook on every reply turn
            # (AutoGen accepts Callable[[Agent], bool] as a trigger). We register
            # at position 0 but always return (False, None), so position relative
            # to other reply funcs does not change the conversation outcome.
            try:
                register_reply(_always_trigger, hook, position=0)
            except TypeError:
                # Older/forked signatures may not accept the position keyword.
                register_reply(_always_trigger, hook)
            self._attached.append((agent, hook))
        except Exception:  # pragma: no cover - defensive across forks
            logger.debug(
                "Promptetheus AutoGen adapter could not register reply hook on %r",
                _agent_name(agent),
                exc_info=True,
            )

    def detach_all(self) -> None:
        """Stop observing: neutralize every installed hook. Idempotent, never raises.

        AutoGen exposes no public de-registration for register_reply across forks
        (reply funcs live in the agent's internal _reply_func_list), so teardown
        flips a guard that makes our hooks emit nothing further; the hook itself
        stays a harmless (False, None) no-op for the remainder of the run.
        """
        if self._stopped:
            return
        self._stopped = True

    # Alias matching the handle-style teardown used by the other adapters.
    def stop(self) -> None:
        """Alias for detach_all."""
        self.detach_all()

    # -- hook factory ------------------------------------------------------

    def _make_hook(self, agent: Any) -> Any:
        """Build the reply_func AutoGen will call for agent.

        AutoGen invokes a reply func as
        reply_func(recipient, messages=None, sender=None, config=None) and
        expects a (final: bool, reply) tuple; returning (False, None) means
        "I have no reply, continue to the next reply func", which is how we
        observe without intercepting. We accept *args/**kwargs so signature
        drift across forks cannot raise into the run loop.
        """

        def _hook(
            recipient: Any = None,
            messages: Any = None,
            sender: Any = None,
            config: Any = None,
            *args: Any,
            **kwargs: Any,
        ) -> tuple[bool, Any]:
            if not self._stopped:
                try:
                    self._observe(messages, sender, recipient)
                except Exception:  # pragma: no cover - helpers already swallow
                    logger.exception(
                        "Promptetheus AutoGen adapter failed observing a reply turn"
                    )
            # Never intercept: defer to the agent's real reply logic.
            return False, None

        return _hook

    # -- observation (AutoGen messages -> Session helpers) -----------------

    def _observe(self, messages: Any, sender: Any, recipient: Any) -> None:
        """Emit public events for the latest message in a reply turn.

        Reads only the most recent message so repeated hook calls do not
        re-emit history. A tool-response turn maps to tool_result; a turn
        carrying tool/function calls maps to one tool_call each; otherwise a
        text turn maps to agent_message.
        """
        message = _last_message(messages)
        if message is None:
            return

        # De-duplicate across hooks: AutoGen shares the running message list, so
        # the same latest message can be observed by more than one attached
        # agent's hook within overlapping turns. Emit each logical turn once.
        if self._already_seen(message):
            return

        # Tool-response turn (role tool/function): emit tool_result(s).
        results = _tool_results(message)
        if results:
            for response in results:
                self._emit_tool_result(response)
            return

        # Tool/function-call turn: emit one tool_call per call.
        calls = _tool_calls(message)
        if calls:
            for call in calls:
                self._emit_tool_call(call)

        # Text content (may co-exist with tool calls on a single assistant turn).
        content = _message_content(message)
        if content:
            self.session.agent_message(content=content)

    def _already_seen(self, message: Any) -> bool:
        """Return True if message was already emitted; otherwise record it.

        Keyed by a stable message identity (object id plus a content/role/
        tool-id hash) so the same shared message is not re-emitted by a second
        attached agent's hook. The seen set is bounded; oldest keys evict first.
        """
        try:
            key = _message_key(message)
        except Exception:  # pragma: no cover - defensive; never block emission
            return False
        if key in self._seen_messages:
            return True
        self._seen_messages.set(key, None)
        return False

    def _emit_tool_call(self, call: Any) -> None:
        """Map one AutoGen tool/function call to session.tool_call."""
        try:
            function = _get(call, "function")
            # tool_calls: {id, function: {name, arguments}}. Older function_call:
            # {name, arguments} directly on the call.
            name = (
                safe_str(_get(function, "name"))
                or safe_str(_get(call, "name"))
                or "tool"
            )
            raw_args = _get(function, "arguments")
            if raw_args is None:
                raw_args = _get(call, "arguments")
            arguments = _coerce_arguments(raw_args)
            call_id = safe_str(_get(call, "id")) or safe_str(_get(call, "tool_call_id"))
            self.session.tool_call(tool_name=name, arguments=arguments, call_id=call_id)
        except Exception:  # pragma: no cover - helpers already swallow
            logger.exception("Promptetheus AutoGen adapter failed emitting tool_call")

    def _emit_tool_result(self, response: Any) -> None:
        """Map one AutoGen tool/function response to session.tool_result."""
        try:
            call_id = safe_str(_get(response, "tool_call_id")) or safe_str(
                _get(response, "call_id")
            )
            content = _get(response, "content")
            # Older function shape correlates by name rather than id.
            if call_id is None:
                call_id = safe_str(_get(response, "name"))
            self.session.tool_result(
                call_id=call_id or "unknown",
                result=content,
            )
        except Exception:  # pragma: no cover - helpers already swallow
            logger.exception("Promptetheus AutoGen adapter failed emitting tool_result")


# -- module-level helpers (duck-typed, dependency-free) -------------------


def _get(obj: Any, name: str) -> Any:
    """Read name from a dict or a plain object; never raise."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _message_key(message: Any) -> str:
    """Build a stable de-dup key for an AutoGen message.

    Combines the object identity with a content/role/tool-id signature so a turn
    is matched whether the same dict object is shared across hooks or an equal
    copy is presented. Falls back to identity alone when fields are unreadable.
    """
    role = safe_str(_get(message, "role")) or ""
    content = _get(message, "content")
    content_sig = content if isinstance(content, str) else repr(content)
    tool_call_id = safe_str(_get(message, "tool_call_id")) or ""
    calls = _get(message, "tool_calls")
    calls_sig = repr(calls) if calls is not None else ""
    return f"{id(message)}:{role}:{tool_call_id}:{content_sig}:{calls_sig}"


def _coerce_arguments(arguments: Any) -> dict[str, Any]:
    """Normalize tool-call arguments to a dict for the tool_call payload.

    AutoGen (OpenAI tool-call style) carries function arguments as a JSON string.
    Parse it when possible; otherwise wrap the raw value so the event still
    carries something useful and never crashes on malformed JSON.
    """
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return dict(arguments)
    if isinstance(arguments, str):
        import json

        try:
            parsed = json.loads(arguments)
        except (ValueError, TypeError):
            return {"raw": arguments}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": arguments}


__all__ = ["AutoGenAdapter"]
