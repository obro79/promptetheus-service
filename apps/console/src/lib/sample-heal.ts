/**
 * Representative heal report used when the live Promptetheus API isn't
 * connected. It mirrors the real `POST /api/incidents/{id}/heal` response shape
 * (gates + eval before→after + PR) so the verification flow stays visible
 * without a backend. The live report takes over whenever the API is configured.
 */
import { getIncident } from "./data";
import type { HealReport } from "./types";

export function buildSampleHealReport(incidentId: string): HealReport {
  const incident = getIncident(incidentId);
  const label = incident?.label ?? "goal_mismatch";
  const title = incident?.title ?? "Agent goal violation";
  const rootCause =
    incident?.root_cause ??
    "The agent claimed success while the terminal goal check failed.";
  const affected = incident?.session_ids.length ?? 3;
  const branch = `promptetheus/${incidentId}-fix`;

  return {
    status: "pr_opened",
    incident_id: incidentId,
    attempts: 1,
    source: "browserbase",
    orchestrator: "agentspan",
    workflow_run_id: "wf_8f21c4",
    reason: null,
    trail: [
      {
        kind: "attempt",
        attempt: 1,
        runner: "claude",
        diagnosis: `Root cause: ${rootCause} Adding a post-action goal-verification guard so the agent re-checks the goal before claiming success.`,
        critique: {
          approved: true,
          confidence: 0.93,
          reason:
            "The patch inserts a goal-verification guard that directly addresses the detected root cause.",
        },
        regression: {
          before_fail: affected,
          after_pass: affected,
          after_fail: 0,
        },
        eval: {
          passed: true,
          meaningful: true,
          fallback: false,
          before_fail: 1,
          after_fail: 0,
          note: null,
          cases: [
            {
              case_id: `${incidentId}:goal_check`,
              assertion:
                "The agent's final answer/action must satisfy the user goal and stay consistent with the retrieved evidence.",
              before_passed: false,
              after_passed: true,
              confidence: 0.92,
              reason:
                "The original output contradicted the retrieved evidence; the corrected output is consistent with it.",
            },
          ],
        },
        passed: true,
      },
    ],
    pr: {
      branch,
      title: `Fix: ${title}`,
      body: `## Root cause\n${rootCause}\n\n## Fix\nAdds a post-action goal-verification guard wired into the agent's completion path, so a failed goal check blocks the success claim.\n\n## Verification\n- LLM-as-judge eval: before FAIL → after PASS (confidence 0.92)\n- Regression replay: ${affected} failing → 0 failing`,
      changed_files: ["agents/goal_verification_guard.py"],
      fallback: true,
      pr_url: null,
    },
  };
}
