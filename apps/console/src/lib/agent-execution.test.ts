import { afterEach, describe, expect, it, vi } from "vitest";

import {
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
  it("opens one PR per demo agent and requests Devin review", async () => {
    vi.stubEnv("GITHUB_TOKEN", "ghp_test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.includes("/git/ref/heads/main")) {
        return jsonResponse({ object: { sha: "base-sha" } });
      }
      if (url.endsWith("/git/refs") && method === "POST") {
        return jsonResponse({ ref: "refs/heads/test" });
      }
      if (url.includes("/contents/") && method === "GET") {
        return jsonResponse({
          content: Buffer.from("existing file\n", "utf8").toString("base64"),
          encoding: "base64",
          sha: "file-sha",
        });
      }
      if (url.includes("/contents/") && method === "PUT") {
        return jsonResponse({ content: { sha: "new-file-sha" } });
      }
      if (url.endsWith("/pulls") && method === "POST") {
        const pullNumber = fetchMock.mock.calls.filter(([calledUrl]) =>
          String(calledUrl).endsWith("/pulls"),
        ).length;
        return jsonResponse({
          html_url: `https://github.com/obro79/demo-agents/pull/${pullNumber}`,
          number: pullNumber,
        });
      }
      if (url.includes("/issues/") && url.endsWith("/comments") && method === "POST") {
        return jsonResponse({ id: 100 });
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

    expect(result.status).toBe("pr_opened");
    expect(result.targetRepo).toBe("obro79/demo-agents");
    expect(result.pullRequests.map((pullRequest) => pullRequest.agentType)).toEqual([
      "browser",
      "chat",
      "voice",
    ]);
    expect(result.pullRequests.every((pullRequest) => pullRequest.devinReviewRequested)).toBe(true);
    expect(result.pullRequests.map((pullRequest) => pullRequest.url)).toEqual([
      "https://github.com/obro79/demo-agents/pull/1",
      "https://github.com/obro79/demo-agents/pull/2",
      "https://github.com/obro79/demo-agents/pull/3",
    ]);
  });

  it("returns partial when one agent PR fails", async () => {
    vi.stubEnv("GITHUB_TOKEN", "ghp_test");
    let pullAttempts = 0;
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/git/ref/heads/main")) return jsonResponse({ object: { sha: "base-sha" } });
      if (url.endsWith("/git/refs") && method === "POST") return jsonResponse({});
      if (url.includes("/contents/") && method === "GET") {
        return jsonResponse({
          content: Buffer.from("existing file\n", "utf8").toString("base64"),
          encoding: "base64",
          sha: "file-sha",
        });
      }
      if (url.includes("/contents/") && method === "PUT") return jsonResponse({});
      if (url.endsWith("/pulls") && method === "POST") {
        pullAttempts += 1;
        if (pullAttempts === 2) return jsonResponse({ message: "validation failed" }, 422);
        return jsonResponse({
          html_url: `https://github.com/obro79/demo-agents/pull/${pullAttempts}`,
          number: pullAttempts,
        });
      }
      if (url.includes("/issues/") && url.endsWith("/comments") && method === "POST") {
        return jsonResponse({});
      }
      return jsonResponse({});
    }) as typeof fetch;

    const result = await dispatchDemoAgentPullRequests({
      incidentId: "inc_failed",
      sessionId: "ses_failed",
    });

    expect(result.status).toBe("partial");
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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}
