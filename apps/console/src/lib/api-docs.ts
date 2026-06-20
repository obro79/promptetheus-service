import { EVENT_SCHEMA_JSON, EVENT_TYPES } from "@/lib/schema";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH";

export type AuthMode = "api_key_or_jwt" | "jwt" | "server_only";

export type DocsCodeLanguage = "bash" | "http" | "json" | "python" | "text";

export interface DocsCodeExample {
  id: string;
  label: string;
  language: DocsCodeLanguage;
  filename?: string;
  code: string;
}

export interface ApiEndpoint {
  id: string;
  method: HttpMethod;
  path: string;
  group: "Ingestion" | "Replay" | "Analysis" | "Stream" | "Artifacts" | "Incidents" | "Fix" | "Regression";
  auth: AuthMode;
  purpose: string;
  request: string;
  response: string;
  notes: string[];
}

export interface AuthDoc {
  id: AuthMode;
  label: string;
  credential: string;
  usedBy: string;
  description: string;
  header?: string;
}

export interface QuickstartStep {
  id: string;
  title: string;
  description: string;
  examples: DocsCodeExample[];
}

export interface EventEnvelopeField {
  name: string;
  type: string;
  required: boolean;
  description: string;
}

export interface EventPayloadField {
  name: string;
  type: string;
  description?: string;
}

export interface EventTypeDoc {
  type: (typeof EVENT_TYPES)[number];
  reserved: boolean;
  summary: string;
  fields: EventPayloadField[];
}

export interface ErrorDoc {
  status: number;
  label: string;
  meaning: string;
  retry: "no" | "after_fix" | "backoff" | "conditional";
}

export const apiDocsOverview = {
  title: "Promptetheus API",
  subtitle:
    "Instrument agent runs, ingest trace events, replay the exact bad step, and drive analysis, fix-agent, and regression workflows through FastAPI.",
  contractStatus:
    "State 0 locks the 14-endpoint API, the event envelope, standard errors, and private artifact contract before parallel implementation work.",
  baseUrls: [
    { label: "Local", url: "http://127.0.0.1:4318" },
    { label: "Hosted", url: "Railway service URL; hosted product mirrors the same bodies under /v1/projects/{project_id}/..." },
  ],
  invariants: [
    "FastAPI is the write gateway for all trace-derived state.",
    "Supabase Postgres and private Supabase Storage are canonical storage.",
    "Every request resolves a workspace from API key, Supabase JWT, or server-only credentials.",
    "Trace event order is (session_id, seq), never client timestamp.",
    "The SDK may spool failed deliveries locally, but replay always goes back through FastAPI.",
  ],
} as const;

export const authDocs: AuthDoc[] = [
  {
    id: "api_key_or_jwt",
    label: "Project API key or console JWT",
    credential: "Authorization: Bearer <project_api_key | supabase_jwt>",
    usedBy: "SDK ingestion, raw HTTP ingestion, and console-triggered writes where allowed",
    description:
      "Project API keys resolve to workspace_id and project_id on the server. Console calls use the user's Supabase session JWT.",
    header: "Authorization: Bearer pt_dev_key",
  },
  {
    id: "jwt",
    label: "Supabase session JWT",
    credential: "Authorization: Bearer <supabase_jwt>",
    usedBy: "Console reads, SSE, artifact redirects, incident workflow actions",
    description:
      "JWT requests are workspace-filtered. Optional project_id and session_id filters narrow the visible data, never broaden it.",
    header: "Authorization: Bearer pt_console_token",
  },
  {
    id: "server_only",
    label: "Server-only credential",
    credential: "Internal FastAPI or trusted server token",
    usedBy: "Analysis result writeback and other internal workflow persistence",
    description:
      "Service-role credentials and provider tokens never leave server-side FastAPI or trusted Next.js routes, and still pass explicit workspace checks.",
  },
];

export const standardHeaders = [
  {
    name: "Authorization",
    value: "Bearer <token>",
    appliesTo: "All authenticated endpoints",
  },
  {
    name: "Content-Type",
    value: "application/json",
    appliesTo: "JSON requests and event batches",
  },
  {
    name: "Idempotency-Key",
    value: "<stable-write-key>",
    appliesTo: "Idempotent writes; event batches may also use per-event idempotency_key",
  },
  {
    name: "Last-Event-ID",
    value: "<session_id>:<seq> or <seq>",
    appliesTo: "SSE reconnect; after_seq query parameter is also supported",
  },
] as const;

