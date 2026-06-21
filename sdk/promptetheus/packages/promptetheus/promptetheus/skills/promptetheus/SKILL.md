---
name: promptetheus
description: Add, configure, debug, and verify Promptetheus SDK instrumentation for AI agents. Use when a user asks to instrument an agent, wrap an agent run, emit Promptetheus trace events, configure PROMPTETHEUS_API_URL or PROMPTETHEUS_API_KEY, debug SDK delivery/spool behavior, or connect agent runs to Promptetheus replay and MCP incident evidence.
---

# Promptetheus SDK Instrumentation

Use this skill to add Promptetheus observability to an AI-agent codebase. Promptetheus traces an agent run, streams structured events to the FastAPI gateway, and lets the console/MCP tools replay failures and inspect incident evidence.

## Workflow

1. Inspect the repo before editing.
   - Read local instructions such as `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, and README files.
   - Find the real agent entrypoint: CLI command, worker, test harness, web route, notebook, or scheduled job.
   - Identify the user goal, agent name, tool calls, model calls, browser actions, and final success/failure checks.

2. Import the SDK near the agent entrypoint:

   ```python
   import promptetheus as pt
   ```

3. Wrap the top-level agent run with `pt.trace.start(...)`.

   ```python
   import promptetheus as pt

   def run_agent(user_goal: str) -> str:
       with pt.trace.start(
           agent="my-agent",
           user_goal=user_goal,
           transport="auto",
           metadata={"entrypoint": "run_agent"},
       ) as session:
           session.user_message(user_goal)
           result = agent.run(user_goal)
           session.agent_message(str(result))
           session.goal_check(_goal_satisfied(user_goal, result))
           return result
   ```

4. Emit events at meaningful boundaries.
   - `session.user_message(text)` for user instructions or task goals.
   - `session.agent_message(text)` for agent responses, plans, or final answers.
   - `session.tool_call(tool_name, arguments, call_id=...)` before external tool use.
   - `session.tool_result(call_id, result=..., error=...)` after tool completion.
   - `session.browser_action(action, target, url=...)` for browser automation steps.
   - `session.dom_snapshot(url, visible_text, selected_values=..., warnings=...)` when browser state matters.
   - `session.goal_check(passed, mismatches=[...])` for the final correctness signal.
   - `session.error(exc, handled=True)` when an exception or recoverable failure matters.
   - `session.end("success")`, `session.end("failed")`, or let the context manager end the session automatically.

5. Configure delivery with the onboarding CLI.

   Hosted Promptetheus is the default. After installing the SDK, bootstrap a
   workspace/project key from the terminal:

   ```bash
   export PROMPTETHEUS_CONSOLE_TOKEN=...
   promptetheus init --workspace-name "My Team" --project-name "My Agent" --write-env .env
   ```

   `promptetheus init` calls the Promptetheus API, creates or reuses the
   workspace/project, generates a real project API key, stores only the key hash
   server-side, prints the raw `pt_live_...` key once, and writes
   `PROMPTETHEUS_API_KEY` to the requested env file when `--write-env` is used.
   Do not invent a local API key for hosted ingestion; it must be registered by
   the Promptetheus backend.

   If the user already has a project key, they can set it directly:

   ```bash
   export PROMPTETHEUS_API_KEY=pt_live_...
   python your_agent.py
   ```

   For local self-hosted development, bootstrap against the local FastAPI
   gateway with the default dev console token:

   ```bash
   promptetheus init --api-url http://127.0.0.1:4318 --console-token pt_console_token --write-env .env
   ```

   For self-hosted or local FastAPI with an existing key, add an endpoint
   override:

   ```bash
   export PROMPTETHEUS_API_URL=http://127.0.0.1:4318
   export PROMPTETHEUS_API_KEY=pt_dev_key
   python your_agent.py
   ```

   Use `transport="auto"` by default. With `PROMPTETHEUS_API_KEY` set, auto
   transport delivers to hosted Promptetheus unless `PROMPTETHEUS_API_URL`
   overrides it. Without an API key, auto transport safely spools locally. Use
   `transport="http"` only when an endpoint/API key are explicitly known and
   failing fast is desirable. Do not ask users for Supabase/Postgres connection
   strings in agent apps; SDK events should go to Promptetheus FastAPI
   ingestion, which writes to storage.

6. Validate the setup.
   - Run the repo's narrow tests for the instrumented path.
   - Run `promptetheus doctor` to inspect resolved config, gateway reachability, and spool state.
   - If delivery fails, inspect/replay the SDK spool with `promptetheus spool list` and `promptetheus spool replay`.

## Rules

- Do not write canonical trace/session/event files directly. Use the SDK and let failed delivery spool replay through FastAPI.
- Do not put secrets, raw credentials, cookies, or access tokens into event payloads. Prefer references, hashes, IDs, or redacted summaries.
- Keep instrumentation close to real behavior. Do not add fake success events that hide failed goals.
- Prefer one top-level trace per user-visible agent task.
- Preserve existing repo patterns and tests; Promptetheus should observe the agent, not rewrite its architecture.

## Common Patterns

### Tool Calls

```python
call_id = "search-1"
session.tool_call("search", {"query": query}, call_id=call_id)
try:
    result = search(query)
except Exception as exc:
    session.tool_result(call_id, error=str(exc))
    session.error(exc, handled=False)
    raise
else:
    session.tool_result(call_id, result={"count": len(result)})
```

### Browser Agents

```python
session.browser_action("click", "#checkout", url=page.url)
session.dom_snapshot(
    page.url,
    visible_text=page_text,
    selected_values={"day": selected_day},
    warnings=warnings,
)
session.goal_check(selected_day == requested_day, mismatches=["wrong day"])
```

### Tests

When adding tests, prefer SDK in-memory capture for unit-level assertions and HTTP delivery only for integration/E2E tests.

```python
from promptetheus.testing import capture_session

def test_agent_emits_goal_check():
    with capture_session(agent="test-agent", user_goal="book Tuesday") as cap:
        cap.session.user_message("book Tuesday")
        cap.session.goal_check(False, mismatches=["booked Wednesday"])

    assert "goal_check" in cap.event_types
```
