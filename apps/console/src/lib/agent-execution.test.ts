import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("node:child_process", () => {
  const execFileSync = vi.fn(() => {
    throw new Error("gh auth unavailable");
  });
  return {
    default: { execFileSync },
    execFileSync,
  };
});

import {
  checkDevinOpenedPullRequests,
  createAndCloseLogsTestPullRequest,
  dispatchDemoAgentPullRequests,
} from "./agent-execution";

const originalFetch = globalThis.fetch;

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  globalThis.fetch = originalFetch;
});

describe("dispatchDemoAgentPullRequests", () => {
  it("creates one Devin session per demo agent when DEVIN_API_KEY is configured", async () => {
    vi.stubEnv("DEVIN_API_KEY", "devin_test");
    vi.stubEnv("ORKES_API_URL", "");
    vi.stubEnv("ORKES_CONDUCTOR_URL", "");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.endsWith("/v1/sessions") && method === "POST") {
        const sessionNumber = fetchMock.mock.calls.filter(([calledUrl]) =>
          String(calledUrl).endsWith("/v1/sessions"),
        ).length;
        return jsonResponse({
          session_id: `devin-${sessionNumber}`,
          url: `https://app.devin.ai/sessions/devin-${sessionNumber}`,
        });
      }
      return jsonResponse({ message: "not found" }, 404);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    const result = await dispatchDemoAgentPullRequests({
      agentName: "browser-agent@test",
      incidentId: "inc_failed",
      incidentTitle: "Wrong time selected",
      rootCause: "The selected time was wrong.",
      sessionId: "ses_failed",
    });

    expect(result.status).toBe("devin_dispatched");
    expect(result.targetRepo).toBe("obro79/demo-agents");
    expect(result.orchestrator).toBe("local_orkes");
    expect(result.workflowRunId).toMatch(/^local-orkes-inc-failed-/);
    expect(result.evalGate).toMatchObject({
      afterFail: null,
      beforeFail: 1,
      caseCount: 3,
      status: "pending",
    });
    expect(result.workflowStages?.map((stage) => stage.id)).toEqual([
      "build_eval_set",
      "dispatch_devin",
      "wait_for_pr",
      "run_evals",
      "sentry_proof",
      "close_loop",
    ]);
    expect(result.workflowStages?.find((stage) => stage.id === "dispatch_devin")?.status).toBe("passed");
    expect(result.pullRequests.map((pullRequest) => pullRequest.agentType)).toEqual([
      "browser",
      "chat",
      "voice",
    ]);
    expect(result.pullRequests.every((pullRequest) => pullRequest.kind === "devin_session")).toBe(true);
    expect(result.pullRequests.every((pullRequest) => pullRequest.devinPrRequested)).toBe(true);
    expect(result.pullRequests.every((pullRequest) => !pullRequest.devinReviewRequested)).toBe(true);
    expect(result.pullRequests.map((pullRequest) => pullRequest.url)).toEqual([
      "https://app.devin.ai/sessions/devin-1",
      "https://app.devin.ai/sessions/devin-2",
      "https://app.devin.ai/sessions/devin-3",
    ]);
    expect(JSON.stringify(fetchMock.mock.calls[0]?.[1]?.body)).toContain("Your job is to make the pull request yourself");
    expect(JSON.stringify(fetchMock.mock.calls[0]?.[1]?.body)).toContain("Orkes workflow");
    expect(JSON.stringify(fetchMock.mock.calls[0]?.[1]?.body)).toContain("Run the relevant checks and evals");
    expect(JSON.stringify(fetchMock.mock.calls[0]?.[1]?.body)).toContain(
      "Promptetheus-Dispatch: inc_failed/ses_failed/browser",
    );
    expect(JSON.stringify(fetchMock.mock.calls[0]?.[1]?.headers)).toContain("Bearer devin_test");
  });

  it("starts an Orkes workflow when Orkes credentials are configured", async () => {
    vi.stubEnv("DEVIN_API_KEY", "devin_test");
    vi.stubEnv("ORKES_API_KEY", "orkes_test");
    vi.stubEnv("ORKES_API_URL", "https://orkes.example");
    vi.stubEnv("ORKES_WORKFLOW_NAME", "promptetheus_fix_dispatch");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url === "https://orkes.example/api/workflow/promptetheus_fix_dispatch" && method === "POST") {
        return jsonResponse({ workflowId: "wf_123" });
      }
      if (url.endsWith("/v1/sessions") && method === "POST") {
        const sessionNumber = fetchMock.mock.calls.filter(([calledUrl]) =>
          String(calledUrl).endsWith("/v1/sessions"),
        ).length;
        return jsonResponse({
          session_id: `devin-${sessionNumber}`,
          url: `https://app.devin.ai/sessions/devin-${sessionNumber}`,
        });
      }
      return jsonResponse({ message: "not found" }, 404);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    const result = await dispatchDemoAgentPullRequests({
      incidentId: "inc_failed",
      rootCause: "The selected time was wrong.",
      sessionId: "ses_failed",
    });

    expect(result.orchestrator).toBe("orkes");
    expect(result.workflowRunId).toBe("wf_123");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://orkes.example/api/workflow/promptetheus_fix_dispatch",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer orkes_test" }),
        method: "POST",
      }),
    );
    expect(JSON.stringify(fetchMock.mock.calls[0]?.[1]?.body)).toContain("inc_failed");
    expect(result.pullRequests).toHaveLength(3);
  });

  it("falls back to GitHub Devin issues when DEVIN_API_KEY is unavailable", async () => {
    vi.stubEnv("GITHUB_TOKEN", "ghp_test");
    vi.stubEnv("ORKES_API_URL", "");
    vi.stubEnv("ORKES_CONDUCTOR_URL", "");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.endsWith("/issues") && method === "POST") {
        const issueNumber = fetchMock.mock.calls.filter(([calledUrl]) =>
          String(calledUrl).endsWith("/issues"),
        ).length;
        return jsonResponse({
          html_url: `https://github.com/obro79/demo-agents/issues/${issueNumber}`,
          number: issueNumber,
        });
      }
      return jsonResponse({ message: "not found" }, 404);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    const result = await dispatchDemoAgentPullRequests({
      incidentId: "inc_failed",
      sessionId: "ses_failed",
    });

    expect(result.status).toBe("devin_dispatched");
    expect(result.orchestrator).toBe("local_orkes");
    expect(result.evalGate?.status).toBe("pending");
    expect(result.pullRequests.every((pullRequest) => pullRequest.kind === "devin_issue")).toBe(true);
    expect(result.pullRequests.map((pullRequest) => pullRequest.url)).toEqual([
      "https://github.com/obro79/demo-agents/issues/1",
      "https://github.com/obro79/demo-agents/issues/2",
      "https://github.com/obro79/demo-agents/issues/3",
    ]);
    expect(JSON.stringify(fetchMock.mock.calls[0]?.[1]?.body)).toContain("@devin please investigate");
    expect(JSON.stringify(fetchMock.mock.calls[0]?.[1]?.body)).toContain("Run evals before marking the PR ready");
    expect(JSON.stringify(fetchMock.mock.calls[0]?.[1]?.body)).toContain(
      "Promptetheus-Dispatch: inc_failed/ses_failed/browser",
    );
  });

  it("returns partial when one Devin PR request fails", async () => {
    vi.stubEnv("GITHUB_TOKEN", "ghp_test");
    vi.stubEnv("ORKES_API_URL", "");
    vi.stubEnv("ORKES_CONDUCTOR_URL", "");
    let issueAttempts = 0;
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/issues") && method === "POST") {
        issueAttempts += 1;
        if (issueAttempts === 2) return jsonResponse({ message: "validation failed" }, 422);
        return jsonResponse({
          html_url: `https://github.com/obro79/demo-agents/issues/${issueAttempts}`,
          number: issueAttempts,
        });
      }
      return jsonResponse({});
    }) as typeof fetch;

    const result = await dispatchDemoAgentPullRequests({
      incidentId: "inc_failed",
      sessionId: "ses_failed",
    });

    expect(result.status).toBe("partial");
    expect(result.workflowStages?.find((stage) => stage.id === "dispatch_devin")?.status).toBe("running");
    expect(result.pullRequests.filter((pullRequest) => pullRequest.url)).toHaveLength(2);
    expect(result.pullRequests.find((pullRequest) => pullRequest.agentType === "chat")?.error).toContain(
      "GitHub 422",
    );
  });

  it("creates and closes one disposable test PR", async () => {
    vi.stubEnv("GITHUB_TOKEN", "ghp_test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.includes("/git/ref/heads/main")) return jsonResponse({ object: { sha: "base-sha" } });
      if (url.endsWith("/git/refs") && method === "POST") return jsonResponse({});
      if (url.includes("/contents/") && method === "GET") {
        return jsonResponse({
          content: Buffer.from("existing readme\n", "utf8").toString("base64"),
          encoding: "base64",
          sha: "file-sha",
        });
      }
      if (url.includes("/contents/") && method === "PUT") return jsonResponse({});
      if (url.endsWith("/pulls") && method === "POST") {
        return jsonResponse({
          html_url: "https://github.com/obro79/demo-agents/pull/44",
          number: 44,
        });
      }
      if (url.endsWith("/pulls/44") && method === "PATCH") {
        return jsonResponse({ state: "closed" });
      }
      return jsonResponse({ message: "not found" }, 404);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    const result = await createAndCloseLogsTestPullRequest({
      incidentId: "inc_failed",
      sessionId: "ses_failed",
    });

    expect(result).toMatchObject({
      number: 44,
      state: "closed",
      targetRepo: "obro79/demo-agents",
      url: "https://github.com/obro79/demo-agents/pull/44",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/repos/obro79/demo-agents/pulls/44"),
      expect.objectContaining({ method: "PATCH" }),
    );
  });
});