export const apiEndpoints: ApiEndpoint[] = [
  {
    id: "create-trace",
    method: "POST",
    path: "/api/traces",
    group: "Ingestion",
    auth: "api_key_or_jwt",
    purpose: "Create a trace_session for an agent run.",
    request: "Trace identity, user_goal, agent identity, project context, and optional caller-supplied id.",
    response: "Created trace_session with workspace/project scope and timestamps.",
    notes: ["The SDK calls this before event delivery when starting a session."],
  },
  {
    id: "append-events",
    method: "POST",
    path: "/api/traces/{id}/events",
    group: "Ingestion",
    auth: "api_key_or_jwt",
    purpose: "Append one event or a batch of events, validate schema, persist rows, and rebroadcast SSE.",
    request: "Either { events: PromptetheusEvent[] } or one PromptetheusEvent object.",
    response: "{ accepted: number, rejected: [{ index, idempotency_key, reason }] }",
    notes: [
      "Valid events in a mixed batch are accepted even when other events are rejected.",
      "The SDK dead-letters only rejected events; accepted events are not retried.",
    ],
  },
  {
    id: "upload-artifact",
    method: "POST",
    path: "/api/traces/{id}/artifacts",
    group: "Artifacts",
    auth: "api_key_or_jwt",
    purpose: "Upload or register replay and screenshot artifacts in private Supabase Storage.",
    request: "Artifact content plus content_type, size_bytes, filename, artifact_type, and optional event_time_map.",
    response: "Artifact id, storage_path, content_type, size_bytes, artifact_type, and timing metadata.",
    notes: [
      "Artifact event payloads carry artifact_id and storage_path, never public URLs.",
      "Oversized artifacts return 413; unsupported content types return 415.",
    ],
  },
  {
    id: "list-sessions",
    method: "GET",
    path: "/api/sessions",
    group: "Replay",
    auth: "jwt",
    purpose: "List workspace/project-scoped sessions for the console.",
    request: "Optional project, status, time range, and pagination filters.",
    response: "Ordered trace_session summaries visible to the caller's workspace.",
    notes: ["This is a read endpoint; trace mutations still go through FastAPI write routes."],
  },
  {
    id: "read-events",
    method: "GET",
    path: "/api/traces/{id}/events",
    group: "Replay",
    auth: "jwt",
    purpose: "Read ordered events for replay and inspection.",
    request: "Trace id plus optional after_seq or pagination filters.",
    response: "PromptetheusEvent[] ordered by (session_id, seq).",
    notes: ["Timeline order never depends on client timestamp."],
  },
  {
    id: "read-analysis",
    method: "GET",
    path: "/api/traces/{id}/analysis",
    group: "Analysis",
    auth: "jwt",
    purpose: "Read the stored analysis result for a session.",
    request: "Trace id visible in the caller's workspace.",
    response: "Analysis labels, critical_step_seq, confidence, root_cause, and incident links.",
    notes: ["The console renders this result; detection logic runs in FastAPI."],
  },
  {
    id: "store-analysis",
    method: "PUT",
    path: "/api/traces/{id}/analysis",
    group: "Analysis",
    auth: "server_only",
    purpose: "Persist analysis results and incident links from server-side analysis workflow.",
    request: "Detector labels, evidence refs, confidence, root_cause, critical_step_seq, and incident linkage.",
    response: "Stored analysis_result and any incident updates.",
    notes: ["This endpoint is not callable by browser clients."],
  },
  {
    id: "stream",
    method: "GET",
    path: "/api/stream",
    group: "Stream",
    auth: "jwt",
    purpose: "Open a workspace-filtered SSE stream for live trace updates.",
    request: "Optional project_id, session_id, and after_seq query parameters.",
    response: "Server-sent events with missed-event backfill followed by live events and heartbeats.",
    notes: [
      "Global stream means workspace-global, not public-global.",
      "Reconnect uses Last-Event-ID or after_seq.",
    ],
  },
  {
    id: "artifact-redirect",
    method: "GET",
    path: "/artifacts/{artifact_id}",
    group: "Artifacts",
    auth: "jwt",
    purpose: "Redirect an authorized console request to a short-lived signed artifact URL.",
    request: "Artifact id visible in the caller's workspace.",
    response: "HTTP redirect to a private Supabase Storage signed URL.",
    notes: ["Clients never receive raw public artifact URLs."],
  },
  {
    id: "analyze-trace",
    method: "POST",
    path: "/api/traces/{id}/analyze",
    group: "Analysis",
    auth: "jwt",
    purpose: "Run deterministic detectors on a session in FastAPI.",
    request: "Trace id and optional analysis options.",
    response: "Analysis result with labels, confidence, evidence refs, critical step, and root cause.",
    notes: ["Same ordered events in means same detector labels, confidences, and critical step."],
  },
  {
    id: "list-incidents",
    method: "GET",
    path: "/api/incidents",
    group: "Incidents",
    auth: "jwt",
    purpose: "List workspace-scoped incident clusters.",
    request: "Optional project, status, severity, owner, and pagination filters.",
    response: "Incident summaries with representative_session_id and current workflow state.",
    notes: ["Incidents cluster trace failures; they are not generic analytics rows."],
  },
  {
    id: "update-incident",
    method: "PATCH",
    path: "/api/incidents/{id}",
    group: "Incidents",
    auth: "jwt",
    purpose: "Update incident status or owner.",
    request: "status in new, triaged, fixing, verified, ignored; optional owner_id.",
    response: "Updated incident row.",
    notes: ["Workspace and project checks apply before mutation."],
  },
  {
    id: "dispatch-fix-agent",
    method: "POST",
    path: "/api/incidents/{id}/fix-agent",
    group: "Fix",
    auth: "jwt",
    purpose: "Dispatch FixAgentRunner and return a plan plus diff or a labeled fallback.",
    request: "Incident id and optional dispatch options.",
    response: "Fix plan, diff summary, GitHub PR link when available, or deterministic fallback output.",
    notes: [
      "GitHub installation tokens stay server-side.",
      "Output is rejected if it changes files outside connected_repo.allowed_paths_json.",
    ],
  },
  {
    id: "run-regression",
    method: "POST",
    path: "/api/incidents/{id}/regression-runs",
    group: "Regression",
    auth: "jwt",
    purpose: "Trigger before/after regression replay for an incident.",
    request: "Incident id, optional PR URL or candidate fix metadata.",
    response: "Stored regression_run with before_pass, before_fail, after_pass, after_fail, and raw results.",
    notes: ["Regression persistence goes through FastAPI with audit logging."],
  },
];

