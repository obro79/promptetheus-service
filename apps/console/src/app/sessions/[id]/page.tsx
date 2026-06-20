import * as React from "react";
import Link from "next/link";
import { FileQuestion } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import {
  LandingAppShell,
  LandingCard,
  LandingSection,
} from "@/components/landing/landing-primitives";
import { Button } from "@/components/ui/button";
import { ReplayView } from "@/components/replay/replay-view";
import {
  getAnalysis,
  getArtifacts,
  getEvents,
  getSession,
} from "@/lib/data";

interface SessionPageProps {
  params: { id: string };
}

export default function SessionPage({ params }: SessionPageProps) {
  const session = getSession(params.id);

  if (!session) {
    return (
      <LandingAppShell>
        <LandingSection
          className="flex min-h-dvh items-center"
          containerClassName="flex justify-center"
        >
          <LandingCard className="w-full max-w-md">
          <EmptyState
            icon={FileQuestion}
            title="Session not found"
            description={`No trace session matches “${params.id}”. It may have been pruned by retention, or the id is wrong.`}
            action={
              <Button asChild variant="secondary" size="sm">
                <Link href="/sessions">Back to sessions</Link>
              </Button>
            }
          />
          </LandingCard>
        </LandingSection>
      </LandingAppShell>
    );
  }

  const events = getEvents(session.id);
  const analysis = getAnalysis(session.id);
  const artifacts = getArtifacts(session.id);

  return (
    <ReplayView
      session={session}
      events={events}
      analysis={analysis}
      artifacts={artifacts}
    />
  );
}