describe("checkDevinOpenedPullRequests", () => {
  it("finds an open GitHub PR by incident/session marker", async () => {
    vi.stubEnv("GITHUB_TOKEN", "ghp_test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.includes("/search/issues") && method === "GET") {
        return jsonResponse({
          items: [
            {
              body: "Promptetheus-Dispatch: inc_failed/ses_failed/browser",
              html_url: "https://github.com/obro79/demo-agents/pull/77",
              number: 77,
              pull_request: {},
              title: "Add Promptetheus browser agent replay guard",
            },
          ],
        });
      }
      if (url.endsWith("/pulls/77") && method === "GET") {
        return jsonResponse({
          head: { ref: "devin/browser-agent-fix" },
          html_url: "https://github.com/obro79/demo-agents/pull/77",
          number: 77,
          title: "Add Promptetheus browser agent replay guard",
        });
      }
      return jsonResponse({ message: "not found" }, 404);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    const result = await checkDevinOpenedPullRequests({
      dispatchResult: trackedDispatchResult(),
      incidentId: "inc_failed",
      sessionId: "ses_failed",
    });

    expect(result.status).toBe("pr_opened");
    expect(result.trackingStatus).toBe("tracking");
    expect(result.pullRequests[0]).toMatchObject({
      openedPrBranch: "devin/browser-agent-fix",
      openedPrNumber: 77,
      openedPrTitle: "Add Promptetheus browser agent replay guard",
      openedPrUrl: "https://github.com/obro79/demo-agents/pull/77",
    });
    expect(result.workflowStages?.find((stage) => stage.id === "wait_for_pr")?.status).toBe("passed");
  });

  it("keeps Devin dispatched while no matching GitHub PR exists yet", async () => {
    vi.stubEnv("GITHUB_TOKEN", "ghp_test");
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/search/issues") && method === "GET") return jsonResponse({ items: [] });
      return jsonResponse({ message: "not found" }, 404);
    }) as typeof fetch;

    const result = await checkDevinOpenedPullRequests({
      dispatchResult: trackedDispatchResult(),
      incidentId: "inc_failed",
      sessionId: "ses_failed",
    });

    expect(result.status).toBe("devin_dispatched");
    expect(result.trackingStatus).toBe("not_found");
    expect(result.pullRequests.every((pullRequest) => !pullRequest.openedPrUrl)).toBe(true);
    expect(result.workflowStages?.find((stage) => stage.id === "wait_for_pr")?.status).toBe("running");
  });

  it("returns tracking-unavailable metadata when GitHub credentials are unavailable", async () => {
    vi.stubEnv("GITHUB_TOKEN", "");
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as typeof fetch;

    const result = await checkDevinOpenedPullRequests({
      dispatchResult: trackedDispatchResult(),
      incidentId: "inc_failed",
      sessionId: "ses_failed",
    });

    expect(result.status).toBe("devin_dispatched");
    expect(result.trackingStatus).toBe("tracking_unavailable");
    expect(result.trackingError).toBe("Devin dispatched; GitHub PR tracking unavailable.");
    expect(result.workflowStages?.find((stage) => stage.id === "wait_for_pr")?.status).toBe("blocked");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

function trackedDispatchResult() {
  return {
    pullRequests: [
      {
        agentType: "browser" as const,
        branch: null,
        devinPrRequested: true,
        devinReviewRequested: false,
        externalId: "devin-21",
        kind: "devin_session" as const,
        number: null,
        title: "Devin: Add Promptetheus browser agent replay guard",
        url: "https://app.devin.ai/sessions/devin-21",
      },
      {
        agentType: "chat" as const,
        branch: null,
        devinPrRequested: true,
        devinReviewRequested: false,
        externalId: "devin-22",
        kind: "devin_session" as const,
        number: null,
        title: "Devin: Add Promptetheus chat agent recovery marker",
        url: "https://app.devin.ai/sessions/devin-22",
      },
    ],
    status: "devin_dispatched" as const,
    targetRepo: "obro79/demo-agents",
    workflowStages: [
      {
        detail: "2/2 Devin agent tasks created.",
        id: "dispatch_devin" as const,
        label: "Dispatch Devin",
        status: "passed" as const,
      },
      {
        detail: "Waiting for Devin to open a candidate PR from the dispatched task.",
        id: "wait_for_pr" as const,
        label: "Wait for PR",
        status: "running" as const,
      },
    ],
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}
