import * as React from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { ShieldQuestion } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
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
      <main className="flex min-h-screen items-center justify-center bg-canvas px-6 py-16">
        <div className="w-full max-w-md">
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
        </div>
      </main>
    );
  }

  return <IncidentDetail context={context} />;
}
