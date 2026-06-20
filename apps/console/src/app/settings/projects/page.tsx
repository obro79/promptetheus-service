import * as React from "react";
import { Settings2 } from "lucide-react";

import { getProjects, getWorkspace } from "@/lib/data";
import { listProjectSettings } from "@/lib/promptetheus-api";
import {
  ConsolePage,
  ConsolePageContent,
  ConsolePageHeader,
  ConsoleEyebrow,
} from "@/components/common/console-primitives";
import { ApiKeyRow } from "@/components/settings/api-key-row";
import { RepoConnection } from "@/components/settings/repo-connection";
import { RetentionControl } from "@/components/settings/retention-control";

export const metadata = {
  title: "Project settings — Promptetheus",
};

export default async function ProjectSettingsPage() {
  const fallbackWorkspace = getWorkspace();
  const remote = await listProjectSettings(fallbackWorkspace);
  const workspace = remote?.workspace ?? fallbackWorkspace;
  const projects = remote?.projects ?? getProjects();

  return (
    <ConsolePage>
      <ConsolePageHeader narrow>
        <div className="min-w-0">
          <ConsoleEyebrow
            icon={<Settings2 className="size-3.5" strokeWidth={1.8} aria-hidden />}
          >
            {workspace.name}
          </ConsoleEyebrow>
          <h1 className="display text-5xl leading-[0.92] text-foreground sm:text-6xl">
            Project settings
          </h1>
          <p className="mt-5 max-w-2xl text-sm leading-6 text-muted-foreground">
            Manage API keys, the connected GitHub repository, and trace
            retention for each project in this workspace.
          </p>
        </div>
      </ConsolePageHeader>

      <ConsolePageContent narrow className="flex flex-col gap-10 py-8">
        {/* API keys */}
        <section>
          <div className="mb-1 flex items-baseline justify-between">
            <h2 className="text-base font-semibold tracking-tight text-foreground">
              API keys
            </h2>
            <span className="mono text-[11px] text-muted-foreground">
              {projects.length}{" "}
              {projects.length === 1 ? "project" : "projects"}
            </span>
          </div>
          <p className="mb-4 max-w-2xl text-xs leading-relaxed text-muted-foreground">
            Used by the SDK to authenticate ingestion. Keys are workspace-scoped
            and shown masked — reveal, copy, or rotate below. Rotating a key
            takes effect immediately.
          </p>
          <div className="space-y-3">
            {projects.map((p) => (
              <ApiKeyRow key={p.id} project={p} />
            ))}
          </div>
        </section>

        {/* Per-project: repo + retention */}
        {projects.map((p) => (
          <section key={p.id}>
            <div className="mb-4 flex items-center gap-2">
              <h2 className="text-base font-semibold tracking-tight text-foreground">
                {p.name}
              </h2>
              <span className="mono rounded-full border border-border/50 bg-elevated px-2.5 py-1 text-[10px] leading-none text-muted-foreground">
                {p.id}
              </span>
            </div>
            <div className="space-y-3">
              <RepoConnection project={p} />
              <RetentionControl project={p} />
            </div>
          </section>
        ))}
      </ConsolePageContent>
    </ConsolePage>
  );
}