export const standardErrors: ErrorDoc[] = [
  { status: 400, label: "Bad request", meaning: "Malformed request body.", retry: "after_fix" },
  { status: 401, label: "Unauthorized", meaning: "Missing or invalid authentication.", retry: "after_fix" },
  { status: 403, label: "Forbidden", meaning: "Workspace or project mismatch.", retry: "after_fix" },
  { status: 404, label: "Not found", meaning: "Trace or artifact is not visible in the caller's workspace.", retry: "after_fix" },
  { status: 409, label: "Conflict", meaning: "Duplicate seq or idempotency conflict.", retry: "conditional" },
  { status: 413, label: "Payload too large", meaning: "Artifact exceeds configured size limits.", retry: "after_fix" },
  { status: 415, label: "Unsupported media type", meaning: "Artifact content type is not supported.", retry: "after_fix" },
  { status: 422, label: "Validation error", meaning: "Schema validation failed for the event or request.", retry: "after_fix" },
  { status: 429, label: "Rate limited", meaning: "Burst or backpressure limit.", retry: "backoff" },
  { status: 500, label: "Server error", meaning: "Unexpected server error with request id.", retry: "backoff" },
];

export const eventEnvelopeFields: EventEnvelopeField[] = [
  {
    name: "type",
    type: "EventType",
    required: true,
    description: "One of the event types exported by schema.py and mirrored in the console schema.",
  },
  {
    name: "session_id",
    type: "string",
    required: true,
    description: "Trace session id. The SDK generates one when callers do not provide one.",
  },
  {
    name: "timestamp",
    type: "ISO 8601 string",
    required: true,
    description: "Client clock timestamp. Informational only; ordering uses seq.",
  },
  {
    name: "seq",
    type: "integer >= 0",
    required: true,
    description: "Monotonic per-session sequence number assigned before enqueue.",
  },
  {
    name: "idempotency_key",
    type: "string",
    required: true,
    description: "Stable retry key, normally <session_id>:<instance_nonce>:<seq>.",
  },
  {
    name: "payload",
    type: "object",
    required: true,
    description: "Event-specific payload object.",
  },
  {
    name: "metadata",
    type: "object",
    required: false,
    description: "Optional metadata object. SDK helpers take metadata explicitly, not open kwargs.",
  },
  {
    name: "span_id",
    type: "string",
    required: false,
    description: "Optional run-tree span id for events emitted inside a Session.span block.",
  },
  {
    name: "parent_id",
    type: "string | null",
    required: false,
    description: "Optional enclosing span id. Timeline order still uses seq.",
  },
];

