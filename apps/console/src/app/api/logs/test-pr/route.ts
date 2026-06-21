import { NextResponse } from "next/server";

import {
  createAndCloseLogsTestPullRequest,
  type AgentDispatchRequest,
} from "@/lib/agent-execution";

export const runtime = "nodejs";

export async function POST(request: Request) {
  let payload: Partial<AgentDispatchRequest>;

  try {
    payload = (await request.json()) as Partial<AgentDispatchRequest>;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  if (!payload.incidentId || !payload.sessionId) {
    return NextResponse.json(
      { error: "incidentId and sessionId are required." },
      { status: 400 },
    );
  }

  try {
    const result = await createAndCloseLogsTestPullRequest({
      agentName: payload.agentName ?? null,
      incidentId: payload.incidentId,
      incidentTitle: payload.incidentTitle ?? null,
      rootCause: payload.rootCause ?? null,
      sessionId: payload.sessionId,
    });
    return NextResponse.json(result);
  } catch (caught) {
    return NextResponse.json(
      {
        error: caught instanceof Error ? caught.message : "Unable to create and close test PR.",
      },
      { status: 500 },
    );
  }
}
