import { NextResponse } from "next/server";

import {
  checkDevinOpenedPullRequests,
  type AgentPrDispatchResult,
  type AgentPrStatusRequest,
} from "@/lib/agent-execution";

export const runtime = "nodejs";

export async function POST(request: Request) {
  let payload: Partial<AgentPrStatusRequest>;

  try {
    payload = (await request.json()) as Partial<AgentPrStatusRequest>;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  if (!payload.incidentId || !payload.sessionId || !isAgentDispatchResult(payload.dispatchResult)) {
    return NextResponse.json(
      { error: "incidentId, sessionId, and dispatchResult are required." },
      { status: 400 },
    );
  }

  try {
    const result = await checkDevinOpenedPullRequests({
      dispatchResult: payload.dispatchResult,
      incidentId: payload.incidentId,
      sessionId: payload.sessionId,
    });
    return NextResponse.json(result);
  } catch (caught) {
    return NextResponse.json(
      {
        error: caught instanceof Error ? caught.message : "Unable to track Devin PRs.",
      },
      { status: 500 },
    );
  }
}

function isAgentDispatchResult(value: unknown): value is AgentPrDispatchResult {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as AgentPrDispatchResult).pullRequests) &&
    typeof (value as AgentPrDispatchResult).targetRepo === "string"
  );
}
