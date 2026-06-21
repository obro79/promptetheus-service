import * as React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type {
  AnalysisResult,
  Incident,
  Project,
  TraceEvent,
  TraceSession,
} from "@/lib/types";
import { LogsDashboard } from "./logs-dashboard";

const project: Project = {
  id: "prj_logs",
  workspace_id: "ws_logs",
  name: "Logs Project",
  api_key_preview: "pk_live_test",
  connected_repo: null,
  retention_days: 14,
  created_at: "2026-06-18T00:00:00Z",
};

const sessions: TraceSession[] = [
  {
    id: "ses_failed",
    workspace_id: "ws_logs",
    project_id: project.id,
    user_goal: "Book a demo at 2pm",
    agent: "browser-agent@test",
    environment: "production",
    status: "failed",
    tags: ["booking"],
    metadata: {},
    started_at: "2026-06-18T16:45:00Z",
    event_count: 3,
    duration_ms: 9000,
    incident_id: "inc_failed",
  },
  {
    id: "ses_passed",
    workspace_id: "ws_logs",
    project_id: project.id,
    user_goal: "Answer order status",
    agent: "support-agent@test",
    environment: "production",
    status: "passed",
    tags: ["support"],
    metadata: {},
    started_at: "2026-06-18T15:45:00Z",
    event_count: 2,
    duration_ms: 3000,
    incident_id: null,
  },
];

function event(
  sessionId: string,
  seq: number,
  type: TraceEvent["type"],
  payload: Record<string, unknown>,
): TraceEvent {
  return {
    type,
    session_id: sessionId,
    timestamp: "2026-06-18T16:45:00Z",
    seq,
    idempotency_key: `${sessionId}-${seq}`,
    t_offset_ms: seq * 1000,
    payload,
  };
}

const analysesBySession: Record<string, AnalysisResult> = {
  ses_failed: {
    session_id: "ses_failed",
    detections: [
      {
        label: "goal_mismatch",
        confidence: 0.9,
        evidence_refs: [1, 2],
        critical_step_seq: 1,
      },
    ],
    labels: ["goal_mismatch"],
    critical_step_seq: 1,
    confidence: 0.9,
    root_cause: "The selected time was wrong.",
    fallback: false,
    created_at: "2026-06-18T16:46:00Z",
  },
};

const incidents: Incident[] = [
  {
    id: "inc_failed",
    workspace_id: "ws_logs",
    project_id: project.id,
    label: "goal_mismatch",
    title: "Wrong time selected",
    severity: "critical",
    status: "open",
    representative_session_id: "ses_failed",
    owner_id: null,
    session_ids: ["ses_failed"],
    critical_step_seq: 1,
    root_cause: "The selected time was wrong.",
    fingerprint: "goal_mismatch:test",
    labels: ["goal_mismatch"],
    pr_url: null,
    fix_agent_result: null,
    created_at: "2026-06-18T16:46:00Z",
    updated_at: "2026-06-18T16:46:00Z",
  },
];

const eventsBySession: Record<string, TraceEvent[]> = {
  ses_failed: [
    event("ses_failed", 0, "user_message", { content: "Book a demo at 2pm" }),
    event("ses_failed", 1, "tool_call", { tool_name: "browser.click" }),
    event("ses_failed", 2, "goal_check", {
      passed: false,
      mismatches: ["Selected 2am"],
    }),
  ],
  ses_passed: [
    event("ses_passed", 0, "user_message", { content: "Answer order status" }),
    event("ses_passed", 1, "agent_message", { content: "Order shipped" }),
  ],
};

function renderDashboard() {
  render(
    <LogsDashboard
      sessions={sessions}
      projects={[project]}
      incidents={incidents}
      eventsBySession={eventsBySession}
      analysesBySession={analysesBySession}
    />,
  );
}

afterEach(() => cleanup());

describe("LogsDashboard", () => {
  it("filters run rows and keeps the selected run inspector visible", () => {
    renderDashboard();

    expect(screen.getAllByText("Book a demo at 2pm").length).toBeGreaterThan(0);
    expect(screen.queryByText("Answer order status")).not.toBeInTheDocument();
    expect(screen.getAllByText("Selected 2am").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Passed" }));
    fireEvent.click(screen.getByRole("button", { name: "Failed only" }));

    expect(screen.getAllByText("Answer order status").length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByText("Answer order status")[0]);
    expect(screen.getAllByText("Order shipped").length).toBeGreaterThan(0);
  });

  it("expands and collapses trace nodes", () => {
    renderDashboard();

    const trace = screen.getByLabelText("Trace waterfall");
    expect(within(trace).getByText("browser.click")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Collapse trace node"));
    expect(within(trace).queryByText("browser.click")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Expand trace node"));
    expect(within(trace).getByText("browser.click")).toBeInTheDocument();
  });
});
