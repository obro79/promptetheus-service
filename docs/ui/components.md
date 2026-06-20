# Cluely-Style Promptetheus Component System

This document mirrors the dev-only `/design-system` route on the `of/cluley-ui-branch` branch. It
defines the visual foundation for rebuilding the Promptetheus demo and console in a light,
assistant-style interface inspired by Cluely's public homepage, using original Promptetheus code,
copy, and assets.

## Visual Direction

- Light-first canvas with pale blue gradient atmosphere.
- Rounded desktop-app windows and floating assistant panels.
- Soft borders, translucent white surfaces, and blue focus states.
- Large confident display type for demo moments.
- Compact mono text for events, code, and terminal streams.
- Status language always combines icon, color, and text.

Do not copy Cluely source code, proprietary images, logos, product names, or marketing copy.

## Tokens

Use existing semantic token names so current components can be restyled without changing their
interfaces.

| Role | Token | Usage |
| --- | --- | --- |
| Canvas | `--canvas` | Page background and top-level app frame |
| Panel | `--panel` | Cards, sheets, popovers, assistant bubbles |
| Elevated | `--elevated` | Inputs, hover states, low-emphasis chips |
| Foreground | `--foreground` | Primary text and dark terminal surfaces |
| Muted text | `--muted-foreground` | Body copy, captions, helper text |
| Primary signal | `--accent` | Main CTA, selected nav, active evidence |
| Primary soft | `--accent-muted` | Selected row backgrounds and badges |
| Success | `--success` | Passed replay, completed fix stage |
| Warning | `--warning` | Fix in progress, ambiguous evidence |
| Destructive | `--destructive` | Failed goal checks and critical incidents |
| Border | `--border` | Soft card, input, and window outlines |
| Ring | `--ring` | Keyboard focus and active command surfaces |

Typography uses `--font-sans` for product UI and `--font-mono` for trace data. Display headings use
the same sans stack with heavy weight and tight tracking.

## Primitives

### Buttons

Use the existing `Button` primitive.

- `default`: primary blue pill for one main action.
- `secondary`: white/translucent pill for neutral actions.
- `outline`: low-emphasis bordered action.
- `ghost`: inline low-emphasis navigation or row action.
- `destructive`: failure/escalation action only.
- `icon`: square hit area rendered as a round icon button with an aria label.

Example:

```tsx
<Button>
  <Wand2 />
  Dispatch fix
</Button>
```

### Inputs

Use `Input` for search, command, and text fields. Prefer leading lucide icons for search and command
fields. Inputs are rounded pills with panel backgrounds and visible focus rings.

Example:

```tsx
<div className="relative">
  <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2" />
  <Input className="pl-10" placeholder="goal mismatch, refund, browser warning" />
</div>
```

### Cards

Use `Card` for bounded component groups and local settings. Use the `surface` class for custom
panels that need assistant-window styling.

Card patterns:

- Basic card: neutral grouped content.
- Agent card: top agent state, main surface, attached terminal stream.
- Evidence card: highlighted event with type, sequence, and replay context.
- Metric card: high-contrast value with explicit label.
- Assistant panel: conversational bubbles plus command input.

Avoid stacking decorative cards inside decorative cards. Nested surfaces are allowed when the inner
surface is part of a repeated component, such as an agent terminal strip.

## Demo Components

### Three-Agent Card

Each demo card has three zones:

1. Header with agent name, modality icon, and fixture/status chip.
2. Agent surface showing the visible task failure.
3. Attached terminal stream with the latest 3-5 events.

Required states:

- Pre-instrumentation failed run.
- Instrumentation overlay.
- Instrumented rerun with events.
- Captured incident.
- Passed state for the browser agent after fix.

### Terminal Stream Strip

Terminal strips are compact, dark, and mono.

```text
[browser] browser_action click li[data-time='02:00']
[browser] dom_snapshot warning: did you mean 2:00 PM?
[browser] agent_message "Booked 2pm Pacific"
[detect] goal_check failed: selected 02:00
```

Rules:

- Keep streams attached to their agent card.
- Show only recent rows.
- Highlight one evidence row when detection fires.
- Preserve tabular event rhythm with mono text.

### Instrumentation Code Block

Use a dark code panel with no syntax-highlighting dependency.

```python
uv add promptetheus

import promptetheus as pt

@pt.observe("acmemeet-browser-agent")
def run_agent(task):
    return agent.run(task)
```

### Incident Row

Incident rows should be compact and scannable:

- Severity icon.
- Incident title.
- One-line evidence summary.
- Severity/status chip.

### Fix Pipeline

Render fix dispatch as a three-step progression:

1. Bundle: root cause and diff packaged.
2. Patch: fix agent output ready.
3. Replay: regression proves the corrected behavior.

Each step uses an icon, label, and short detail. Passed state uses `--success`; in-progress uses
`--warning`.

## Navigation Samples

The `/design-system` route includes these navigation references:

- Top pill nav with selected foreground pill.
- Compact command/search field.
- Round icon command button.
- Light floating app header.

Use these patterns for the future demo shell before repainting the full console navigation.

## State Language

| State | Icon examples | Color |
| --- | --- | --- |
| Running | `Radio`, `Activity` | `--accent` |
| Observed | `Activity`, `Sparkles` | `--accent` |
| Failed | `XCircle`, `AlertTriangle` | `--destructive` |
| Fixing | `Wand2`, `Loader2` | `--warning` |
| Passed | `CheckCircle2`, `ShieldCheck` | `--success` |

Color is never the only signal. Include text and an icon for every state badge or row.

## Acceptance Checklist

- `/design-system` renders all typography, color, button, input, card, demo, navigation, and state
  samples.
- The page is still blocked in production with `notFound()`.
- Shared primitives keep keyboard focus rings.
- No behavior, API, schema, or data-loading code changes are required for this pass.
- The design system can be used to rebuild `/demo` without inventing new visual decisions.
