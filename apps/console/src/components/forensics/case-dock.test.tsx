import * as React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AnalysisResult, TraceEvent, TraceSession } from "@/lib/types";
import { CaseDock } from "./case-dock";

const session = {
  id: "ses_test",
  workspace_id: "ws",
  project_id: "prj",
  user_goal: "Cancel the order",
  agent: "voice-agent",
  environment: "test",
  status: "failed",
  tags: ["voice"],
  metadata: { modality: "voice" },
  started_at: "2026-06-18T00:00:00Z",
  event_count: 2,
  duration_ms: 2000,
  incident_id: null,
} satisfies TraceSession;

const events = [
  { type: "user_message", seq: 0, t_offset_ms: 0, payload: { content: "Cancel it" } },
  { type: "goal_check", seq: 1, t_offset_ms: 2000, payload: { passed: false, mismatches: ["Cancellation tool was never called"] } },
].map((event) => ({ session_id: session.id, timestamp: session.started_at, idempotency_key: `event-${event.seq}`, ...event })) as TraceEvent[];

const analysis = {
  root_cause: "The correction was ignored",
  labels: ["false_success_claim"],
  detections: [{ label: "false_success_claim", confidence: 0.9, evidence_refs: [0, 1], critical_step_seq: 1 }],
} as AnalysisResult;

describe("CaseDock", () => {
  afterEach(() => vi.useRealTimers());

  it("turns failure evidence into a regression test state", async () => {
    vi.useFakeTimers();
    render(<CaseDock session={session} events={events} analysis={analysis} evidence={[0, 1]} criticalSeq={1} onSelect={() => undefined} />);

    fireEvent.click(screen.getByRole("button", { name: "Generate regression test" }));
    expect(screen.getByText("Generating regression…")).toBeInTheDocument();

    await act(async () => vi.advanceTimersByTime(900));
    expect(screen.getByText("Regression test ready")).toBeInTheDocument();
  });
});
