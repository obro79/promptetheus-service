# Adapter parity matrix (P10.10)

Event types emitted by each integration adapter vs hand-instrumented `Session` helpers.

| Event type | Session helper | LangChain | LangGraph | OpenAI | Anthropic | Playwright |
| --- | --- | --- | --- | --- | --- | --- |
| `user_message` | yes | via chain | via graph | — | — | — |
| `agent_message` | yes | via LLM out | via graph | — | — | — |
| `tool_call` | yes | yes | yes | yes | yes | — |
| `tool_result` | yes | yes | yes | yes | yes | — |
| `llm_call` | yes | yes | yes | yes | yes | — |
| `browser_action` | yes | — | — | — | — | yes |
| `dom_snapshot` | yes | — | — | — | — | yes |
| `screenshot` | yes | — | — | — | — | yes |
| `replay_artifact` | yes | — | — | — | — | yes |
| `goal_check` | yes | — | — | — | — | yes |
| `session_end` | yes | yes | yes | yes | yes | yes |
| `state_change` | yes | span markers | span markers | — | — | — |
| `error` | yes | on failure | on failure | on failure | on failure | — |

**Notes**

- All adapters stamp the same envelope: `type`, `session_id`, `timestamp`, `seq`, `idempotency_key`, `payload`.
- LangSmith export is **deferred** (P10.3).
- Driven tests: `tests/adapters/test_langchain_driven.py`, `tests/adapters/test_langchain_adapter_parity.py`.
