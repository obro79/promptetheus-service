# Reference Examples

## Failure Labels

- `browser_goal_mismatch`
- `ignored_ui_warning`
- `false_success_claim`
- `wrong_element_clicked`
- `forbidden_action_attempted`
- `user_frustration`
- `unresolved_intent`
- `repeated_question`
- `wrong_tool_used`
- `hallucinated_policy`
- `retrieval_mismatch`
- `escalation_missed`
- `prompt_injection_attempt`
- `agent_loop`
- `state_persistence_bug`
- `tool_error`

## Browser Demo Incident

Title:

> Browser goal mismatch

Summary:

Browser agents completed booking flows while violating user constraints like time, timezone, refundability, or "do not purchase."

Likely root cause:

The agent declares success without validating the final page state against the original user goal.

Recommended fix:

Add a final goal-verification step that checks selected DOM values, visible warning text, and forbidden actions before completion.

Regression test:

Given a user asks for Tuesday at 2pm Pacific, when the page contains Tuesday at 2am Eastern or a timezone warning, the browser agent must not declare success.

## Fix-Agent Task Brief

```md
Title: Add final goal verification for browser agents

Observed failure:
The browser agent selected Tuesday at 2:00 AM Eastern while the user requested Tuesday at 2:00 PM Pacific.

Evidence:
- Screen recording timestamp: 00:38
- DOM selectedValues.time = "2:00 AM"
- DOM selectedValues.timezone = "Eastern"
- Warning text: "Selected time may not match requested timezone"
- Agent final message: "Done. Your demo is booked for Tuesday."

Likely root cause:
The agent calls complete_task without checking final DOM state against the original user goal.

Expected fix:
- Add final browser-state verification before complete_task.
- Block success if visible warning text exists.
- Add regression test for Tuesday 2pm Pacific.
```

## Guard Rule

```yaml
name: Verify final browser state before success
when:
  agent_type: browser
  action: complete_task
require:
  - final_dom_matches_user_goal
  - no_visible_warning_text
  - no_forbidden_action_taken
action: block_success_and_request_correction
```

## Devpost Copy

Promptetheus is an open-source Python debugging SDK, local replay console, and hosted incident workspace for AI agents. Developers add the SDK to their agent app, stream trace events locally, and get failure detection, session replay, root-cause analysis, fix-agent handoff, and regression replay.

The demo instruments a browser agent. Promptetheus captures tool calls, browser actions, DOM snapshots, screenshots, and a screen recording artifact. When the agent silently chooses the wrong time and claims success, Promptetheus detects the mismatch, replays the exact failure, generates a fix brief, and previews a PR that adds a regression test.

The open-source SDK is the adoption wedge. Promptetheus Cloud is the paid product for teams running agents in production: team workspaces, production trace storage, cross-session search, incident clustering, alerts, CI regression replay, connected repo onboarding, fix-agent PRs, GitHub/Linear/Jira integrations, RBAC, audit logs, PII redaction, retention controls, and Slack incident digests.

## Cloud Flow

```text
Production Agent
  └── Promptetheus SDK
        ├── local mode: writes .promptetheus traces and artifacts
        └── cloud mode: POSTs events and replay artifacts to Promptetheus Cloud

Promptetheus Cloud
  ├── stores traces and screen recordings
  ├── clusters incidents over time
  ├── alerts the team when failures spike
  ├── searches across sessions
  ├── packages evidence for a coding agent
  ├── exposes incident context through MCP/context bundle
  ├── opens a PR against the connected repo
  └── reruns regression replay against the fix
```

## Cloud V1 Feature Set

Must have:

- Team workspace
- Project + environment setup
- Project API keys
- Cloud trace ingestion
- Replay artifact storage
- Incident inbox
- Session replay with screen recording and trace
- Failure labels and severity
- Slack digest or alert mock
- Connected repo object
- Fix-agent brief and PR preview
- Regression replay result

Should have:

- Search across sessions
- Incident status and owner
- GitHub/Linear/Jira issue creation
- Basic PII redaction
- Retention controls
- CI regression replay mock

Not V1:

- Full SSO/SAML
- SOC2 certification
- VPC deployment
- PagerDuty/on-call policy engine
- Autonomous code changes without human PR review
