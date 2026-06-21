# Demo Data Plan

## Goal

Populate the demo with enough realistic data that Promptetheus feels like production infrastructure, while keeping the live story focused on one memorable failure.

The main demo should show one live browser-agent failure. Supporting data should make it feel like the failure is part of a larger production pattern.

## Primary Live Session

Session:

- `sess_live_booking_goal_mismatch`

User goal:

> Book a demo for next Tuesday at 2pm Pacific, but stop at the confirmation screen.

Failure:

- Agent selects Tuesday correctly.
- Agent selects `2:00 AM` instead of `2:00 PM`.
- Page shows timezone warning.
- Agent ignores warning.
- Agent claims success.
- Goal check fails.

Artifacts:

- Screen recording: `artifacts/sess_live_booking_goal_mismatch/replay.webm`
- Screenshots:
  - `01-booking-page.png`
  - `02-time-selected-2am.png`
  - `03-warning-visible.png`
  - `04-agent-claims-success.png`
- DOM snapshots:
  - selected day
  - selected time
  - selected timezone
  - visible warning text
- Trace events:
  - user message
  - browser open
  - click day
  - select time
  - DOM snapshot
  - screenshot
  - agent message
  - goal check

Failure labels:

- `browser_goal_mismatch`
- `ignored_ui_warning`
- `false_success_claim`

Critical step:

> Agent selected `2:00 AM` while user requested `2:00 PM`.

## Supporting Incident Clusters

Seed 5 clusters:

1. Browser goal mismatch — 27 sessions
2. Ignored UI warning — 21 sessions
3. False success claim — 18 sessions
4. Wrong element clicked — 14 sessions
5. Forbidden action attempted — 7 sessions

Each cluster should have:

- title
- severity
- affected sessions
- representative replay
- root-cause hypothesis
- suggested fix
- regression status

## Session Examples

### Browser Goal Mismatch

User asks for Tuesday 2pm Pacific. Agent selects Tuesday 2am Eastern.

### Ignored UI Warning

User asks for refundable ticket. Agent selects a ticket where the page says "All sales final."

### False Success Claim

Agent says the form was submitted successfully, but the page still shows required-field errors.

### Wrong Element Clicked

Agent clicks "Delete workspace" instead of "Disable integration" because both buttons are near each other.

### Forbidden Action Attempted

User says "do not purchase." Agent advances to payment confirmation.

## Console Data

Live trace stream should include:

- event timestamp
- event type
- source: SDK, browser adapter, detector, fix-agent
- short label
- raw payload preview
- evidence flag when event contributes to failure analysis

Evidence chips:

- Goal mismatch
- Ignored warning
- False success
- Timezone mismatch
- Forbidden action risk

## Fix Bundle

For the primary incident, generate:

- root cause
- final goal-verification rule
- warning-text guard
- DOM assertion
- regression test
- fix-agent task brief
- PR preview

PR preview:

Files changed:

- `agent/complete_task.py`
- `agent/goal_verification.py`
- `tests/test_browser_goal_verification.py`

Diff summary:

- Adds `verify_final_browser_state()`
- Blocks completion when warning text is visible
- Compares selected DOM values against `user_goal`
- Adds regression for Tuesday 2pm Pacific

## Before/After Regression Replay

Before fix:

- 12/12 booking runs fail goal verification.

After fix:

- 10/12 pass.
- 2/12 pause for user confirmation because the UI is ambiguous.

Show this as a bar or compact table. Do not overbuild analytics.

## Devpost Video Population

The video should show:

1. Browser agent run.
2. Promptetheus trace stream filling in.
3. Screen recording saved.
4. Failure analysis lights up.
5. Replay jumps to exact failure timestamp.
6. Fix button creates PR preview.
7. Regression replay improves pass rate.

Do not spend video time on generic dashboards.
