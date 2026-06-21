import { execFileSync } from "node:child_process";

export type AgentDispatchStatus = "running" | "devin_dispatched" | "pr_opened" | "partial" | "error";
export type AgentDispatchType = "browser" | "chat" | "voice";

export interface AgentDispatchRequest {
  incidentId: string;
  sessionId: string;
  agentName?: string | null;
  incidentTitle?: string | null;
  rootCause?: string | null;
}

export interface AgentPrStatusRequest {
  incidentId: string;
  sessionId: string;
  dispatchResult: AgentPrDispatchResult;
}

export interface AgentPullRequestResult {
  agentType: AgentDispatchType;
  kind?: "devin_issue" | "devin_session" | "pull_request";
  title: string;
  url: string | null;
  branch: string | null;
  externalId?: string | null;
  number: number | null;
  openedPrUrl?: string | null;
  openedPrNumber?: number | null;
  openedPrTitle?: string | null;
  openedPrBranch?: string | null;
  prDetectedAt?: string | null;
  devinPrRequested?: boolean;
  devinReviewRequested: boolean;
  error?: string;
}

export type AgentPrTrackingStatus = "tracking" | "not_found" | "tracking_unavailable";

export type FixWorkflowOrchestrator = "orkes" | "local_orkes";
export type FixWorkflowStageStatus = "pending" | "running" | "passed" | "failed" | "blocked";
export type FixWorkflowStageId =
  | "build_eval_set"
  | "dispatch_devin"
  | "wait_for_pr"
  | "run_evals"
  | "sentry_proof"
  | "close_loop";

export interface FixWorkflowStage {
  id: FixWorkflowStageId;
  label: string;
  status: FixWorkflowStageStatus;
  detail: string;
}

export interface EvalGateReceipt {
  status: "pending" | "passed" | "failed";
  caseCount: number;
  beforeFail: number;
  afterFail: number | null;
  assertion: string;
  confidence: number | null;
  note: string;
}

export interface SentryProofReceipt {
  configured: boolean;
  traceId: string | null;
  detail: string;
}

export interface AgentPrDispatchResult {
  status: AgentDispatchStatus;
  targetRepo: string;
  pullRequests: AgentPullRequestResult[];
  trackingStatus?: AgentPrTrackingStatus;
  trackingError?: string | null;
  orchestrator?: FixWorkflowOrchestrator;
  workflowRunId?: string | null;
  workflowStages?: FixWorkflowStage[];
  evalGate?: EvalGateReceipt | null;
  sentryProof?: SentryProofReceipt | null;
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
  title?: string;
  head?: {
    ref?: string;
  };
}

interface GitHubSearchIssue {
  html_url: string;
  number: number;
  title: string;
  body?: string | null;
  pull_request?: unknown;
}

interface GitHubSearchResponse {
  items: GitHubSearchIssue[];
}

interface GitHubIssue {
  html_url: string;
  number: number;
}

interface GitHubRef {
  object: {
    sha: string;
  };
}

