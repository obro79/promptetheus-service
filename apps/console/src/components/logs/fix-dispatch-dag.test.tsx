import * as React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AnalysisResult,
  HealReport,
  Incident,
  Project,
  TraceEvent,
  TraceSession,
} from "@/lib/types";
import { FixDispatchDag } from "./fix-dispatch-dag";
import { projectFixDispatchDag } from "./fix-dispatch-dag-model";
import type { LogRun } from "./model";

const project: Project = {
  id: "prj_logs",
  workspace_id: "ws_logs",
  name: "Logs Project",
  api_key_preview: "pk_live_test",
  connected_repo: null,
  retention_days: 14,
  created_at: "2026-06-18T00:00:00Z",
};

const session: TraceSession = {
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
};

const analysis: AnalysisResult = {
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
};

const incident: Incident = {
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
};

const event: TraceEvent = {
  type: "goal_check",
  session_id: session.id,
  timestamp: "2026-06-18T16:45:00Z",
  seq: 2,
  idempotency_key: "ses_failed-2",
  t_offset_ms: 2000,
  payload: { passed: false, mismatches: ["Selected 2am"] },
};

function run(overrides: Partial<LogRun> = {}): LogRun {
  return {
    analysis,
    confidence: 0.9,
    errorPreview: "Selected 2am",
    events: [event],
    feedbackCount: 1,
    incident,
    inputPreview: "Book a demo at 2pm",
    latencyMs: 9000,
    outputPreview: "Booked 2am",
    project,
    session,
    totalTokens: 120,
    ...overrides,
  };
}

