import * as React from "react";
import { ArrowRight, Lock, Radio, ShieldCheck } from "lucide-react";

import { apiDocs, type ApiEndpoint, type AuthMode } from "@/lib/api-docs";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type Endpoint = ApiEndpoint;

const METHOD_TONE: Record<Endpoint["method"], string> = {
  GET: "bg-accent/10 text-accent",
  POST: "bg-success/10 text-success",
  PUT: "bg-warning/10 text-warning",
  PATCH: "bg-warning/10 text-warning",
};

const AUTH_LABEL: Record<AuthMode, string> = {
  api_key_or_jwt: "API key or JWT",
  jwt: "JWT",
  server_only: "Server-only",
};

export interface EndpointMethodBadgeProps {
  method: Endpoint["method"];
  className?: string;
}

export function EndpointMethodBadge({
  method,
  className,
}: EndpointMethodBadgeProps) {
  return (
    <span
      className={cn(
        "mono inline-flex min-w-12 items-center justify-center rounded-md px-1.5 py-1 text-[10px] font-semibold leading-none",
        METHOD_TONE[method],
        className,
      )}
    >
      {method}
    </span>
  );
}

export interface EndpointTableProps {
  endpoints?: Endpoint[];
  className?: string;
  showAuth?: boolean;
  showStatusCodes?: boolean;
}

export function EndpointTable({
  endpoints = apiDocs.endpoints,
  className,
  showAuth = true,
}: EndpointTableProps) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg bg-panel",
        className,
      )}
    >
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border bg-elevated/40 text-left">
            <th className="px-3 py-2 text-[11px] font-medium text-muted-foreground">
              Method
            </th>
            <th className="px-3 py-2 text-[11px] font-medium text-muted-foreground">
              Endpoint
            </th>
            <th className="hidden px-3 py-2 text-[11px] font-medium text-muted-foreground sm:table-cell">
              Group
            </th>
            {showAuth ? (
              <th className="hidden px-3 py-2 text-[11px] font-medium text-muted-foreground md:table-cell">
                Auth
              </th>
            ) : null}
            <th className="px-3 py-2 text-[11px] font-medium text-muted-foreground">
              Purpose
            </th>
          </tr>
        </thead>
        <tbody>
          {endpoints.map((endpoint) => (
            <tr
              key={endpoint.id}
              className="border-b border-border/60 transition-colors duration-150 last:border-0 hover:bg-elevated/40"
            >
              <td className="px-3 py-2 align-top">
                <EndpointMethodBadge method={endpoint.method} />
              </td>
              <td className="px-3 py-2 align-top">
                <span className="mono text-xs text-foreground">{endpoint.path}</span>
              </td>
              <td className="hidden px-3 py-2 align-top sm:table-cell">
                <span className="text-xs text-muted-foreground">{endpoint.group}</span>
              </td>
              {showAuth ? (
                <td className="hidden px-3 py-2 align-top md:table-cell">
                  <EndpointAuthBadge auth={endpoint.auth} />
                </td>
              ) : null}
              <td className="px-3 py-2 align-top">
                <span className="text-xs text-muted-foreground">{endpoint.purpose}</span>
                {endpoint.notes.length > 0 ? (
                  <span className="mt-1 block text-[11px] leading-relaxed text-muted-foreground/75">
                    {endpoint.notes[0]}
                  </span>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface EndpointCardsProps {
  endpoints?: Endpoint[];
  className?: string;
  onEndpointSelect?: (endpoint: Endpoint) => void;
}

export function EndpointCards({
  endpoints = apiDocs.endpoints,
  className,
  onEndpointSelect,
}: EndpointCardsProps) {
  return (
    <div className={cn("grid grid-cols-1 gap-3 md:grid-cols-2", className)}>
      {endpoints.map((endpoint) => (
        <EndpointCard
          key={endpoint.id}
          endpoint={endpoint}
          onSelect={onEndpointSelect}
        />
      ))}
    </div>
  );
}

export interface EndpointCardProps {
  endpoint: Endpoint;
  className?: string;
  onSelect?: (endpoint: Endpoint) => void;
}

export function EndpointCard({
  endpoint,
  className,
  onSelect,
}: EndpointCardProps) {
  const interactive = Boolean(onSelect);
  const Wrapper = interactive ? "button" : "article";

  return (
    <Wrapper
      type={interactive ? "button" : undefined}
      onClick={interactive ? () => onSelect?.(endpoint) : undefined}
      className={cn(
        "group flex min-h-36 w-full flex-col rounded-lg border border-border/70 bg-panel p-3 text-left transition-colors duration-150 hover:border-border-strong hover:bg-elevated/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <EndpointMethodBadge method={endpoint.method} />
          <span className="mono truncate text-xs text-foreground">
            {endpoint.path}
          </span>
        </div>
        {endpoint.path === "/api/stream" ? (
          <Radio className="size-4 shrink-0 text-accent" aria-hidden="true" />
        ) : interactive ? (
          <ArrowRight className="size-4 shrink-0 text-muted-foreground transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-foreground" aria-hidden="true" />
        ) : null}
      </div>

      <p className="mt-3 flex-1 text-xs leading-relaxed text-muted-foreground">
        {endpoint.purpose}
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Badge variant="outline">{endpoint.group}</Badge>
        <EndpointAuthBadge auth={endpoint.auth} />
      </div>
    </Wrapper>
  );
}

function EndpointAuthBadge({ auth }: { auth: AuthMode }) {
  const Icon = auth === "api_key_or_jwt" ? ShieldCheck : Lock;

  return (
    <Badge variant={auth === "api_key_or_jwt" ? "accent" : auth === "server_only" ? "warning" : "secondary"}>
      <Icon className="size-3" aria-hidden="true" />
      {AUTH_LABEL[auth]}
    </Badge>
  );
}