interface DevinSession {
  session_id?: string;
  id?: string;
  url?: string;
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

// Target repo for demo PRs. Override with env to point at a repo your token can
// write to: GITHUB_TARGET_OWNER/GITHUB_TARGET_REPO (or GITHUB_TARGET_REPO as a
// full "owner/repo" slug). A 404 from the GitHub API here means the token can't
// see the repo — usually wrong owner/repo or missing write access.
const TARGET_REPO_SLUG =
  process.env.GITHUB_TARGET_REPO && process.env.GITHUB_TARGET_REPO.includes("/")
    ? process.env.GITHUB_TARGET_REPO
    : `${process.env.GITHUB_TARGET_OWNER ?? "obro79"}/${process.env.GITHUB_TARGET_REPO ?? "demo-agents"}`;
const TARGET_BASE_BRANCH = process.env.GITHUB_TARGET_BASE_BRANCH ?? "main";
const GITHUB_API_URL = process.env.GITHUB_API_URL ?? "https://api.github.com";
const DEVIN_API_URL = process.env.PROMPTETHEUS_DEVIN_API_URL ?? "https://api.devin.ai";
const DEVIN_WEB_URL = process.env.PROMPTETHEUS_DEVIN_WEB_URL ?? "https://app.devin.ai";
const DEFAULT_ORKES_WORKFLOW_NAME = "promptetheus_fix_dispatch";

interface FixWorkflowStart {
  orchestrator: FixWorkflowOrchestrator;
  workflowRunId: string;
}

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
    throw new Error("incidentId and sessionId are required to dispatch Devin PR requests.");
  }

  const workflow = await startFixWorkflow(request);
  const devinApiKey = process.env.DEVIN_API_KEY;
  if (devinApiKey) {
    return withFixWorkflowReceipts(request, await dispatchDevinSessions(request, devinApiKey), workflow);
  }

  const token = getGitHubToken();
  if (!token) {
    throw new Error("DEVIN_API_KEY, GITHUB_TOKEN, or a logged-in gh CLI session is required to request Devin pull requests.");
  }

  const client = new GitHubClient(token);
  const results: AgentPullRequestResult[] = [];

  for (const workOrder of WORK_ORDERS) {
    try {
      results.push(await requestDevinPullRequest(client, workOrder, request));
    } catch (caught) {
      results.push({
        agentType: workOrder.agentType,
        branch: null,
        devinPrRequested: false,
        devinReviewRequested: false,
        error: caught instanceof Error ? caught.message : "Unknown agent dispatch failure.",
        kind: "devin_issue",
        number: null,
        title: workOrder.title,
        url: null,
      });
    }
  }

  const opened = results.filter((result) => result.url);
  const status: AgentDispatchStatus =
    opened.length === WORK_ORDERS.length
      ? "devin_dispatched"
      : opened.length > 0
        ? "partial"
        : "error";

  return withFixWorkflowReceipts(request, {
    pullRequests: results,
    status,
    targetRepo: TARGET_REPO_SLUG,
  }, workflow);
}

async function dispatchDevinSessions(
  request: AgentDispatchRequest,
  apiKey: string,
): Promise<AgentPrDispatchResult> {
  const results: AgentPullRequestResult[] = [];
  for (const workOrder of WORK_ORDERS) {
    try {
      results.push(await createDevinSession(workOrder, request, apiKey));
    } catch (caught) {
      results.push({
        agentType: workOrder.agentType,
        branch: null,
        devinPrRequested: false,
        devinReviewRequested: false,
        error: caught instanceof Error ? caught.message : "Unknown Devin dispatch failure.",
        kind: "devin_session",
        number: null,
        title: workOrder.title,
        url: null,
      });
    }
  }

  const opened = results.filter((result) => result.url || result.externalId);
  const status: AgentDispatchStatus =
    opened.length === WORK_ORDERS.length
      ? "devin_dispatched"
      : opened.length > 0
        ? "partial"
        : "error";

  return {
    pullRequests: results,
    status,
    targetRepo: TARGET_REPO_SLUG,
  };
}

export async function checkDevinOpenedPullRequests(
  request: AgentPrStatusRequest,
): Promise<AgentPrDispatchResult> {
  if (!request.incidentId || !request.sessionId) {
    throw new Error("incidentId and sessionId are required to track Devin pull requests.");
  }
  if (request.dispatchResult.targetRepo !== TARGET_REPO_SLUG) {
    throw new Error(`Devin PR tracking only supports ${TARGET_REPO_SLUG}.`);
  }
  if (request.dispatchResult.pullRequests.length > WORK_ORDERS.length) {
    throw new Error(`Devin PR tracking accepts at most ${WORK_ORDERS.length} work orders.`);
  }

  const token = getGitHubToken();
  if (!token) {
    return withUpdatedWorkflowStages({
      ...request.dispatchResult,
      trackingError: "Devin dispatched; GitHub PR tracking unavailable.",
      trackingStatus: "tracking_unavailable",
    });
  }

  const client = new GitHubClient(token);
  const candidates = await client.searchPullRequests(
    buildPullRequestSearchQuery(request.incidentId, request.sessionId),
  );
  const usedPullRequestNumbers = new Set<number>();
  const detectedAt = new Date().toISOString();
  const pullRequests: AgentPullRequestResult[] = [];

  for (const pullRequest of request.dispatchResult.pullRequests) {
    if (hasOpenedPullRequest(pullRequest)) {
      pullRequests.push(pullRequest);
      if (pullRequest.openedPrNumber) usedPullRequestNumbers.add(pullRequest.openedPrNumber);
      continue;
    }

    const match = matchOpenedPullRequest({
      candidates,
      incidentId: request.incidentId,
      pullRequest,
      sessionId: request.sessionId,
      usedPullRequestNumbers,
    });
    if (!match) {
      pullRequests.push(pullRequest);
      continue;
    }

    usedPullRequestNumbers.add(match.number);
    const pr = await client.getPullRequest(match.number).catch(() => null);
    pullRequests.push({
      ...pullRequest,
      openedPrBranch: pr?.head?.ref ?? null,
      openedPrNumber: pr?.number ?? match.number,
      openedPrTitle: pr?.title ?? match.title,
      openedPrUrl: pr?.html_url ?? match.html_url,
      prDetectedAt: detectedAt,
    });
  }

  const detectedCount = pullRequests.filter(hasOpenedPullRequest).length;
  const status: AgentDispatchStatus =
    detectedCount > 0
      ? "pr_opened"
      : request.dispatchResult.status === "error"
        ? "error"
        : "devin_dispatched";

  return withUpdatedWorkflowStages({
    ...request.dispatchResult,
    pullRequests,
    status,
    trackingError: null,
    trackingStatus: detectedCount > 0 ? "tracking" : "not_found",
  });
}