const EVENT_SUMMARIES: Record<(typeof EVENT_TYPES)[number], string> = {
  user_message: "User input or instruction captured in the trace.",
  agent_message: "Agent response or claim, including terminal success claims.",
  tool_call: "Tool invocation with tool_name, arguments, and optional call_id.",
  tool_result: "Tool result or tool error associated with a call_id.",
  retrieval: "Retrieval query plus returned document metadata.",
  browser_action: "Browser click, fill, navigation, submit, or related UI action.",
  dom_snapshot: "Observed browser state, visible text, selected values, and warnings.",
  screenshot: "Screenshot artifact reference or staged screenshot source.",
  replay_artifact: "Replay artifact identity and event time map for private storage.",
  goal_check: "Explicit user-goal verdict emitted by the agent or test harness.",
  state_change: "Named state transition, including span_start and span_end markers.",
  session_end: "Terminal session status event used as the canonical status transition.",
  llm_call: "Reserved event type for future LLM framework adapters.",
  score: "Human or automated score attached to the session.",
  error: "Captured exception or handled error richer than a tool_result error string.",
  metric: "Numeric metric emitted during the run.",
};

function schemaType(definition: unknown): string {
  if (!definition || typeof definition !== "object") return "any";

  const def = definition as {
    type?: string | readonly string[];
    enum?: readonly unknown[];
    $ref?: string;
    items?: { type?: string };
    additionalProperties?: { type?: string } | boolean;
  };

  if (def.$ref) return def.$ref;
  if (Array.isArray(def.enum)) return def.enum.map((value) => JSON.stringify(value)).join(" | ");
  if (Array.isArray(def.type)) return def.type.join(" | ");
  if (def.type === "array" && def.items?.type) return `${def.items.type}[]`;
  if (def.type === "object" && typeof def.additionalProperties === "object" && def.additionalProperties.type) {
    return `Record<string, ${def.additionalProperties.type}>`;
  }
  if (typeof def.type === "string") return def.type;
  return "any";
}

function eventPayloadFields(type: (typeof EVENT_TYPES)[number]): EventPayloadField[] {
  const events = EVENT_SCHEMA_JSON.events as Record<
    string,
    { properties?: Record<string, unknown>; reserved?: boolean }
  >;
  const properties = events[type]?.properties;
  if (!properties) return [];

  return Object.entries(properties).map(([name, definition]) => ({
    name,
    type: schemaType(definition),
  }));
}

export const eventTypeDocs: EventTypeDoc[] = EVENT_TYPES.map((type) => {
  const events = EVENT_SCHEMA_JSON.events as Record<string, { reserved?: boolean }>;
  return {
    type,
    reserved: Boolean(events[type]?.reserved),
    summary: EVENT_SUMMARIES[type],
    fields: eventPayloadFields(type),
  };
});

export const schemaDocs = {
  sourceOfTruth: "packages/promptetheus/promptetheus/schema.py",
  consoleMirror: "apps/console/src/lib/schema.ts",
  orderingRule: "Order by (session_id, seq), never by timestamp.",
  batchResponse: "{ accepted: number, rejected: [{ index, idempotency_key, reason }] }",
  envelopeFields: eventEnvelopeFields,
  eventTypes: eventTypeDocs,
  rawSchema: EVENT_SCHEMA_JSON,
} as const;

const CREATE_TRACE_CURL = `curl -sS -X POST http://127.0.0.1:4318/api/traces \\
  -H "Authorization: Bearer pt_dev_key" \\
  -H "Content-Type: application/json" \\
  -d '{"user_goal":"Book a room for Tuesday","agent":"demo-agent","id":"trace_curl_1"}'`;

