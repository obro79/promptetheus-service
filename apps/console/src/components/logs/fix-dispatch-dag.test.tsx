import * as React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AgentPrDispatchResult,
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
    artifacts: [],
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

function agentPrDispatch(overrides: Partial<AgentPrDispatchResult> = {}): AgentPrDispatchResult {
  return {
    evalGate: {
      afterFail: null,
      assertion: "Fix must resolve: The selected time was wrong.",
      beforeFail: 1,
      caseCount: 3,
      confidence: null,
      note: "Eval set is attached to Devin. The PR is not ready until Devin runs it and reports the result.",
      status: "pending",
    },
    orchestrator: "local_orkes",
    pullRequests: [
      {
        agentType: "browser",
        branch: null,
        devinPrRequested: true,
        devinReviewRequested: false,
        externalId: "devin-21",
        kind: "devin_session",
        number: null,
        title: "Devin: Add Promptetheus browser agent replay guard",
        url: "https://app.devin.ai/sessions/devin-21",
      },
      {
        agentType: "chat",
        branch: null,
        devinPrRequested: true,
        devinReviewRequested: false,
        externalId: "devin-22",
        kind: "devin_session",
        number: null,
        title: "Devin: Add Promptetheus chat agent recovery marker",
        url: "https://app.devin.ai/sessions/devin-22",
      },
      {
        agentType: "voice",
        branch: null,
        devinPrRequested: true,
        devinReviewRequested: false,
        externalId: "devin-23",
        kind: "devin_session",
        number: null,
        title: "Devin: Add Promptetheus voice agent interruption guard",
        url: "https://app.devin.ai/sessions/devin-23",
      },
    ],
    sentryProof: {
      configured: true,
      detail: "Sentry DSN is configured; live backend heal/eval spans can be correlated with this workflow id.",
      traceId: "promptetheus-inc-failed-123",
    },
    status: "devin_dispatched",
    targetRepo: "obro79/demo-agents",
    workflowRunId: "local-orkes-inc-failed-123",
    workflowStages: [
      {
        detail: "Incident trace, root cause, and replay assertion packaged for the workflow.",
        id: "build_eval_set",
        label: "Build eval set",
        status: "passed",
      },
      {
        detail: "3/3 Devin agent tasks created.",
        id: "dispatch_devin",
        label: "Dispatch Devin",
        status: "passed",
      },
      {
        detail: "Waiting for Devin to open a candidate PR from the dispatched task.",
        id: "wait_for_pr",
        label: "Wait for PR",
        status: "running",
      },
      {
        detail: "Eval set is attached to Devin. The PR is not ready until Devin runs it and reports the result.",
        id: "run_evals",
        label: "Run evals",
        status: "pending",
      },
    ],
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

  it("projects Devin dispatches into a waiting-for-PR state", () => {
    const projection = projectFixDispatchDag({
      incident,
      phase: "waiting_for_pr",
    });

    expect(projection.headline).toBe("Waiting for Devin PR");
    expect(projection.prPreview).toBe(false);
    expect(projection.nodes.find((node) => node.id === "open_pr")?.status).toBe("active");
    expect(projection.nodes.find((node) => node.id === "merge_github")?.status).toBe("pending");
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
    expect(screen.getByText("30s demo loop")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Fix DAG proof")).getByText("Read selected run")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(6000);
    });

    expect(within(screen.getByLabelText("Fix DAG proof")).getByText("Plan fix from incident")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(6000);
    });

    expect(within(screen.getByLabelText("Fix DAG proof")).getByText("Dispatch fix agent")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(18000);
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
      vi.advanceTimersByTime(30000);
    });

    expect(dispatchHeal).toHaveBeenCalledWith(incident.id, expect.objectContaining({ incident }));
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

  it("waits for the real Devin-opened PR while keeping session links visible", async () => {
    vi.useFakeTimers();
    const dispatchHeal = vi.fn().mockResolvedValue(agentPrDispatch());
    render(
      <FixDispatchDag
        dispatchHeal={dispatchHeal}
        dispatchLabel="Ask Devin to open PRs"
        layout="prominent"
        run={run()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Dispatch fix for selected run" }));

    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(30000);
    });

    expect(dispatchHeal).toHaveBeenCalledWith(incident.id, expect.objectContaining({ incident }));
    expect(screen.getByText("Waiting for Devin PR")).toBeInTheDocument();
    expect(screen.getByText("Devin agents are fixing the project")).toBeInTheDocument();
    expect(screen.getByText("PR detection active")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check for Devin PR" })).toBeInTheDocument();
    expect(screen.queryByText("PR ready for GitHub")).not.toBeInTheDocument();

    const proof = within(screen.getByLabelText("Fix DAG proof"));
    expect(proof.getByText("Devin is creating the PR")).toBeInTheDocument();
    expect(proof.getByText("Local Orkes workflow")).toBeInTheDocument();
    expect(proof.getByText("local-orkes-inc-failed-123")).toBeInTheDocument();
    expect(proof.getByText("Eval gate")).toBeInTheDocument();
    expect(proof.getByText("pending")).toBeInTheDocument();
    expect(proof.getByText("Fix must resolve: The selected time was wrong.")).toBeInTheDocument();
    expect(proof.getByText(/Sentry: configured/)).toBeInTheDocument();
    expect(proof.getByText("Dispatch Devin")).toBeInTheDocument();
    expect(proof.getByText("Devin sessions")).toBeInTheDocument();
    expect(proof.getByText("obro79/demo-agents")).toBeInTheDocument();
    expect(proof.getByRole("link", { name: /Session devin-21/ })).toHaveAttribute(
      "href",
      "https://app.devin.ai/sessions/devin-21",
    );
    expect(proof.getByRole("link", { name: /Session devin-22/ })).toHaveAttribute(
      "href",
      "https://app.devin.ai/sessions/devin-22",
    );
    expect(proof.getByRole("link", { name: /Session devin-23/ })).toHaveAttribute(
      "href",
      "https://app.devin.ai/sessions/devin-23",
    );
    expect(proof.getAllByText("Devin creating PR")).toHaveLength(3);
    expect(screen.queryByRole("link", { name: "Open PR in GitHub" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Expand DAG to fullscreen" }));
    const fullscreen = within(screen.getByRole("dialog"));
    expect(fullscreen.getByText("Devin agents are fixing the project")).toBeInTheDocument();
    expect(
      fullscreen.getByText("Devin is working through the prebuilt PR handoff steps"),
    ).toBeInTheDocument();
    expect(fullscreen.getByRole("button", { name: "Check for Devin PR" })).toBeInTheDocument();
  });

  it("polls Devin PR status and promotes only when a real GitHub PR is found", async () => {
    vi.useFakeTimers();
    const dispatchHeal = vi.fn().mockResolvedValue(agentPrDispatch());
    const trackedResult = agentPrDispatch({
      pullRequests: [
        {
          ...agentPrDispatch().pullRequests[0],
          openedPrBranch: "devin/browser-agent-fix",
          openedPrNumber: 77,
          openedPrTitle: "Add Promptetheus browser agent replay guard",
          openedPrUrl: "https://github.com/obro79/demo-agents/pull/77",
          prDetectedAt: "2026-06-21T12:00:00Z",
        },
        ...agentPrDispatch().pullRequests.slice(1),
      ],
      status: "pr_opened",
      trackingStatus: "tracking",
      workflowStages: agentPrDispatch().workflowStages?.map((stage) =>
        stage.id === "wait_for_pr"
          ? { ...stage, detail: "1/3 Devin-opened GitHub PR detected.", status: "passed" }
          : stage,
      ),
    });
    const checkDispatchStatus = vi.fn().mockResolvedValue(trackedResult);
    render(
      <FixDispatchDag
        checkDispatchStatus={checkDispatchStatus}
        dispatchHeal={dispatchHeal}
        dispatchLabel="Ask Devin to open PRs"
        layout="prominent"
        run={run()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Dispatch fix for selected run" }));

    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(30000);
    });

    expect(screen.getByText("Waiting for Devin PR")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
    });

    expect(checkDispatchStatus).toHaveBeenCalledWith({
      dispatchResult: expect.objectContaining({ status: "devin_dispatched" }),
      incidentId: incident.id,
      sessionId: session.id,
    });
    expect(screen.getByText("PR ready for GitHub")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open PR in GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/obro79/demo-agents/pull/77",
    );
    const proof = within(screen.getByLabelText("Fix DAG proof"));
    expect(proof.getByRole("link", { name: /PR #77/ })).toHaveAttribute(
      "href",
      "https://github.com/obro79/demo-agents/pull/77",
    );
    expect(proof.getByRole("link", { name: /Session devin-21/ })).toHaveAttribute(
      "href",
      "https://app.devin.ai/sessions/devin-21",
    );
    expect(proof.getByText("PR opened")).toBeInTheDocument();
  });

  it("falls back to demo mode when the API is unavailable", async () => {
    vi.useFakeTimers();
    const dispatchHeal = vi.fn().mockResolvedValue(null);
    render(<FixDispatchDag run={run()} dispatchHeal={dispatchHeal} />);

    fireEvent.click(screen.getByRole("button", { name: "Dispatch fix for selected run" }));

    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(30000);
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
      vi.advanceTimersByTime(30000);
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
      vi.advanceTimersByTime(30000);
    });

    const proof = within(screen.getByLabelText("Fix DAG proof"));
    expect(screen.getByText("Eval gate blocked dispatch")).toBeInTheDocument();
    expect(proof.getByText("Run eval gate")).toBeInTheDocument();
    expect(proof.getByText("failed")).toBeInTheDocument();
    expect(proof.getByText("Reason: Eval did not flip")).toBeInTheDocument();
  });
});