function report(overrides: Partial<HealReport> = {}): HealReport {
  return {
    attempts: 1,
    incident_id: incident.id,
    orchestrator: "in_process",
    pr: {
      branch: "promptetheus/inc_failed-fix",
      changed_files: ["agents/browser.py"],
      fallback: false,
      pr_url: "https://github.com/acme/repo/pull/12",
      title: "Fix browser timezone mismatch",
    },
    reason: null,
    source: "fix_agent",
    status: "pr_opened",
    trail: [
      {
        attempt: 1,
        critique: { approved: true, confidence: 0.9, reason: "Evidence matches." },
        diagnosis: "Timezone mismatch before confirmation.",
        eval: {
          after_fail: 0,
          before_fail: 1,
          cases: [
            {
              after_passed: true,
              assertion: "Books requested time",
              before_passed: false,
              case_id: "case_1",
              confidence: 0.88,
              reason: "After output satisfies assertion.",
            },
          ],
          fallback: false,
          meaningful: true,
          note: null,
          passed: true,
        },
        kind: "heal_attempt",
        passed: true,
        regression: { after_fail: 0, after_pass: 1, before_fail: 1 },
        runner: "deterministic",
      },
    ],
    workflow_run_id: null,
    warm_start: null,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("projectFixDispatchDag", () => {
  it("projects an idle incident into a ready DAG", () => {
    const projection = projectFixDispatchDag({ incident, phase: "idle" });

    expect(projection.mode).toBe("idle");
    expect(projection.nodes.find((node) => node.id === "read_logs")?.status).toBe("complete");
    expect(projection.nodes.find((node) => node.id === "plan_fix")?.status).toBe("pending");
  });

  it("projects a live opened PR into a merge-ready DAG", () => {
    const projection = projectFixDispatchDag({
      incident,
      phase: "pr_opened",
      report: report(),
    });

    expect(projection.mode).toBe("live");
    expect(projection.prUrl).toBe("https://github.com/acme/repo/pull/12");
    expect(projection.nodes.find((node) => node.id === "merge_github")?.status).toBe("ready");
  });

  it("marks escalated dispatches as blocked at the eval gate", () => {
    const projection = projectFixDispatchDag({
      incident,
      phase: "escalated",
      report: report({ reason: "Eval did not flip", status: "escalated", pr: null }),
    });

    expect(projection.mode).toBe("blocked");
    expect(projection.detail).toBe("Eval did not flip");
    expect(projection.nodes.find((node) => node.id === "run_evals")?.status).toBe("blocked");
  });

  it("distinguishes fallback PR previews from real merge-ready PRs", () => {
    const projection = projectFixDispatchDag({
      incident,
      phase: "pr_opened",
      report: report({ pr: { fallback: true, pr_url: null, title: "Preview" } }),
    });

    expect(projection.prPreview).toBe(true);
    expect(projection.nodes.find((node) => node.id === "open_pr")?.status).toBe("preview");
    expect(projection.nodes.find((node) => node.id === "merge_github")?.status).toBe("blocked");
  });

  it("projects API-unavailable demo mode as a preview-only path", () => {
    const projection = projectFixDispatchDag({ incident, phase: "demo" });

    expect(projection.mode).toBe("demo");
    expect(projection.prPreview).toBe(true);
    expect(projection.nodes.find((node) => node.id === "open_pr")?.status).toBe("preview");
  });

  it("projects the completed demo path into the merge PR state", () => {
    const projection = projectFixDispatchDag({ incident, phase: "demo_complete" });

    expect(projection.mode).toBe("demo");
    expect(projection.headline).toBe("Merge-ready PR path");
    expect(projection.nodes.find((node) => node.id === "merge_github")?.status).toBe("ready");
  });
});

describe("FixDispatchDag", () => {
  it("disables dispatch when the selected run has no incident", () => {
    render(<FixDispatchDag run={run({ incident: undefined, session: { ...session, incident_id: null } })} />);

    expect(screen.getByText("No incident attached")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dispatch fix unavailable" })).toBeDisabled();
  });

  it("shows no-incident evidence in the prominent proof panel", () => {
    render(
      <FixDispatchDag
        layout="prominent"
        run={run({ incident: undefined, session: { ...session, incident_id: null } })}
      />,
    );

    const proof = within(screen.getByLabelText("Fix DAG proof"));
    expect(proof.getByText("No incident available")).toBeInTheDocument();
    expect(proof.getByText("ses_failed")).toBeInTheDocument();
  });

  it("auto-runs the prominent demo DAG through merge PR", async () => {
    vi.useFakeTimers();
    render(<FixDispatchDag autoDemo layout="prominent" run={run()} />);

    expect(screen.getByText("Dispatch running")).toBeInTheDocument();
    expect(screen.getByText("3s demo loop")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Fix DAG proof")).getByText("Read selected run")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    expect(within(screen.getByLabelText("Fix DAG proof")).getByText("Plan fix from incident")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    expect(within(screen.getByLabelText("Fix DAG proof")).getByText("Dispatch fix agent")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(9000);
    });

    expect(screen.getByText("Merge-ready PR path")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Fix DAG proof")).getByText("Merge blocked until real PR")).toBeInTheDocument();
    expect(screen.getAllByText("Merge PR").length).toBeGreaterThan(0);
  });

  it("advances a successful dispatch and shows the GitHub PR link", async () => {
    vi.useFakeTimers();
    const dispatchHeal = vi.fn().mockResolvedValue(report());
    render(<FixDispatchDag layout="prominent" run={run()} dispatchHeal={dispatchHeal} />);

    fireEvent.click(screen.getByRole("button", { name: "Dispatch fix for selected run" }));

    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(2200);
    });

    expect(dispatchHeal).toHaveBeenCalledWith(incident.id);
    expect(screen.getByText("PR ready for GitHub")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open PR in GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/acme/repo/pull/12",
    );

    const proof = within(screen.getByLabelText("Fix DAG proof"));
    expect(proof.getByText("Merge in GitHub")).toBeInTheDocument();
    expect(proof.getByText("real PR")).toBeInTheDocument();

    fireEvent.click(screen.getAllByText("Open PR")[0]);
    const prProof = within(screen.getByLabelText("Fix DAG proof"));
    expect(prProof.getByText("Changed files: agents/browser.py")).toBeInTheDocument();
    expect(prProof.getByText("real GitHub PR")).toBeInTheDocument();

    fireEvent.click(screen.getAllByText("Run evals")[0]);
    const evalProof = within(screen.getByLabelText("Fix DAG proof"));
    expect(evalProof.getByText("Assertion: Books requested time")).toBeInTheDocument();
  });

  it("falls back to demo mode when the API is unavailable", async () => {
    vi.useFakeTimers();
    const dispatchHeal = vi.fn().mockResolvedValue(null);
    render(<FixDispatchDag run={run()} dispatchHeal={dispatchHeal} />);

    fireEvent.click(screen.getByRole("button", { name: "Dispatch fix for selected run" }));

    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(2200);
    });

    expect(screen.getByText("Demo dispatch complete")).toBeInTheDocument();
    expect(screen.getByText(/Connect the Promptetheus API to open a real PR/)).toBeInTheDocument();
  });

  it("marks dispatch failures as errors", async () => {
    vi.useFakeTimers();
    const dispatchHeal = vi.fn().mockRejectedValue(new Error("API exploded"));
    render(<FixDispatchDag run={run()} dispatchHeal={dispatchHeal} />);

    fireEvent.click(screen.getByRole("button", { name: "Dispatch fix for selected run" }));

    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(2200);
    });

    expect(screen.getByText("Dispatch failed")).toBeInTheDocument();
    expect(screen.getByText("API exploded")).toBeInTheDocument();
  });

  it("shows escalated dispatch evidence in the proof panel", async () => {
    vi.useFakeTimers();
    const dispatchHeal = vi.fn().mockResolvedValue(
      report({
        pr: null,
        reason: "Eval did not flip",
        status: "escalated",
        trail: [
          {
            ...report().trail[0],
            eval: {
              ...report().trail[0].eval!,
              passed: false,
              after_fail: 1,
              cases: [
                {
                  ...report().trail[0].eval!.cases[0],
                  after_passed: false,
                  reason: "Selected time still wrong.",
                },
              ],
            },
            passed: false,
          },
        ],
      }),
    );
    render(<FixDispatchDag layout="prominent" run={run()} dispatchHeal={dispatchHeal} />);

    fireEvent.click(screen.getByRole("button", { name: "Dispatch fix for selected run" }));

    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(2200);
    });

    const proof = within(screen.getByLabelText("Fix DAG proof"));
    expect(screen.getByText("Eval gate blocked dispatch")).toBeInTheDocument();
    expect(proof.getByText("Run eval gate")).toBeInTheDocument();
    expect(proof.getByText("failed")).toBeInTheDocument();
    expect(proof.getByText("Reason: Eval did not flip")).toBeInTheDocument();
  });
});
