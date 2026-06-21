import * as React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AnalysisResult,
  Incident,
  Project,
  TraceEvent,
  TraceSession,
} from "@/lib/types";
import { LogsDashboard } from "./logs-dashboard";

const mockReplace = vi.fn();
const mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => "/logs",
  useSearchParams: () => mockSearchParams,
}));

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

function renderDashboard(overrides?: Partial<React.ComponentProps<typeof LogsDashboard>>) {
  render(
    <LogsDashboard
      sessions={sessions}
      projects={[project]}
      incidents={incidents}
      eventsBySession={eventsBySession}
      analysesBySession={analysesBySession}
      {...overrides}
    />,
  );
}

function openRunTrace(runLabel: string) {
  const runsList = screen.getByLabelText("Runs list");
  fireEvent.click(within(runsList).getAllByText(runLabel)[0]);
}

beforeEach(() => {
  vi.useFakeTimers();
  mockReplace.mockClear();
  for (const key of [...mockSearchParams.keys()]) {
    mockSearchParams.delete(key);
  }
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("LogsDashboard", () => {
  it("shows logs navigation, runs table, and trace debugger by default", () => {
    renderDashboard();

    expect(screen.getByLabelText("Logs sections")).toBeInTheDocument();
    expect(screen.getByLabelText("Runs list")).toBeInTheDocument();
    expect(screen.getByLabelText("Trace waterfall")).toBeInTheDocument();
    expect(screen.getByLabelText("Run inspector")).toBeInTheDocument();
  });

  it("filters run rows with status pills and updates the selected trace", () => {
    renderDashboard();
    fireEvent.click(screen.getByRole("button", { name: "Failed only" }));

    const runsList = screen.getByLabelText("Runs list");

    expect(within(runsList).getAllByText("Book a demo at 2pm").length).toBeGreaterThan(0);
    expect(within(runsList).getAllByText("Answer order status").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Passed" }));

    expect(within(runsList).queryByText("Book a demo at 2pm")).not.toBeInTheDocument();
    expect(within(runsList).getAllByText("Answer order status").length).toBeGreaterThan(0);

    fireEvent.click(within(runsList).getByRole("button", { name: "Inspect run ses_passed" }));

    expect(screen.getByLabelText("Trace waterfall")).toBeInTheDocument();
    expect(screen.getAllByText("Order shipped").length).toBeGreaterThan(0);
  });

  it("expands and collapses trace nodes in the overlay", () => {
    renderDashboard();
    openRunTrace("Book a demo at 2pm");

    const trace = screen.getByLabelText("Trace waterfall");
    expect(within(trace).getByText("browser.click")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Collapse trace node"));
    expect(within(trace).queryByText("browser.click")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Expand trace node"));
    expect(within(trace).getByText("browser.click")).toBeInTheDocument();
  });

  it("shows section navigation and trace controls", () => {
    renderDashboard();

    expect(screen.getByRole("button", { name: "Agents" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Runs / Traces" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByLabelText("Expand trace tree")).toBeInTheDocument();
  });

  it("shows the promoted fix dispatch DAG above the runs list with proof receipts", () => {
    renderDashboard();

    const dag = screen.getByLabelText("Fix dispatch DAG");
    const proof = within(screen.getByLabelText("Fix DAG proof"));
    const runsList = screen.getByLabelText("Runs list");

    expect(screen.getByText("Dispatch running")).toBeInTheDocument();
    expect(screen.getByText("3s demo loop")).toBeInTheDocument();
    expect(proof.getByText("Read selected run")).toBeInTheDocument();
    expect(dag.compareDocumentPosition(runsList) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("auto-selects a failed run when selecting an agent without opening trace overlay", () => {
    renderDashboard();

    fireEvent.click(screen.getByLabelText("Logs Project"));

    expect(screen.getAllByText("Book a demo at 2pm").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Trace waterfall")).toBeInTheDocument();
  });

  it("filters runs to a selected agent and hides runs from other agents", () => {
    const project2: Project = {
      id: "prj_other",
      workspace_id: "ws_logs",
      name: "Other Agent",
      api_key_preview: "pk_live_other",
      connected_repo: null,
      retention_days: 14,
      created_at: "2026-06-18T00:00:00Z",
    };
    const sessionOther: TraceSession = {
      id: "ses_other",
      workspace_id: "ws_logs",
      project_id: "prj_other",
      user_goal: "Other agent task",
      agent: "other-agent@1.0.0",
      environment: "staging",
      status: "passed",
      tags: [],
      metadata: {},
      started_at: "2026-06-18T16:00:00Z",
      event_count: 1,
      duration_ms: 1000,
      incident_id: null,
    };

    render(
      <LogsDashboard
        sessions={[...sessions, sessionOther]}
        projects={[project, project2]}
        incidents={incidents}
        eventsBySession={{
          ...eventsBySession,
          ses_other: [event("ses_other", 0, "user_message", { content: "Other agent task" })],
        }}
        analysesBySession={analysesBySession}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Failed only" }));

    const runsList = screen.getByLabelText("Runs list");
    expect(within(runsList).getAllByText("Other agent task").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByLabelText("Logs Project"));

    expect(within(runsList).queryByText("Other agent task")).not.toBeInTheDocument();
  });

  it("hydrates selection from URL search params and opens trace overlay", () => {
    mockSearchParams.set("agent", "prj_logs");
    mockSearchParams.set("session", "ses_failed");
    mockSearchParams.set("seq", "2");

    renderDashboard();

    expect(screen.getByLabelText("Trace waterfall")).toBeInTheDocument();
    expect(screen.getAllByText("Book a demo at 2pm").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Selected 2am").length).toBeGreaterThan(0);
  });
});
