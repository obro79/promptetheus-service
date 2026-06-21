import type { Metadata } from "next";
import { redirect, notFound } from "next/navigation";

import { getSession } from "@/lib/data";
import { shortId } from "@/lib/utils";

interface LogSessionPageProps {
  params: { sessionId: string };
}

export function generateMetadata({ params }: LogSessionPageProps): Metadata {
  const session = getSession(params.sessionId);
  if (!session) {
    return { title: "Session not found · Logs · Promptetheus" };
  }
  return {
    title: `${session.user_goal ?? shortId(session.id, 12)} · Logs · Promptetheus`,
    description: `Trace waterfall and run inspector for session ${session.id}.`,
  };
}

export default function LogSessionPage({ params }: LogSessionPageProps) {
  const session = getSession(params.sessionId);
  if (!session) notFound();

  redirect(`/logs?session=${encodeURIComponent(params.sessionId)}&agent=${encodeURIComponent(session.project_id)}`);
}
