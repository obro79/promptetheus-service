# Competitive Landscape

## Summary

Promptetheus does not need to be alone in the market. The category is real precisely because LangSmith, Datadog, Langfuse, Phoenix, and others are investing in LLM/agent observability.

The risk is not competition. The risk is looking like a thinner clone of trace dashboards, eval tooling, or generic observability.

Promptetheus should position around:

```text
Screen-recorded agent replay + goal-state failure attribution + fix-agent PR workflow
```

That is narrower than generic LLM observability and more demoable than a dashboard.

## LangSmith

What LangSmith already does well:

- LLM application tracing
- Production metrics and dashboards
- Alerts
- Feedback and annotation
- Evaluation datasets and experiments
- Prompt engineering
- Integrations across common LLM frameworks
- LangSmith Engine for recurring issue detection and root-cause diagnosis

Why Promptetheus should not copy it:

- LangSmith is already strong at trace/eval workflows.
- A generic "trace viewer for agents" will look like a weaker LangSmith.

Promptetheus differentiation:

- Visual replay artifact for browser/action agents.
- Final goal-state comparison: original goal vs observed browser/app state.
- Critical failure step shown with screenshot/DOM/video evidence.
- Fix-agent handoff that opens or previews a PR.
- Regression replay as the closing loop.

## Datadog LLM Observability

What Datadog already does well:

- Monitor, troubleshoot, and evaluate LLM applications.
- Trace each application request.
- Monitor performance, cost, token usage, errors, quality, privacy, and safety.
- Topic/pattern clustering of production traffic.
- Sensitive-data scanning, redaction, prompt-injection detection.
- Anomaly insights across operational metrics and evaluations.
- Python SDK integrations with OpenAI, LangChain, Bedrock, Anthropic.
- Broader platform coverage: APM, logs, RUM, session replay, incident response, workflows, security, and Bits AI agents.

Why Promptetheus should not copy it:

- Datadog owns broad enterprise observability.
- Competing on dashboards, metrics, alerts, and generic production monitoring is a losing demo.

Promptetheus differentiation:

- Purpose-built for agent failure debugging rather than whole-stack monitoring.
- Replay artifact is attached to the exact agent run, not just frontend RUM.
- Failure detector reasons about task goal, DOM state, browser action, and "agent claimed success but goal failed."
- Cloud pitch focuses on agent incident-to-PR remediation, not just monitoring.

## Sentry

What Sentry already does well:

- Issue grouping and triage.
- Session Replay for web and mobile.
- Replays attached to issues.
- Breadcrumbs, tags, traces, screenshots, attachments, suspect commits, feature flags, and issue ownership.
- Issue tracker integrations and developer workflow hooks.
- MCP surface for exposing Sentry context to AI tools.

Why Promptetheus should not copy it:

- Sentry is already the default mental model for software error monitoring.
- "Sentry for agents" is useful shorthand, but not enough as a product.
- Sentry issues typically start from exceptions, crashes, performance regressions, or frontend user behavior. Agent failures can be silent: the action succeeds, the page returns 200, and the agent still violates the goal.

Promptetheus differentiation:

- Agent session replay, not just user session replay.
- Trace includes model messages, tool calls, browser actions, DOM snapshots, goal checks, and replay artifacts.
- Incidents group by agent failure mode: goal mismatch, ignored warning, false success claim, forbidden action, state persistence bug.
- Critical-step attribution explains where the agent went wrong.
- Connected repo and docs context lets a coding agent plan and open a PR.
- Regression replay verifies that the fix prevents the same class of agent failure.

Best framing:

> Sentry shows what broke in software. Promptetheus shows how an agent violated its task, packages the replay evidence, and routes it to a fix agent.

## Langfuse

What Langfuse already does well:

- Open-source LLM observability.
- Traces, sessions, observations.
- Prompt/completion visibility.
- Tool and retrieval steps.
- Token usage, latency, cost.
- Prompt management, evaluations, datasets, experiments.
- Self-hosting.
- Async batching so instrumentation does not block the app.

Why Promptetheus should not copy it:

- Langfuse is already a credible open-source tracing/evals platform.
- "Open-source Langfuse but for agents" is not sharp enough.

Promptetheus differentiation:

- Agent-environment replay, especially browser sessions.
- Goal-check events and failure evidence chips.
- Screen recording synced to trace events.
- Fix-agent PR workflow.

## Arize Phoenix

What Phoenix already does well:

- AI observability using OpenTelemetry-style tracing.
- Traces for LLM calls, tool execution, retrieval, and generation.
- Sessions for multi-turn conversations.
- Annotations and evaluations.
- Datasets and experiments.
- Local/self-hosted and Phoenix Cloud options.
- Strong educational story around "trace everything, measure what matters."

Why Promptetheus should not copy it:

- Phoenix already tells the story of tracing + evaluation for agent internals.
- A "Phoenix with a nicer UI" is not enough.

Promptetheus differentiation:

- Screen-recorded external environment replay.
- Goal-state verification, not only response quality.
- Incident-to-fix pipeline with coding-agent PR handoff.

## Positioning Map

```text
Generic tracing/evals
  LangSmith / Langfuse / Phoenix

Enterprise observability
  Datadog

Software issue replay and error triage
  Sentry

Promptetheus wedge
  Agent session replay + goal-state attribution + fix-agent PR workflow
```

## What To Say In The Demo

Do not say:

> We are LangSmith for agents.

Say:

> Existing tools show traces and metrics. Promptetheus shows the agent's actual run, detects where it violated the user's goal, and turns that failure into a PR-backed regression fix.

Or, if using the Sentry analogy:

> Think Sentry-style issue replay for AI agents, but the issue is not just an exception. It is an agent violating the user's goal. Promptetheus captures the run, identifies the bad step, and gives a coding agent the context to open a fix PR.

## Demo Implication

Populate the demo with data that competitors would normally show:

- Trace events
- Tool calls
- Cost/latency
- Failure labels
- Incident clustering

But make the memorable moment something competitors do not foreground:

- Screen recording replay
- DOM state vs user goal
- Critical step freeze-frame
- Fix button
- PR preview
- Before/after regression replay

That keeps us credible in the category without looking like a clone.