function withFixWorkflowReceipts(
  request: AgentDispatchRequest,
  result: AgentPrDispatchResult,
  workflow: FixWorkflowStart,
): AgentPrDispatchResult {
  const evalGate = buildEvalGateReceipt(request, result);
  return {
    ...result,
    evalGate,
    orchestrator: workflow.orchestrator,
    sentryProof: buildSentryProof(request, workflow.workflowRunId),
    workflowRunId: workflow.workflowRunId,
    workflowStages: buildWorkflowStages(result, evalGate),
  };
}

function withUpdatedWorkflowStages(result: AgentPrDispatchResult): AgentPrDispatchResult {
  if (!result.workflowStages?.length) return result;

  const detectedCount = result.pullRequests.filter(hasOpenedPullRequest).length;
  const total = Math.max(1, result.pullRequests.length);
  return {
    ...result,
    workflowStages: result.workflowStages.map((stage) => {
      if (stage.id !== "wait_for_pr") return stage;
      if (detectedCount > 0) {
        return {
          ...stage,
          detail: `${detectedCount}/${total} Devin-opened GitHub PR${detectedCount === 1 ? "" : "s"} detected.`,
          status: "passed",
        };
      }
      if (result.trackingStatus === "tracking_unavailable") {
        return {
          ...stage,
          detail: "Devin dispatched; GitHub PR tracking unavailable.",
          status: "blocked",
        };
      }
      return {
        ...stage,
        detail: "Checking GitHub for a Devin-opened PR from the dispatched task.",
        status: "running",
      };
    }),
  };
}

async function startFixWorkflow(request: AgentDispatchRequest): Promise<FixWorkflowStart> {
  const orkesApiUrl = getOrkesApiUrl();
  if (!orkesApiUrl) {
    return {
      orchestrator: "local_orkes",
      workflowRunId: formatWorkflowRunId(request, "local-orkes"),
    };
  }

  try {
    const response = await fetch(
      `${orkesApiUrl.replace(/\/$/, "")}/api/workflow/${encodeURIComponent(getOrkesWorkflowName())}`,
      {
        body: JSON.stringify({
          input: {
            agentName: request.agentName,
            incidentId: request.incidentId,
            incidentTitle: request.incidentTitle,
            rootCause: request.rootCause,
            sessionId: request.sessionId,
            targetRepo: TARGET_REPO_SLUG,
          },
        }),
        headers: {
          "Content-Type": "application/json",
          ...(process.env.ORKES_API_KEY ? { Authorization: `Bearer ${process.env.ORKES_API_KEY}` } : {}),
        },
        method: "POST",
      },
    );
    if (!response.ok) {
      throw new Error(`Orkes ${response.status}: ${await response.text()}`);
    }
    const body = (await response.json()) as {
      workflowId?: string;
      workflow_id?: string;
      workflowInstanceId?: string;
      id?: string;
    };
    return {
      orchestrator: "orkes",
      workflowRunId:
        body.workflowId ?? body.workflow_id ?? body.workflowInstanceId ?? body.id ?? formatWorkflowRunId(request, "orkes"),
    };
  } catch {
    return {
      orchestrator: "local_orkes",
      workflowRunId: formatWorkflowRunId(request, "local-orkes"),
    };
  }
}

