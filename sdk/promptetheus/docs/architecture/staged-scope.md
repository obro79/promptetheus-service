# Staged Scope: State 0 → State 1 → State 2

The hackathon build is **State 0**: an MVP where the demo spine is real and everything else is allowed to be mocked. **State 1** is wiring up the mocks if we get time (or immediately after). **State 2** is the real Cloud product. This doc exists so that every mock we build in State 0 has a known upgrade path instead of becoming a rewrite.

## Design Rule: Mocks Behind Seams

Every mocked capability sits behind a small interface so wiring it up later is a swap, not a refactor:

| Seam | State 0 implementation | State 1 swap |
| --- | --- | --- |
| `FixAgent` | Canned plan + fake diff for the primary incident | Real LLM plan generation; real coding-agent dispatch |
| `PRProvider` | Generated PR preview card | Real PR via GitHub API / `gh` CLI against a demo repo |
| `RegressionRunner` | Simulated pass rates (12/12 fail → 10/12 pass) | Re-run the scripted agent N times with the fix toggled |
| `IncidentGrouper` | Deterministic grouping by seeded failure label | Real clustering over detector output (labels first, embeddings later) |
| `CloudWorkspace` | Static mock pages with fixture data | Real auth, tenancy, hosted storage (State 2) |

The console should consume these through their interfaces from day one — the UI must not know whether the implementation is mock or real.

## State 0 — Hackathon MVP

**Real (the demo spine must not be faked):**

- Python SDK with local transport and event helpers
- Playwright adapter with screen recording
- FastAPI ingestion server persisting to `.promptetheus/`, live SSE stream
- Side-by-side demo console with live trace stream and evidence chips
- Replay view with video synced to the timeline
- Rule-based failure detectors (goal mismatch, ignored warning, false success)
- LLM-generated fix brief with deterministic fallback for the primary session
- Seeded incident clusters (~87 sessions via the real ingestion API)

**Mocked (behind the seams above):**

- Fix-agent dispatch and PR creation (preview card + fake diff)
- Regression replay numbers (simulated before/after)
- Promptetheus Cloud (workspace, API keys, connected repo, Slack digest, retention/PII — all static UI)
- Incident clustering (label-based grouping of pre-labeled seed data)

## State 1 — Wire-Up (ordered by demo value per hour of work)

1. **Real regression replay.** Feature-flag the fix in the scripted agent (`verify_final_browser_state()` guard on/off), re-run the booking task 12 times against AcmeMeet, report real pass rates. Highest credibility gain; everything needed already exists in State 0.
2. **Real GitHub PR.** Create a demo repo containing the browser agent code; `PRProvider` opens a real branch + PR with the generated diff via the GitHub API. The PR preview card gets a real link.
3. **Real fix-agent dispatch.** Replace the canned plan with a real coding-agent invocation (Cursor/Codex/Claude CLI) fed by the fix-brief context bundle. Keep the canned path as fallback.
4. **Generic HTTP ingestion, documented.** Token auth on the ingestion endpoints plus a `curl` quickstart, making "any agent, any language" a tested claim rather than an aspiration (see integration surfaces in [technical-architecture.md](technical-architecture.md)).
5. **Real incident clustering.** Run detectors over all stored sessions and group by emitted labels instead of seed-time labels; embedding-based similarity later.
6. **LangChain/LangGraph adapter.** Callback handler that converts run-tree events into Promptetheus trace events — the interop play borrowed from the LangSmith pattern analysis.

Each item is independent; pick them off in order as time allows during or after the hackathon.

## State 2 — Promptetheus Cloud

Out of scope for the hackathon entirely; listed so State 0/1 decisions don't paint us into a corner.

- Hosted ingestion at `/v1/projects/:project_id/...` mirroring the local API shape (already specified in [sdk-architecture.md](../sdk-architecture.md)) — the SDK's `CloudTransport` stub targets this surface
- Real auth, workspaces, RBAC, retention, PII redaction
- Postgres + object storage replacing the file store (the file-layout contract maps cleanly: `metadata.json` → rows, `events.jsonl` → event table, artifacts → object store)
- Incident inbox with alerts and Slack digests
- MCP server exposing incident context to coding agents
- CI regression replay

**Carry-forward guarantees from State 0:** the event schema, the ingestion API shape, and the seams table above are the three things Cloud inherits. Everything else is replaceable.
