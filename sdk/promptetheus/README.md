# promptetheus

Promptetheus is debugging infrastructure for AI agents: a Python SDK, local
replay tooling, hosted trace delivery, and MCP evidence access for coding
agents that need to fix failing agent runs.

## What You Get

- One trace per user-visible agent task.
- Decorators for top-level agent runs, tool calls, and nested spans.
- Typed events for user messages, agent messages, tool calls, browser actions,
  DOM snapshots, screenshots, LLM calls, retrieval, metrics, errors, scores,
  and final goal checks.
- Durable delivery that never crashes the host agent. If HTTP delivery is not
  configured or fails, events spool locally and can be replayed later.
- Local CLI tools for doctor checks, spool inspection, session replay, diffing,
  and failure fingerprints.
- Hosted MCP config snippets for read-only incident evidence scoped to a
  workspace and Supabase project.

## Install

For a normal project, install from PyPI:

```bash
pip install promptetheus
promptetheus version
```

Create or configure a hosted project key:

```bash
export PROMPTETHEUS_CONSOLE_TOKEN=...
promptetheus init \
  --workspace-name "Acme" \
  --project-name "Browser Agent" \
  --write-env .env
source .env
promptetheus doctor
```

For local self-hosted development:

```bash
promptetheus init \
  --api-url http://127.0.0.1:4318 \
  --console-token pt_console_token \
  --write-env .env
source .env
```

For contributor work from this repository:

```bash
pip install -e packages/promptetheus
promptetheus version
```

With `transport="auto"`, the SDK sends to the configured API when
`PROMPTETHEUS_API_KEY` is present. Without a key, it writes to the local spool
so the instrumented agent keeps running.

## Observe With Decorators

Use decorators when you want instrumentation to sit directly on agent and tool
functions:

```python
import promptetheus as pt

@pt.tool
def search_calendar(day: str) -> list[str]:
    return ["Tuesday 2pm", "Tuesday 3pm"]

@pt.traced("choose-slot")
def choose_slot(slots: list[str]) -> str:
    return "Wednesday 2pm"

@pt.observe(
    agent="calendar-agent",
    user_goal="Book Tuesday at 2pm",
    transport="auto",  # use "spool" to force local JSONL while trying this
)
def run_agent(goal: str) -> str:
    pt.current().user_message(goal)
    slots = search_calendar("Tuesday")
    selected = choose_slot(slots)
    pt.current().agent_message(f"Booked {selected}")
    pt.current().goal_check(
        False,
        mismatches=["selected Wednesday, not Tuesday"],
    )
    return selected

run_agent("Book Tuesday at 2pm")
```

What each decorator does:

- `@pt.observe(...)` starts one trace/session around the top-level run.
- `@pt.tool` records `tool_call` and `tool_result` events inside the current
  session.
- `@pt.traced("name")` adds a nested span to the replay tree without starting a
  separate session.
- `pt.current()` returns the active session so the agent can record user
  messages, agent messages, goal checks, errors, metrics, and other events.

`goal_check(False)` is visible in replay, fingerprints, and tail sampling. If a
failed goal should also make the process fail, record the goal check and then
raise an exception so the terminal `session_end` status is `failed`:

```python
if not selected.startswith("Tuesday"):
    pt.current().goal_check(False, mismatches=["selected Wednesday"])
    raise RuntimeError("agent selected the wrong day")
```

## What You Can See

When no API key is configured, `transport="auto"` writes local JSONL. While
learning, you can also pass `transport="spool"` to force local output. After a
local or spooled run, list sessions:

```bash
promptetheus sessions
```

Example output:

```text
  01KVMZ4T7V2SN61ZWG1XTDBK47: 11 event(s)
```

Replay the timeline:

```bash
promptetheus replay 01KVMZ4T7V2SN61ZWG1XTDBK47
```

Example output:

```text
[0] state_change name='session_started'
[1] tool_call tool_name='run_agent'
[2] user_message content='Book Tuesday at 2pm'
[3] tool_call tool_name='search_calendar'
[4] tool_result call_id='190a6438979141f5ac11b2e1b2ee29a0'
[5] state_change name='span_start'
[6] state_change name='span_end'
[7] agent_message content='Booked Wednesday 2pm'
[8] goal_check passed=False
[9] tool_result call_id='a78566297e0a4a309d5ce44cefe0d836'
[10] session_end status='completed'
```

Replay the run tree:

```bash
promptetheus replay 01KVMZ4T7V2SN61ZWG1XTDBK47 --tree
```

Example output:

```text
[0] state_change name='session_started'
[1] tool_call tool_name='run_agent'
[2] user_message content='Book Tuesday at 2pm'
[3] tool_call tool_name='search_calendar'
[4] tool_result call_id='190a6438979141f5ac11b2e1b2ee29a0'
[7] agent_message content='Booked Wednesday 2pm'
[8] goal_check passed=False
[9] tool_result call_id='a78566297e0a4a309d5ce44cefe0d836'
[10] session_end status='completed'
choose-slot span=span_163a8380174647e98bfe1f3fff9e15b9 duration_ms=0.0
```

Generate a failure fingerprint:

```bash
promptetheus fingerprint 01KVMZ4T7V2SN61ZWG1XTDBK47
```

Example output:

```text
8ae0f41220d0  goal mismatch: selected wednesday, not tuesday
  - goal:selected wednesday, not tuesday
```

Inspect the local delivery spool:

```bash
promptetheus spool list
```

Example output:

```text
Spool: .promptetheus/spool
  pending : 11 event(s) across 1 session file(s), 4082 bytes
  dead    : 0 event(s) across 0 file(s), 0 bytes
    01KVMZ4T7V2SN61ZWG1XTDBK47: 11 pending
```

The raw spool is JSONL. Each line is an event envelope:

```json
{
  "type": "tool_call",
  "session_id": "01KVMZ4T7V2SN61ZWG1XTDBK47",
  "seq": 1,
  "idempotency_key": "01KVMZ4T7V2SN61ZWG1XTDBK47:29c5eff0:1",
  "payload": {
    "tool_name": "run_agent",
    "call_id": "a78566297e0a4a309d5ce44cefe0d836",
    "arguments": {
      "args": "('Book Tuesday at 2pm',)",
      "kwargs": "{}"
    }
  }
}
```

## Manual Trace API

Use `pt.trace.start(...)` when you control the run boundary and want explicit
event calls instead of decorators:

```python
import promptetheus as pt

with pt.trace.start(
    agent="demo-agent",
    user_goal="Book a meeting for Tuesday",
    transport="auto",
) as session:
    session.user_message("Please book the small room for Tuesday at 2pm")
    session.tool_call("calendar.search", {"day": "Tuesday"}, call_id="calendar-1")
    session.tool_result("calendar-1", result={"available": ["2pm", "3pm"]})
    session.agent_message("Booking confirmed for Wednesday at 2pm")
    session.goal_check(False, mismatches=["booked Wednesday, not Tuesday"])
# session_end is emitted automatically; transport flush runs on exit
```

## Public SDK API

The package exposes these primary entry points:

```python
import promptetheus as pt

pt.trace.start(...)
pt.start(...)
pt.observe(...)
pt.tool
pt.traced(...)
pt.current()
pt.Session
pt.AsyncSession
pt.AgentRuntime
```

Common session helpers:

```python
session.user_message("Book Tuesday at 2pm Pacific")
session.agent_message("I found availability")
session.tool_call("browser.click", {"selector": "#checkout"}, call_id="click-1")
session.tool_result("click-1", result={"ok": True})
session.retrieval("refund policy", documents=[{"id": "doc-1", "score": 0.91}])
session.browser_action("click", "#checkout", url=page.url)
session.dom_snapshot(page.url, visible_text, selected_values={"day": "Tuesday"})
session.screenshot(page.screenshot())
session.replay_artifact("trace.webm", artifact_type="screen_recording", event_time_map={})
session.llm_call("gpt-5", input_tokens=100, output_tokens=40, latency_ms=900)
session.score("goal_match", 0.2, comment="Selected the wrong day")
session.metric("steps", 12, unit="count")
session.error(RuntimeError("calendar API timeout"), handled=True)
session.goal_check(False, mismatches=["selected Wednesday"])
session.end("failed")
session.flush(timeout=2)
```

Every helper writes a schema-valid event envelope with `type`, `session_id`,
`timestamp`, `seq`, `idempotency_key`, and `payload`. Use `metadata` for safe,
low-cardinality context. Do not put raw secrets, cookies, tokens, or
credentials into event payloads.

## Async Agents

Use `AsyncSession` when the top-level agent run is async:

```python
from promptetheus import AsyncSession

async with AsyncSession(agent="voice-agent", user_goal="Summarize the call") as session:
    session.user_message("Summarize this call")
    async with session.aspan("transcribe"):
        session.metric("audio_seconds", 42, unit="seconds")
    session.goal_check(True)
```

## Browser Agents

Browser agents should record the user goal, critical browser actions, the final
DOM state, and an explicit goal check:

