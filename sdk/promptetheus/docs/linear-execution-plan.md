# Linear Execution Plan

## Principle

With Cursor/Codex agents running in parallel, the limiting factor is not raw implementation capacity. The limiting factor is demo coherence.

Build many surfaces, but make every surface support one story:

```text
Agent failure -> replay evidence -> incident -> fix-agent PR -> regression replay
```

If a feature does not make that story clearer, defer it or mock it.

## Workstream Map

### Workstream A: Demo Spine

Owner goal: make the 3-minute demo work end to end.

Issues:

1. Build AcmeMeet fake browser task page.
2. Build scripted browser-agent failure runner.
3. Record/save replay artifact for the failed run.
4. Stream trace events into Promptetheus console.
5. Build side-by-side demo console layout.
6. Add failure evidence chips.
7. Add critical-step freeze-frame.
8. Add root-cause summary panel.
9. Add fix button and PR preview.
10. Add before/after regression replay panel.

Acceptance:

- A judge can watch the browser agent fail and understand the failure without explanation.
- The fix button produces a credible PR preview.
- Regression replay shows the issue improved.

### Workstream B: Python SDK

Owner goal: make the product feel like a real dev tool.

Issues:

1. Scaffold `promptetheus` Python package.
2. Implement `trace.start()`.
3. Implement local `.promptetheus/` transport.
4. Implement session event helpers.
5. Implement replay artifact helper.
6. Implement Playwright adapter.
7. Add sample browser-agent instrumentation.
8. Add README install snippet.

Acceptance:

- Demo code imports `promptetheus`.
- Trace events are written to `.promptetheus/`.
- Replay artifacts are linked to sessions.

### Workstream C: Local Ingestion & Storage

Owner goal: make trace data reliable for the demo.

Issues:

1. Define trace event schema.
2. Define session metadata schema.
3. Implement local trace loader.
4. Implement artifact loader.
5. Implement analysis result storage.
6. Add seed data generator for 25-50 sessions.
7. Add deterministic incident grouping.

Acceptance:

- Console can load both live and seeded sessions.
- Seeded data shows 5 incident clusters.
- Artifacts resolve consistently.

### Workstream D: Promptetheus Cloud Mock

Owner goal: show the monetizable product without building real Cloud.

Issues:

1. Build workspace/project page mock.
2. Build project API key setup mock.
3. Build connected repo card.
4. Build incident inbox.
5. Build incident detail page.
6. Build Slack digest mock.
7. Build retention/PII settings mock.
8. Build "Cloud mode" badge and copy.

Acceptance:

- Demo can show local SDK adoption and then Cloud team workflow.
- Cloud surface looks credible enough for Devpost screenshots.
- No real auth/multi-tenancy required.

### Workstream E: Fix-Agent PR Workflow

Owner goal: make the "agent fixes agent issues" moment land.

Issues:

1. Define fix-agent context bundle.
2. Build MCP/context-bundle mock panel.
3. Generate fix-agent plan from incident.
4. Generate PR preview card.
5. Generate fake diff.
6. Link PR preview back to incident.
7. Mark incident as addressed by PR.
8. Show regression replay after PR.

Acceptance:

- The incident detail has a clear "Dispatch fix agent" action.
- The output looks like a reviewable engineering PR, not generic advice.
- The PR links back to replay evidence and regression result.

### Workstream F: Visual Polish

Owner goal: make the project feel like a top-tier dev tool.

Issues:

1. Design visual system.
2. Build demo console shell.
3. Build timeline component.
4. Build screen replay player frame.
5. Build evidence chip animations.
6. Build incident cards.
7. Build PR preview UI.
8. Build Devpost screenshots.
9. Record backup demo video.

Acceptance:

- First viewport communicates the product without explanation.
- Text never overflows.
- Demo screens are clean, dense, and developer-native.

## Linear Labels

Use:

- `spine`
- `sdk`
- `storage`
- `cloud-mock`
- `fix-agent`
- `ui-polish`
- `demo-critical`
- `nice-to-have`
- `blocked`

## Priority Rules

P0:

- Anything required for the live 3-minute demo spine.
- Anything that blocks the screen recording replay or PR preview.

P1:

- Anything that makes the Cloud monetization story visible.
- Anything needed for Devpost screenshots.

P2:

- Nice-to-have integrations, settings, search, and polish.

## Parallelization Rules

Do not let agents overlap on the same files if avoidable.

Suggested boundaries:

- SDK agent owns `packages/python-sdk/`.
- Storage/API agent owns `apps/web/src/server/` or equivalent.
- Demo UI agent owns `apps/web/src/app/demo/`.
- Cloud mock agent owns `apps/web/src/app/cloud/`.
- Fix-agent UI owns `apps/web/src/app/incidents/`.
- Design/polish agent owns shared components after core flows stabilize.

## Demo Gate

Before adding more features, the team must be able to run:

```text
1. Start demo.
2. Browser agent fails.
3. Replay artifact appears.
4. Failure evidence lights up.
5. Incident detail opens.
6. Fix-agent PR preview appears.
7. Regression replay shows improvement.
```

If this flow breaks, all agents pause feature work and fix the spine.