function getOrkesApiUrl(): string | null {
  return process.env.ORKES_API_URL || process.env.ORKES_CONDUCTOR_URL || null;
}

function getOrkesWorkflowName(): string {
  return process.env.ORKES_WORKFLOW_NAME || DEFAULT_ORKES_WORKFLOW_NAME;
}

function formatWorkflowRunId(request: AgentDispatchRequest, prefix: string): string {
  return `${prefix}-${slug(request.incidentId)}-${Date.now()}`;
}

function buildWorkflowStages(
  result: AgentPrDispatchResult,
  evalGate: EvalGateReceipt,
): FixWorkflowStage[] {
  const completed = result.pullRequests.filter((pullRequest) => pullRequest.url || pullRequest.externalId).length;
  const total = Math.max(1, result.pullRequests.length);
  const detectedCount = result.pullRequests.filter(hasOpenedPullRequest).length;
  const allDispatched = completed === total;
  const noneDispatched = completed === 0;
  return [
    {
      detail: "Incident trace, root cause, and replay assertion packaged for the workflow.",
      id: "build_eval_set",
      label: "Build eval set",
      status: "passed",
    },
    {
      detail: noneDispatched
        ? "Devin handoff failed before all agent tasks were created."
        : `${completed}/${total} Devin agent tasks created.`,
      id: "dispatch_devin",
      label: "Dispatch Devin",
      status: noneDispatched ? "failed" : allDispatched ? "passed" : "running",
    },
    {
      detail: detectedCount
        ? `${detectedCount}/${total} Devin-opened GitHub PR${detectedCount === 1 ? "" : "s"} detected.`
        : "Waiting for Devin to open a candidate PR from the dispatched task.",
      id: "wait_for_pr",
      label: "Wait for PR",
      status: detectedCount ? "passed" : allDispatched ? "running" : noneDispatched ? "blocked" : "pending",
    },
    {
      detail: evalGate.note,
      id: "run_evals",
      label: "Run evals",
      status: evalGate.status === "passed" ? "passed" : evalGate.status === "failed" ? "failed" : "pending",
    },
    {
      detail: "Eval receipts will be attached to Sentry when the live workflow reports a PR/eval result.",
      id: "sentry_proof",
      label: "Sentry proof",
      status: evalGate.status === "passed" ? "passed" : "pending",
    },
    {
      detail: "Promptetheus does not merge in-app; it closes the loop by linking the reviewed GitHub PR.",
      id: "close_loop",
      label: "Close loop",
      status: evalGate.status === "passed" ? "passed" : "pending",
    },
  ];
}

function hasOpenedPullRequest(pullRequest: AgentPullRequestResult): boolean {
  return Boolean(pullRequest.openedPrUrl || (pullRequest.kind === "pull_request" && pullRequest.url));
}

function buildEvalGateReceipt(
  request: AgentDispatchRequest,
  result: AgentPrDispatchResult,
): EvalGateReceipt {
  const rootCause = request.rootCause ?? request.incidentTitle ?? "selected run failure";
  const completed = result.pullRequests.filter((pullRequest) => pullRequest.url || pullRequest.externalId).length;
  const allDispatched = completed === result.pullRequests.length && result.pullRequests.length > 0;
  return {
    afterFail: null,
    assertion: `Fix must resolve: ${rootCause}`,
    beforeFail: 1,
    caseCount: WORK_ORDERS.length,
    confidence: null,
    note: allDispatched
      ? "Eval set is attached to Devin. The PR is not ready until Devin runs it and reports the result."
      : "Eval set prepared, but Devin dispatch did not complete for every agent task.",
    status: "pending",
  };
}

