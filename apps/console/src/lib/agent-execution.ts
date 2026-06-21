import { execFileSync } from "node:child_process";

export type AgentDispatchStatus = "running" | "pr_opened" | "partial" | "error";
export type AgentDispatchType = "browser" | "chat" | "voice";

export interface AgentDispatchRequest {
  incidentId: string;
  sessionId: string;
  agentName?: string | null;
  incidentTitle?: string | null;
  rootCause?: string | null;
}

export interface AgentPullRequestResult {
  agentType: AgentDispatchType;
  title: string;
  url: string | null;
  branch: string | null;
  number: number | null;
  devinReviewRequested: boolean;
  error?: string;
}

export interface AgentPrDispatchResult {
  status: AgentDispatchStatus;
  targetRepo: string;
  pullRequests: AgentPullRequestResult[];
}

export interface ClosedTestPullRequestResult {
  title: string;
  url: string;
  branch: string;
  number: number;
  state: "closed";
  targetRepo: string;
}

interface GitHubContent {
  content: string;
  encoding: string;
  sha: string;
}

interface GitHubPullRequest {
  html_url: string;
  number: number;
  state?: string;
}

interface GitHubRef {
  object: {
    sha: string;
  };
}

interface AgentWorkOrder {
  agentType: AgentDispatchType;
  branchPrefix: string;
  commitMessage: string;
  filePath: string;
  title: string;
  body: string;
  appendContent: (request: AgentDispatchRequest) => string;
}

const TARGET_OWNER = "obro79";
const TARGET_REPO = "demo-agents";
const TARGET_REPO_SLUG = `${TARGET_OWNER}/${TARGET_REPO}`;
const TARGET_BASE_BRANCH = "main";
const GITHUB_API_URL = process.env.GITHUB_API_URL ?? "https://api.github.com";

const WORK_ORDERS: AgentWorkOrder[] = [
  {
    agentType: "browser",
    branchPrefix: "promptetheus/browser-agent",
    commitMessage: "Add Promptetheus browser replay guard",
    filePath: "agents/browser-fill-agent/README.md",
    title: "Add Promptetheus browser agent replay guard",
    body: "Adds a demo-safe Promptetheus remediation note for the browser fill agent after log triage.",
    appendContent: buildMarkdownPatch("Browser agent replay guard", [
      "Capture the failed selector path before retrying a form fill.",
      "Prefer idempotent replay inputs when reproducing the incident.",
      "Attach the Promptetheus incident id to the run metadata for follow-up.",
    ]),
  },
  {
    agentType: "chat",
    branchPrefix: "promptetheus/chat-agent",
    commitMessage: "Add Promptetheus chat recovery marker",
    filePath: "agents/demo-ui/src/components/chat-demo.tsx",
    title: "Add Promptetheus chat agent recovery marker",
    body: "Adds a lightweight recovery marker for the chat demo agent so the incident has a concrete PR artifact.",
    appendContent: (request) => `\n/*\n * Promptetheus demo remediation: chat agent recovery marker.\n * Incident: ${request.incidentId}\n * Session: ${request.sessionId}\n * The chat agent should preserve the last verified answer before retrying a failed tool-backed response.\n */\n`,
  },
  {
    agentType: "voice",
    branchPrefix: "promptetheus/voice-agent",
    commitMessage: "Add Promptetheus voice interruption guard",
    filePath: "agents/voice_agents/README.md",
    title: "Add Promptetheus voice agent interruption guard",
    body: "Adds a demo-safe Promptetheus remediation note for the voice agent interruption path.",
    appendContent: buildMarkdownPatch("Voice agent interruption guard", [
      "Record the last stable transcript chunk before an interruption.",
      "Replay the handoff with the captured session id when validating the fix.",
      "Keep the Promptetheus incident id in the local debug payload.",
    ]),
  },
];

