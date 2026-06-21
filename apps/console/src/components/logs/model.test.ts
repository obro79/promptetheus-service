import { describe, expect, it } from "vitest";

import type {
  AnalysisResult,
  Incident,
  Project,
  TraceEvent,
  TraceSession,
} from "@/lib/types";
import {
  buildLogRuns,
  buildTraceTree,
  deriveLogMetrics,
  filterLogRuns,
  flattenTraceTree,
  sortLogRuns,
} from "./model";

const project: Project = {
  id: "prj_test",
  workspace_id: "ws_test",
  name: "Test Project",
  api_key_preview: "pk_test_1234",
  connected_repo: null,
  retention_days: 14,
  created_at: "2026-06-18T00:00:00Z",
};

function session(id: string, status: TraceSession["status"], tags: string[] = []): TraceSession {
  return {
    id,
    workspace_id: "ws_test",
    project_id: project.id,
    user_goal: id === "ses_failed" ? "Book the wrong time" : "Answer the user",
    agent: "agent@test",
    environment: "production",
    status,
    tags,
    metadata: {},
    started_at: id === "ses_failed" ? "2026-06-18T16:55:00Z" : "2026-06-18T14:00:00Z",
    event_count: 3,
    duration_ms: id === "ses_failed" ? 12000 : 3000,
    incident_id: id === "ses_failed" ? "inc_test" : null,
  };
}

function event(
  sessionId: string,
  seq: number,
  type: TraceEvent["type"],
  payload: Record<string, unknown>,
  extra: Partial<TraceEvent> = {},
): TraceEvent {
  return {
    type,
    session_id: sessionId,
    timestamp: "2026-06-18T16:55:00Z",
    seq,
    idempotency_key: `${sessionId}-${seq}`,
    t_offset_ms: seq * 1000,
    payload,
    ...extra,
  };
}

const analysis: AnalysisResult = {
  session_id: "ses_failed",
  detections: [
    {
      label: "goal_mismatch",
      confidence: 0.91,
      evidence_refs: [1, 2],
      critical_step_seq: 1,
    },
  ],
  labels: ["goal_mismatch"],
  critical_step_seq: 1,
  confidence: 0.91,
  root_cause: "The selected time did not match the user goal.",
  fallback: false,
  created_at: "2026-06-18T16:56:00Z",
};

const incident: Incident = {
  id: "inc_test",
  workspace_id: "ws_test",
  project_id: project.id,
  label: "goal_mismatch",
  title: "Wrong time selected",
  severity: "critical",
  status: "open",
  representative_session_id: "ses_failed",
  owner_id: null,
  session_ids: ["ses_failed"],
  critical_step_seq: 1,
  root_cause: "The selected time did not match the user goal.",
  fingerprint: "goal_mismatch:test",
  labels: ["goal_mismatch"],
  pr_url: null,
  fix_agent_result: null,
  created_at: "2026-06-18T16:56:00Z",
  updated_at: "2026-06-18T16:56:00Z",
};

describe("logs model", () => {
  it("derives run previews, tokens, latency, and aggregate metrics", () => {
    const runs = buildLogRuns({
      sessions: [session("ses_failed", "failed", ["booking"]), session("ses_ok", "passed")],
      projects: [project],
      incidents: [incident],
      eventsBySession: {
        ses_failed: [
          event("ses_failed", 0, "user_message", { content: "Book Tuesday at 2pm" }),
          event("ses_failed", 1, "llm_call", {
            model: "test-model",
            input_tokens: 100,
            output_tokens: 20,
            latency_ms: 700,
          }),
          event("ses_failed", 2, "goal_check", {
            passed: false,
            mismatches: ["Selected 2am"],
          }),
        ],
        ses_ok: [
          event("ses_ok", 0, "user_message", { content: "Answer the user" }),
          event("ses_ok", 1, "agent_message", { content: "Done" }),
        ],
      },
      analysesBySession: { ses_failed: analysis },
    });

    expect(runs[0]).toMatchObject({
      inputPreview: "Book Tuesday at 2pm",
      errorPreview: "Selected 2am",
      totalTokens: 120,
      latencyMs: 700,
    });
    expect(deriveLogMetrics(runs)).toMatchObject({
      totalRuns: 2,
      failedRuns: 1,
      totalTokens: 120,
    });
  });

  it("filters and sorts runs by the dashboard controls", () => {
    const runs = buildLogRuns({
      sessions: [session("ses_failed", "failed", ["booking"]), session("ses_ok", "passed", ["support"])],
      projects: [project],
      incidents: [incident],
      eventsBySession: {
        ses_failed: [event("ses_failed", 0, "user_message", { content: "Book Tuesday" })],
        ses_ok: [event("ses_ok", 0, "user_message", { content: "Refund policy" })],
      },
      analysesBySession: { ses_failed: analysis },
    });

    const filtered = filterLogRuns(runs, {
      query: "book",
      status: "all",
      failedOnly: true,
      timeRange: "7d",
      projects: [],
      environments: ["production"],
      tags: ["booking"],
    });

    expect(filtered.map((run) => run.session.id)).toEqual(["ses_failed"]);
    expect(sortLogRuns(runs, "latency", "asc")[0].session.id).toBe("ses_ok");
  });

  it("builds expandable trace trees from explicit span parents", () => {
    const events = [
      event("ses_tree", 0, "user_message", { content: "Hi" }, { span_id: "root" }),
      event("ses_tree", 1, "llm_call", { model: "test" }, { span_id: "child", parent_id: "root" }),
      event("ses_tree", 2, "tool_call", { tool_name: "search" }, { span_id: "leaf", parent_id: "child" }),
    ];
    const tree = buildTraceTree(events);
    expect(tree[0].children[0].children[0].event.seq).toBe(2);
    expect(flattenTraceTree(tree, new Set(["root"])).map(({ node }) => node.event.seq)).toEqual([0, 1]);
    expect(flattenTraceTree(tree, new Set(["root", "child"])).map(({ node }) => node.event.seq)).toEqual([0, 1, 2]);
  });
});
