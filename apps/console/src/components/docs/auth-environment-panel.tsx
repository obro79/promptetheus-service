import * as React from "react";
import { KeyRound, LockKeyhole, Server } from "lucide-react";

import { CodeBlock } from "@/components/docs/code-block";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface EnvironmentVariable {
  name: string;
  value: string;
  description: string;
  required?: boolean;
}

export interface AuthHeader {
  name: string;
  value: string;
  description: string;
}

export const DEFAULT_ENVIRONMENT_VARIABLES: EnvironmentVariable[] = [
  {
    name: "PROMPTETHEUS_API_KEY",
    value: "pt_live_...",
    description: "Project-scoped key used by SDKs and ingestion clients.",
    required: true,
  },
  {
    name: "PROMPTETHEUS_INGEST_URL",
    value: "https://ingest.promptetheus.dev",
    description: "FastAPI write gateway for sessions, events, artifacts, and analysis.",
    required: true,
  },
  {
    name: "PROMPTETHEUS_PROJECT",
    value: "prj_...",
    description: "Project identifier attached to new trace sessions.",
  },
];

export const DEFAULT_AUTH_HEADERS: AuthHeader[] = [
  {
    name: "Authorization",
    value: "Bearer $PROMPTETHEUS_API_KEY",
    description: "Required for every REST and SSE request.",
  },
  {
    name: "Content-Type",
    value: "application/json",
    description: "Required for JSON request bodies.",
  },
  {
    name: "Idempotency-Key",
    value: "ses_...:seq",
    description: "Recommended for retries on session and event writes.",
  },
];

export interface AuthEnvironmentPanelProps {
  title?: string;
  description?: string;
  variables?: EnvironmentVariable[];
  headers?: AuthHeader[];
  className?: string;
}

export function AuthEnvironmentPanel({
  title = "Auth and environment",
  description = "SDKs send trace-derived state through the FastAPI gateway with a project-scoped bearer key. Console reads use workspace auth.",
  variables = DEFAULT_ENVIRONMENT_VARIABLES,
  headers = DEFAULT_AUTH_HEADERS,
  className,
}: AuthEnvironmentPanelProps) {
  const envCode = variables
    .map((variable) => `${variable.name}=${variable.value}`)
    .join("\n");

  return (
    <section
      className={cn(
        "grid grid-cols-1 overflow-hidden rounded-lg bg-panel lg:grid-cols-[minmax(0,1fr)_22rem]",
        className,
      )}
    >
      <div className="border-b border-border p-4 lg:border-b-0 lg:border-r">
        <div className="mb-4 flex items-start gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">
            <LockKeyhole className="size-4" />
          </span>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground">{title}</h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted-foreground">
              {description}
            </p>
          </div>
        </div>

        <div className="space-y-2">
          {headers.map((header) => (
            <div
              key={header.name}
              className="grid grid-cols-1 gap-2 rounded-lg border border-border/60 bg-canvas/60 p-3 sm:grid-cols-[10rem_minmax(0,1fr)]"
            >
              <div className="flex min-w-0 items-center gap-2">
                <KeyRound className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="mono truncate text-xs text-foreground">
                  {header.name}
                </span>
              </div>
              <div className="min-w-0">
                <div className="mono truncate text-xs text-muted-foreground">
                  {header.value}
                </div>
                <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground/80">
                  {header.description}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <aside className="bg-elevated/30 p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <Server className="size-4 text-muted-foreground" />
            <h4 className="text-xs font-semibold text-foreground">
              Environment
            </h4>
          </div>
          <Badge variant="outline">{variables.length} vars</Badge>
        </div>

        <CodeBlock
          code={envCode}
          language="bash"
          filename=".env.local"
          className="bg-canvas"
          preClassName="max-h-48"
        />

        <dl className="mt-3 space-y-2">
          {variables.map((variable) => (
            <div
              key={variable.name}
              className="rounded-md border border-border/50 bg-panel/70 p-2"
            >
              <dt className="flex min-w-0 items-center justify-between gap-2">
                <span className="mono truncate text-[11px] text-foreground">
                  {variable.name}
                </span>
                {variable.required ? (
                  <Badge variant="accent">required</Badge>
                ) : (
                  <Badge variant="secondary">optional</Badge>
                )}
              </dt>
              <dd className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                {variable.description}
              </dd>
            </div>
          ))}
        </dl>
      </aside>
    </section>
  );
}