export async function dispatchDemoAgentPullRequests(
  request: AgentDispatchRequest,
): Promise<AgentPrDispatchResult> {
  if (!request.incidentId || !request.sessionId) {
    throw new Error("incidentId and sessionId are required to dispatch agent PRs.");
  }

  const token = getGitHubToken();
  if (!token) {
    throw new Error("GITHUB_TOKEN or a logged-in gh CLI session is required to open demo agent pull requests.");
  }

  const client = new GitHubClient(token);
  const results: AgentPullRequestResult[] = [];

  for (const workOrder of WORK_ORDERS) {
    try {
      results.push(await openAgentPullRequest(client, workOrder, request));
    } catch (caught) {
      results.push({
        agentType: workOrder.agentType,
        branch: null,
        devinReviewRequested: false,
        error: caught instanceof Error ? caught.message : "Unknown agent dispatch failure.",
        number: null,
        title: workOrder.title,
        url: null,
      });
    }
  }

  const opened = results.filter((result) => result.url);
  const status: AgentDispatchStatus =
    opened.length === WORK_ORDERS.length
      ? "pr_opened"
      : opened.length > 0
        ? "partial"
        : "error";

  return {
    pullRequests: results,
    status,
    targetRepo: TARGET_REPO_SLUG,
  };
}

export async function createAndCloseLogsTestPullRequest(
  request: AgentDispatchRequest,
): Promise<ClosedTestPullRequestResult> {
  if (!request.incidentId || !request.sessionId) {
    throw new Error("incidentId and sessionId are required to create a test PR.");
  }

  const token = getGitHubToken();
  if (!token) {
    throw new Error("GITHUB_TOKEN or a logged-in gh CLI session is required to create a test PR.");
  }

  const client = new GitHubClient(token);
  const baseSha = await client.getBranchSha(TARGET_BASE_BRANCH);
  const branch = `promptetheus/test-pr-${slug(request.incidentId)}-${Date.now()}`;
  const filePath = "README.md";

  await client.createBranch(branch, baseSha);
  const current = await client.getFile(filePath, branch);
  const currentText = decodeGitHubContent(current);
  await client.updateFile({
    branch,
    content: encodeGitHubContent(
      `${currentText}\n<!-- Promptetheus closed test PR: ${request.incidentId} / ${request.sessionId} -->\n`,
    ),
    message: "Add Promptetheus closed test PR marker",
    path: filePath,
    sha: current.sha,
  });

  const pr = await client.createPullRequest({
    base: TARGET_BASE_BRANCH,
    body: [
      "Disposable Promptetheus smoke-test PR created from the logs page.",
      "",
      `Incident: \`${request.incidentId}\``,
      `Session: \`${request.sessionId}\``,
      "",
      "This PR is intentionally closed immediately after creation.",
    ].join("\n"),
    head: branch,
    title: "Promptetheus closed test PR",
  });
  await client.closePullRequest(pr.number);

  return {
    branch,
    number: pr.number,
    state: "closed",
    targetRepo: TARGET_REPO_SLUG,
    title: "Promptetheus closed test PR",
    url: pr.html_url,
  };
}

async function openAgentPullRequest(
  client: GitHubClient,
  workOrder: AgentWorkOrder,
  request: AgentDispatchRequest,
): Promise<AgentPullRequestResult> {
  const baseSha = await client.getBranchSha(TARGET_BASE_BRANCH);
  const branch = `${workOrder.branchPrefix}-${slug(request.incidentId)}-${Date.now()}`;

  await client.createBranch(branch, baseSha);
  const current = await client.getFile(workOrder.filePath, branch);
  const currentText = decodeGitHubContent(current);
  await client.updateFile({
    branch,
    content: encodeGitHubContent(`${currentText}${workOrder.appendContent(request)}`),
    message: workOrder.commitMessage,
    path: workOrder.filePath,
    sha: current.sha,
  });

  const pr = await client.createPullRequest({
    base: TARGET_BASE_BRANCH,
    body: buildPullRequestBody(workOrder, request),
    head: branch,
    title: workOrder.title,
  });
  const devinReviewRequested = await client.requestDevinReview(pr.number);

  return {
    agentType: workOrder.agentType,
    branch,
    devinReviewRequested,
    number: pr.number,
    title: workOrder.title,
    url: pr.html_url,
  };
}

function buildMarkdownPatch(title: string, bullets: string[]) {
  return (request: AgentDispatchRequest) => {
    const lines = [
      "",
      `## Promptetheus demo fix: ${title}`,
      "",
      `Incident: \`${request.incidentId}\``,
      `Session: \`${request.sessionId}\``,
      "",
      ...bullets.map((bullet) => `- ${bullet}`),
      "",
    ];
    return `\n${lines.join("\n")}`;
  };
}

