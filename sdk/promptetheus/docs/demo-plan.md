# Demo Plan

## Three-Minute Pitch

### 0:00-0:25 Problem

AI agents fail silently. The browser action succeeds, the page returns 200, and the agent says it is done, even though it clicked the wrong option or ignored a warning.

### 0:25-0:45 Product

Promptetheus is debugging infrastructure for AI agents.

Core loop:

```text
Observe -> Detect -> Replay -> Attribute -> Fix -> Prevent
```

### 0:45-2:35 Live Demo

Use a purpose-built side-by-side console.

Left side: the browser agent works inside AcmeMeet.

Right side: Promptetheus streams trace events, extracts evidence, saves a screen recording artifact, and lights up failure analysis.

Task:

> Book a demo for next Tuesday at 2pm Pacific, but stop at the confirmation screen.

Failure:

1. Agent opens the booking page.
2. Agent clicks Tuesday.
3. Agent selects 2:00 AM instead of 2:00 PM.
4. Page shows a timezone warning.
5. Agent ignores the warning.
6. Agent claims success.
7. Goal check fails.

Promptetheus shows:

- Screen recording replay artifact
- Trace timeline
- DOM snapshot
- Screenshot
- Warning text
- Original goal
- Observed final state
- Failure labels: `browser_goal_mismatch`, `ignored_ui_warning`, `false_success_claim`
- Critical step: selected `2:00 AM` when the goal required `2:00 PM`
- Root cause: no final browser-state verification before success

### 2:35-3:00 Close

Click **Fix**.

Promptetheus packages the incident for a coding agent:

- Reproduction trace
- Screen recording
- Screenshot and DOM evidence
- Root-cause hypothesis
- Files likely to change
- Regression test to add

Show a PR preview:

- Adds final browser-state verification before `complete_task`
- Adds warning-text guard
- Adds regression test for Tuesday 2pm Pacific

Then show before/after replay:

- Before fix: `12/12` booking runs fail goal verification.
- After fix: `10/12` pass, `2` pause for user confirmation.

## Demo UI

The demo UI should not be a generic analytics dashboard. It should be a purpose-built debugging console.

Required panels:

- Live browser-agent pane
- Live trace stream
- Screen recording replay
- Evidence chips
- Failure analysis panel
- Critical-step freeze-frame
- Root cause and confidence
- Fix button
- PR preview
- Regression replay result

## Demo Close

> Promptetheus works for any agent. Browser agents make the failure visible, but the same debugging loop applies to support agents, coding agents, research agents, and ops agents.
