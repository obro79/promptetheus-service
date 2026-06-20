import * as React from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { ShieldQuestion } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import {
  LandingAppShell,
  LandingCard,
  LandingSection,
} from "@/components/landing/landing-primitives";
import { Button } from "@/components/ui/button";
import { IncidentDetail } from "@/components/incidents/detail/incident-detail";
import { getIncidentContext } from "@/lib/data";

interface IncidentPageProps {
  params: { id: string };
}

export function generateMetadata({ params }: IncidentPageProps): Metadata {
  const ctx = getIncidentContext(params.id);
  if (!ctx) {
    return { title: "Incident not found · Promptetheus" };
  }
  return {
    title: `${ctx.incident.title} · Incident · Promptetheus`,
    description: ctx.incident.root_cause ?? undefined,
  };
}

export default function IncidentPage({ params }: IncidentPageProps) {
  const context = getIncidentContext(params.id);

  if (!context) {
    return (
      <LandingAppShell>
        <LandingSection
          className="flex min-h-dvh items-center"
          containerClassName="flex justify-center"
        >
          <LandingCard className="w-full max-w-md">
          <EmptyState
            icon={ShieldQuestion}
            title="Incident not found"
            description={`No incident matches “${params.id}”. It may have been resolved and pruned, or the id is wrong.`}
            action={
              <Button asChild variant="secondary" size="sm">
                <Link href="/incidents">Back to incidents</Link>
              </Button>
            }
          />
          </LandingCard>
        </LandingSection>
      </LandingAppShell>
    );
  }

  return <IncidentDetail context={context} />;
}