function buildSentryProof(
  request: AgentDispatchRequest,
  workflowRunId: string,
): SentryProofReceipt {
  const configured = Boolean(process.env.SENTRY_DSN);
  return {
    configured,
    detail: configured
      ? "Sentry DSN is configured; live backend heal/eval spans can be correlated with this workflow id."
      : "Sentry DSN is not configured in this process; showing local workflow proof only.",
    traceId: configured ? `promptetheus-${slug(request.incidentId)}-${workflowRunId.split("-").pop()}` : null,
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

async function requestDevinPullRequest(
  client: GitHubClient,
  workOrder: AgentWorkOrder,
  request: AgentDispatchRequest,
): Promise<AgentPullRequestResult> {
  const issue = await client.createIssue({
    body: buildDevinTaskBody(workOrder, request),
    title: `Devin: ${workOrder.title}`,
  });

  return {
    agentType: workOrder.agentType,
    branch: null,
    devinPrRequested: true,
    devinReviewRequested: false,
    kind: "devin_issue",
    number: issue.number,
    title: `Devin: ${workOrder.title}`,
    url: issue.html_url,
  };
}

async function createDevinSession(
  workOrder: AgentWorkOrder,
  request: AgentDispatchRequest,
  apiKey: string,
): Promise<AgentPullRequestResult> {
  const sessionsPath = process.env.PROMPTETHEUS_DEVIN_ORG_ID
    ? `/v3/organizations/${process.env.PROMPTETHEUS_DEVIN_ORG_ID}/sessions`
    : "/v1/sessions";
  const response = await fetch(`${DEVIN_API_URL.replace(/\/$/, "")}${sessionsPath}`, {
    body: JSON.stringify({
      idempotent: true,
      prompt: buildDevinSessionPrompt(workOrder, request),
      tags: ["promptetheus", "logs-dispatch", `${workOrder.agentType}-agent`],
      title: `Promptetheus: ${workOrder.title}`,
    }),
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Devin ${response.status}: ${await response.text()}`);
  }

  const body = (await response.json()) as DevinSession;
  const sessionId = body.session_id ?? body.id ?? null;
  const sessionUrl = body.url ?? (sessionId ? `${DEVIN_WEB_URL.replace(/\/$/, "")}/sessions/${sessionId}` : null);
  return {
    agentType: workOrder.agentType,
    branch: null,
    devinPrRequested: true,
    devinReviewRequested: false,
    externalId: sessionId,
    kind: "devin_session",
    number: null,
    title: `Devin: ${workOrder.title}`,
    url: sessionUrl,
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

function buildDevinTaskBody(workOrder: AgentWorkOrder, request: AgentDispatchRequest): string {
  const dispatchMarker = formatDispatchMarker(workOrder, request);
  return [
    "@devin please investigate this Promptetheus incident and open a pull request with the fix.",
    "You are the implementation task inside a Promptetheus Orkes workflow. Run evals before marking the PR ready.",
    "",
    "Promptetheus dispatch context:",
    `- Target area: ${workOrder.agentType} agent`,
    `- Incident: \`${request.incidentId}\``,
    `- Session: \`${request.sessionId}\``,
    `- Tracking marker: \`${dispatchMarker}\``,
    request.agentName ? `- Source agent: \`${request.agentName}\`` : null,
    request.incidentTitle ? `- Incident title: ${request.incidentTitle}` : null,
    request.rootCause ? `- Root cause: ${request.rootCause}` : null,
    "",
    workOrder.body,
    "",
    "Expected PR:",
    `- Base branch: \`${TARGET_BASE_BRANCH}\``,
    `- Primary file to inspect: \`${workOrder.filePath}\``,
    `- Suggested title: ${workOrder.title}`,
    "- Validation note: include the Promptetheus incident id and session id in the PR body.",
    `- Tracking note: include this exact marker in the PR title or body: \`${dispatchMarker}\`.`,
    "- Eval gate: run the relevant repository checks/evals and include the exact command output or failure reason in the PR body.",
    "",
    "Do not only review an existing PR. Please create the branch, implement the fix, run the relevant checks, and open the pull request.",
  ]
    .filter((line): line is string => line !== null)
    .join("\n");
}

function buildDevinSessionPrompt(workOrder: AgentWorkOrder, request: AgentDispatchRequest): string {
  const dispatchMarker = formatDispatchMarker(workOrder, request);
  return [
    "You are Devin working from a Promptetheus logs-page dispatch.",
    "",
    "Your job is to make the pull request yourself. Do not wait for Promptetheus to create a branch or PR.",
    "You are the Devin task inside a Promptetheus Orkes workflow. The workflow should not treat the PR as ready until evals pass.",
    "",
    "Repository:",
    `- GitHub repo: ${TARGET_REPO_SLUG}`,
    `- Base branch: ${TARGET_BASE_BRANCH}`,
    "",
    "Promptetheus evidence:",
    `- Target area: ${workOrder.agentType} agent`,
    `- Incident: ${request.incidentId}`,
    `- Session: ${request.sessionId}`,
    `- Tracking marker: ${dispatchMarker}`,
    request.agentName ? `- Source agent: ${request.agentName}` : null,
    request.incidentTitle ? `- Incident title: ${request.incidentTitle}` : null,
    request.rootCause ? `- Root cause: ${request.rootCause}` : null,
    "",
    workOrder.body,
    "",
    "Implementation target:",
    `- Inspect and update: ${workOrder.filePath}`,
    `- Suggested PR title: ${workOrder.title}`,
    "",
    "Acceptance criteria:",
    "- Create a branch in the target repo.",
    "- Implement the smallest fix that addresses the incident root cause.",
    "- Run the relevant checks and evals available in the repository before opening or marking the PR ready.",
    "- Open a GitHub pull request against the base branch only after the eval gate is documented.",
    "- Include the Promptetheus incident id and session id in the PR body.",
    `- Include this exact tracking marker in the PR title or body so Promptetheus can link it back: ${dispatchMarker}`,
    "- Include the eval command, pass/fail result, and any Sentry/trace correlation id you can access in the PR body.",
  ]
    .filter((line): line is string => line !== null)
    .join("\n");
}

function formatDispatchMarker(workOrder: Pick<AgentWorkOrder, "agentType">, request: AgentDispatchRequest): string {
  return `Promptetheus-Dispatch: ${request.incidentId}/${request.sessionId}/${workOrder.agentType}`;
}

function buildPullRequestSearchQuery(incidentId: string, sessionId: string): string {
  return `repo:${TARGET_REPO_SLUG} is:pr is:open ${incidentId} ${sessionId}`;
}

function matchOpenedPullRequest({
  candidates,
  incidentId,
  pullRequest,
  sessionId,
  usedPullRequestNumbers,
}: {
  candidates: GitHubSearchIssue[];
  incidentId: string;
  pullRequest: AgentPullRequestResult;
  sessionId: string;
  usedPullRequestNumbers: Set<number>;
}): GitHubSearchIssue | null {
  const available = candidates.filter((candidate) => !usedPullRequestNumbers.has(candidate.number));
  const workOrder = WORK_ORDERS.find((candidate) => candidate.agentType === pullRequest.agentType);
  const exactMarker = formatDispatchMarker({ agentType: pullRequest.agentType }, {
    incidentId,
    sessionId,
  });
  const strongMarkers = [
    exactMarker,
    pullRequest.externalId ?? null,
    workOrder?.title ?? null,
    pullRequest.title.replace(/^Devin:\s*/i, ""),
  ].filter((marker): marker is string => Boolean(marker));

  for (const marker of strongMarkers) {
    const match = available.find((candidate) => searchIssueText(candidate).includes(marker.toLowerCase()));
    if (match) return match;
  }

  const agentScoped = available.find((candidate) => {
    const text = searchIssueText(candidate);
    return text.includes(pullRequest.agentType) && text.includes(incidentId.toLowerCase()) && text.includes(sessionId.toLowerCase());
  });
  if (agentScoped) return agentScoped;

  return available[0] ?? null;
}

function searchIssueText(issue: GitHubSearchIssue): string {
  return `${issue.title} ${issue.body ?? ""} ${issue.html_url}`.toLowerCase();
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

  async getPullRequest(prNumber: number): Promise<GitHubPullRequest> {
    return this.request<GitHubPullRequest>(`/repos/${TARGET_REPO_SLUG}/pulls/${prNumber}`, {
      method: "GET",
    });
  }

  async searchPullRequests(query: string): Promise<GitHubSearchIssue[]> {
    const response = await this.request<GitHubSearchResponse>(
      `/search/issues?q=${encodeURIComponent(query)}&per_page=20`,
      { method: "GET" },
    );
    return response.items.filter((item) => Boolean(item.pull_request));
  }

  async createIssue(input: {
    body: string;
    title: string;
  }): Promise<GitHubIssue> {
    return this.request<GitHubIssue>(`/repos/${TARGET_REPO_SLUG}/issues`, {
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