const APPEND_EVENTS_CURL = `curl -sS -X POST http://127.0.0.1:4318/api/traces/trace_curl_1/events \\
  -H "Authorization: Bearer pt_dev_key" \\
  -H "Content-Type: application/json" \\
  -d '{
    "events": [{
      "type": "user_message",
      "session_id": "trace_curl_1",
      "timestamp": "2026-01-01T00:00:00Z",
      "seq": 0,
      "idempotency_key": "trace_curl_1:dev:0",
      "payload": {"content": "Book Tuesday"}
    }]
  }'`;

const PYTHON_HTTP_EXAMPLE = `import os
import httpx

user_goal = "Book Tuesday at 2pm Pacific, but stop at confirmation"
api_url = os.environ.get("PROMPTETHEUS_API_URL", "http://127.0.0.1:4318")
headers = {
    "Authorization": f"Bearer {os.environ['PROMPTETHEUS_API_KEY']}",
    "Content-Type": "application/json",
}

with httpx.Client(base_url=api_url, headers=headers) as client:
    client.post(
        "/api/traces",
        json={
            "id": "trace_python_1",
            "agent": "browser-agent",
            "project_id": "proj_acmemeet",
            "user_goal": user_goal,
        },
    ).raise_for_status()

    client.post(
        "/api/traces/trace_python_1/events",
        json={
            "events": [
                {
                    "type": "user_message",
                    "session_id": "trace_python_1",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "seq": 0,
                    "idempotency_key": "trace_python_1:dev:0",
                    "payload": {"content": user_goal},
                },
                {
                    "type": "goal_check",
                    "session_id": "trace_python_1",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "seq": 1,
                    "idempotency_key": "trace_python_1:dev:1",
                    "payload": {
                        "passed": False,
                        "mismatches": ["Selected 2:00 AM instead of 2:00 PM"],
                    },
                },
            ]
        },
    ).raise_for_status()`;

const RAW_EVENT_JSON = `{
  "type": "goal_check",
  "session_id": "trace_curl_1",
  "timestamp": "2026-01-01T00:00:01Z",
  "seq": 1,
  "idempotency_key": "trace_curl_1:dev:1",
  "payload": {
    "passed": false,
    "mismatches": ["Selected 2:00 AM instead of 2:00 PM"]
  }
}`;

export const quickstartSteps: QuickstartStep[] = [
  {
    id: "install",
    title: "Install and configure",
    description:
      "Run the service locally on Python 3.12+ with PROMPTETHEUS_API_KEY and optional PROMPTETHEUS_API_URL.",
    examples: [
      {
        id: "install-client",
        label: "Install HTTP client",
        language: "bash",
        filename: "shell",
        code: "pip install httpx",
      },
      {
        id: "env",
        label: "Local environment",
        language: "bash",
        filename: ".env",
        code: 'PROMPTETHEUS_API_URL="http://127.0.0.1:4318"\nPROMPTETHEUS_API_KEY="pt_dev_key"',
      },
    ],
  },
  {
    id: "python-http",
    title: "Emit with Python HTTP",
    description:
      "Create a trace, then append schema-conformant events through the FastAPI ingestion gateway.",
    examples: [
      {
        id: "python-http-client",
        label: "HTTP ingestion",
        language: "python",
        filename: "agent.py",
        code: PYTHON_HTTP_EXAMPLE,
      },
    ],
  },
  {
    id: "raw-http",
    title: "Or post raw HTTP",
    description:
      "Any stack can create a trace and POST schema-conformant events to the FastAPI endpoints.",
    examples: [
      {
        id: "create-trace-curl",
        label: "Create trace",
        language: "bash",
        filename: "curl",
        code: CREATE_TRACE_CURL,
      },
      {
        id: "append-events-curl",
        label: "Append event batch",
        language: "bash",
        filename: "curl",
        code: APPEND_EVENTS_CURL,
      },
      {
        id: "raw-event-json",
        label: "Single event envelope",
        language: "json",
        filename: "event.json",
        code: RAW_EVENT_JSON,
      },
    ],
  },
];