```python
session.browser_action("click", "#confirm", url=page.url)
session.dom_snapshot(
    page.url,
    visible_text=await page.locator("body").inner_text(),
    selected_values={"day": "Wednesday", "time": "2pm"},
    warnings=["Timezone changed from Pacific to Eastern"],
)
session.goal_check(
    False,
    mismatches=["booked Wednesday", "timezone warning visible"],
)
```

This is the path that lets Promptetheus replay a failure and produce fix-agent
evidence instead of just storing generic logs.

## Framework Adapters

Adapters are optional and imported lazily. Install only the extra you need:

```bash
pip install "promptetheus[openai]"
pip install "promptetheus[anthropic]"
pip install "promptetheus[langchain]"
pip install "promptetheus[playwright]"
```

Available adapter exports:

```python
from promptetheus.adapters import (
    AnthropicAdapter,
    AutoGenAdapter,
    CrewAIAdapter,
    DSPyAdapter,
    HaystackAdapter,
    LangGraphAdapter,
    LiteLLMAdapter,
    LlamaIndexAdapter,
    OpenAIAdapter,
    OpenTelemetryBridge,
    PlaywrightAdapter,
    PromptetheusCallbackHandler,
    PydanticAIAdapter,
)
```

Use adapters when a framework already emits structured callbacks. Keep custom
instrumentation close to the real run boundary when the framework does not.

## Runtime Coordination

`AgentRuntime` is a best-effort client for live, service-backed coordination.
It is separate from durable trace storage and never raises into host code when
the service is unavailable:

```python
from promptetheus import AgentRuntime

runtime = AgentRuntime(session.session_id)
runtime.remember("hypothesis", {"summary": "auth header may be missing"})
hint = runtime.before_tool_call("pytest", command="pytest tests/server")

result = run_tests()
runtime.after_tool_call(
    "pytest",
    command="pytest tests/server",
    status="failed" if result.failed else "succeeded",
    error=result.error,
)
runtime.heartbeat(phase="investigating", current_file="tests/server/test_mcp.py")
next_hint = runtime.next_hint()
```

## CLI Workflows

In a fresh install, local gateway and MCP commands need their extras:

```bash
pip install "promptetheus[server,mcp]"
```

```bash
promptetheus dev                     # boot local FastAPI ingestion on :4318
promptetheus doctor                  # config, reachability, spool summary
promptetheus spool list              # pending local delivery files
promptetheus spool replay            # retry pending delivery through the API
promptetheus sessions                # list locally spooled sessions
promptetheus replay <session-id>     # print a flat timeline
promptetheus replay <session-id> --tree
promptetheus diff <baseline> <candidate>
promptetheus fingerprint <session-id>
promptetheus import exported-session.json
```

`spool purge` deletes local spool files. Use it only when you are sure the data
is no longer needed.

## MCP Evidence Access

Generate hosted MCP client config without mutating global client files:

```bash
promptetheus mcp install \
  --client codex \
  --workspace acme \
  --project-ref abcdefghijklmnopqrst
```

Supported clients are `codex`, `claude`, and `cursor`. The generated config
uses a stdio bridge to hosted Promptetheus MCP and defaults to read-only,
project-scoped Supabase evidence. SDK clients and MCP client config should not
receive Supabase service-role keys.

For local stdio development:

```bash
promptetheus mcp
```

## Developing In This Repo

The SDK lives under `packages/promptetheus/promptetheus`. Tests live at the
repository root under `tests`.

Useful commands:

```bash
uv run --project packages/promptetheus --extra dev pytest tests/sdk -q
uv run --project packages/promptetheus --extra dev pytest tests/cli -q
uv run --project packages/promptetheus --extra dev --extra server --extra mcp pytest tests/server/test_mcp.py -q
uv run --project packages/promptetheus --extra dev mypy
```

Docs to read next:

- [SDK architecture](docs/sdk-architecture.md)
- [MCP design](docs/mcp.md)
- [Demo plan](docs/demo-plan.md)
- [Reference examples](docs/reference/reference-examples.md)
- [Technical architecture](docs/architecture/technical-architecture.md)

## Security And Privacy

- Promptetheus project keys identify Promptetheus projects. They are not
  Supabase service-role keys.
- The hosted service owns Supabase credentials and scopes evidence reads by
  workspace/project.
- Use `redact="default"` or a custom redactor for sensitive payloads.
- Store prompt/message references instead of raw large or sensitive LLM payloads
  when possible.
- The SDK should observe agents, not rewrite their architecture or hide failed
  goals.

**Status:** Stable `2.0.1` SDK for hosted/self-hosted Promptetheus trace
delivery.