function buildPullRequestBody(workOrder: AgentWorkOrder, request: AgentDispatchRequest): string {
  return [
    workOrder.body,
    "",
    "Promptetheus dispatch context:",
    `- Incident: \`${request.incidentId}\``,
    `- Session: \`${request.sessionId}\``,
    request.agentName ? `- Source agent: \`${request.agentName}\`` : null,
    request.incidentTitle ? `- Incident title: ${request.incidentTitle}` : null,
    request.rootCause ? `- Root cause: ${request.rootCause}` : null,
    "",
    "This is a lightweight demo PR created from the Promptetheus logs page.",
  ]
    .filter((line): line is string => line !== null)
    .join("\n");
}

function decodeGitHubContent(content: GitHubContent): string {
  if (content.encoding !== "base64") {
    throw new Error(`Unsupported GitHub content encoding: ${content.encoding}`);
  }
  return Buffer.from(content.content.replace(/\n/g, ""), "base64").toString("utf8");
}

function encodeGitHubContent(content: string): string {
  return Buffer.from(content, "utf8").toString("base64");
}

function getGitHubToken(): string | null {
  if (process.env.GITHUB_TOKEN) return process.env.GITHUB_TOKEN;
  try {
    return execFileSync("gh", ["auth", "token"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return null;
  }
}

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

class GitHubClient {
  constructor(private readonly token: string) {}

  async getBranchSha(branch: string): Promise<string> {
    const ref = await this.request<GitHubRef>(
      `/repos/${TARGET_REPO_SLUG}/git/ref/heads/${branch}`,
      { method: "GET" },
    );
    return ref.object.sha;
  }

  async createBranch(branch: string, sha: string): Promise<void> {
    await this.request(`/repos/${TARGET_REPO_SLUG}/git/refs`, {
      body: JSON.stringify({ ref: `refs/heads/${branch}`, sha }),
      method: "POST",
    });
  }

  async getFile(path: string, branch: string): Promise<GitHubContent> {
    return this.request<GitHubContent>(
      `/repos/${TARGET_REPO_SLUG}/contents/${encodeURIComponentPath(path)}?ref=${encodeURIComponent(branch)}`,
      { method: "GET" },
    );
  }

  async updateFile(input: {
    branch: string;
    content: string;
    message: string;
    path: string;
    sha: string;
  }): Promise<void> {
    await this.request(`/repos/${TARGET_REPO_SLUG}/contents/${encodeURIComponentPath(input.path)}`, {
      body: JSON.stringify(input),
      method: "PUT",
    });
  }

  async createPullRequest(input: {
    base: string;
    body: string;
    head: string;
    title: string;
  }): Promise<GitHubPullRequest> {
    return this.request<GitHubPullRequest>(`/repos/${TARGET_REPO_SLUG}/pulls`, {
      body: JSON.stringify(input),
      method: "POST",
    });
  }

  async requestDevinReview(prNumber: number): Promise<boolean> {
    const body = process.env.DEVIN_REVIEW_COMMENT ?? "@devin review this PR";
    try {
      await this.request(`/repos/${TARGET_REPO_SLUG}/issues/${prNumber}/comments`, {
        body: JSON.stringify({ body }),
        method: "POST",
      });
      return true;
    } catch {
      return false;
    }
  }

  async closePullRequest(prNumber: number): Promise<void> {
    await this.request(`/repos/${TARGET_REPO_SLUG}/pulls/${prNumber}`, {
      body: JSON.stringify({ state: "closed" }),
      method: "PATCH",
    });
  }

  private async request<T = unknown>(path: string, init: RequestInit): Promise<T> {
    const response = await fetch(`${GITHUB_API_URL}${path}`, {
      ...init,
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${this.token}`,
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
        ...(init.headers ?? {}),
      },
    });
    if (!response.ok) {
      throw new Error(`GitHub ${response.status}: ${await response.text()}`);
    }
    return (await response.json()) as T;
  }
}

function encodeURIComponentPath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}