export const sdkExamples: DocsCodeExample[] = [
  {
    id: "python-http-client",
    label: "Python HTTP client",
    language: "python",
    filename: "agent.py",
    code: PYTHON_HTTP_EXAMPLE,
  },
  {
    id: "artifact-upload",
    label: "Artifact upload",
    language: "bash",
    filename: "curl",
    code: `curl -sS -X POST http://127.0.0.1:4318/api/traces/trace_curl_1/artifacts \\
  -H "Authorization: Bearer pt_dev_key" \\
  -H "Content-Type: image/png" \\
  -H "X-Promptetheus-Filename: screenshot.png" \\
  -H "X-Promptetheus-Artifact-Type: screenshot" \\
  --data-binary @screenshot.png`,
  },
  {
    id: "generic-event",
    label: "Generic event batch",
    language: "json",
    filename: "events.json",
    code: `{
  "events": [{
    "type": "llm_call",
    "session_id": "trace_curl_1",
    "timestamp": "2026-01-01T00:00:02Z",
    "seq": 2,
    "idempotency_key": "trace_curl_1:dev:2",
    "payload": {
        "model": "gpt-5",
        "prompt_ref": "prompt_01",
        "input_tokens": 240,
        "output_tokens": 80,
        "latency_ms": 1260
    }
  }]
}`,
  },
];

export const rawHttpExamples: DocsCodeExample[] = [
  {
    id: "create-trace",
    label: "Create trace",
    language: "bash",
    filename: "curl",
    code: CREATE_TRACE_CURL,
  },
  {
    id: "append-events",
    label: "Append events",
    language: "bash",
    filename: "curl",
    code: APPEND_EVENTS_CURL,
  },
  {
    id: "analyze",
    label: "Analyze with console JWT",
    language: "bash",
    filename: "curl",
    code: `curl -sS -X POST http://127.0.0.1:4318/api/traces/trace_curl_1/analyze \\
  -H "Authorization: Bearer pt_console_token"`,
  },
];

export const sseDocs = {
  path: "/api/stream?project_id=...&session_id=...&after_seq=...",
  auth: "Supabase session JWT",
  filters: ["workspace_id from JWT", "optional project_id", "optional session_id", "optional after_seq"],
  reconnect: "Use Last-Event-ID or after_seq; the server backfills missed events before live events.",
  constraints: [
    "Heartbeats keep connections open.",
    "Per-client buffers are bounded.",
    "State 0 live fan-out is in-process pub/sub on a single FastAPI instance.",
    "Postgres backfill by (session_id, seq) makes pub/sub a latency optimization, not canonical storage.",
  ],
} as const;

export const artifactDocs = {
  storage: "Private Supabase Storage bucket",
  pathPattern: "artifacts/<workspace_id>/<session_id>/<artifact_id>/<filename>",
  access: "GET /artifacts/{artifact_id} returns a short-lived signed URL after workspace authorization.",
  rules: [
    "Artifact events carry storage identity, not public URLs.",
    "content_type, size_bytes, artifact_type, and event_time_map are persisted with the artifact row.",
    "Retention cleanup removes both database rows and storage objects according to project policy.",
  ],
} as const;

export const detectorDocs = [
  {
    label: "browser_goal_mismatch",
    summary:
      "Fires on an explicit failed goal_check or a contradiction between user_goal constraints and the final dom_snapshot.selected_values.",
    confidence: "0.9 explicit failed goal_check; 0.7 structured selected_values contradiction; 0.5 text-only disagreement.",
  },
  {
    label: "ignored_ui_warning",
    summary:
      "Fires when a warning-bearing dom_snapshot is followed by progressing browser_action events without addressing the warning.",
    confidence: "0.9 when the warning persists into final submit or confirm; 0.6 for positional transient warnings.",
  },
  {
    label: "false_success_claim",
    summary:
      "Fires when a terminal agent_message asserts success while goal mismatch or failed goal_check evidence exists.",
    confidence: "0.95 with a high-confidence mismatch; 0.6 with only low-confidence mismatch evidence.",
  },
  {
    label: "forbidden_action",
    summary:
      "Fires when browser_action crosses a stop or limit boundary parsed from the user_goal.",
    confidence: "0.9 selector-level boundary match; 0.6 visible-text heuristic match.",
  },
] as const;

export const apiDocs = {
  overview: apiDocsOverview,
  auth: authDocs,
  headers: standardHeaders,
  quickstart: quickstartSteps,
  endpoints: apiEndpoints,
  schema: schemaDocs,
  errors: standardErrors,
  sdkExamples,
  rawHttpExamples,
  sse: sseDocs,
  artifacts: artifactDocs,
  detectors: detectorDocs,
} as const;
