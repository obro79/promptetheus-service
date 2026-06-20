import * as React from "react";
import { AlertTriangle, CheckCircle2, Clock3, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface StatusMatrixRow {
  status: number;
  label: string;
  retry: "no" | "safe" | "after-backoff";
  meaning: string;
  action: string;
}

export const DEFAULT_STATUS_MATRIX: StatusMatrixRow[] = [
  {
    status: 200,
    label: "OK",
    retry: "no",
    meaning: "Read completed or SSE connection established.",
    action: "Render the response body.",
  },
  {
    status: 201,
    label: "Created",
    retry: "no",
    meaning: "Session or artifact was created.",
    action: "Store the returned identifier.",
  },
  {
    status: 202,
    label: "Accepted",
    retry: "no",
    meaning: "Batch, analysis, fix-agent, or regression work was queued.",
    action: "Poll the related read endpoint or subscribe to /api/stream.",
  },
  {
    status: 400,
    label: "Bad request",
    retry: "no",
    meaning: "Payload failed schema validation.",
    action: "Fix the request body before retrying.",
  },
  {
    status: 401,
    label: "Unauthorized",
    retry: "no",
    meaning: "Bearer token is missing, expired, or not workspace-scoped.",
    action: "Refresh credentials and resend the request.",
  },
  {
    status: 404,
    label: "Not found",
    retry: "no",
    meaning: "Resource does not exist in this workspace.",
    action: "Check workspace, project, and path identifiers.",
  },
  {
    status: 409,
    label: "Conflict",
    retry: "safe",
    meaning: "Duplicate idempotency key or work already in progress.",
    action: "Reuse the original response or wait for the active run.",
  },
  {
    status: 429,
    label: "Rate limited",
    retry: "after-backoff",
    meaning: "The workspace exceeded a short-term request budget.",
    action: "Back off and retry with the same idempotency key.",
  },
  {
    status: 500,
    label: "Server error",
    retry: "after-backoff",
    meaning: "Unexpected gateway or analysis failure.",
    action: "Retry writes; surface reads as temporarily unavailable.",
  },
];

const RETRY_LABEL: Record<StatusMatrixRow["retry"], string> = {
  no: "Do not retry",
  safe: "Safe retry",
  "after-backoff": "Back off",
};

export interface StatusMatrixProps {
  rows?: StatusMatrixRow[];
  title?: string;
  description?: string;
  className?: string;
}

export function StatusMatrix({
  rows = DEFAULT_STATUS_MATRIX,
  title = "Error and status matrix",
  description = "Use idempotency keys for trace writes so network and gateway retries do not duplicate canonical state.",
  className,
}: StatusMatrixProps) {
  return (
    <section className={cn("overflow-hidden rounded-lg bg-panel", className)}>
      <div className="flex items-start justify-between gap-4 border-b border-border bg-elevated/30 px-4 py-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted-foreground">
            {description}
          </p>
        </div>
        <Badge variant="outline">{rows.length} statuses</Badge>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-elevated/20 text-left">
              <th className="px-3 py-2 text-[11px] font-medium text-muted-foreground">
                Status
              </th>
              <th className="px-3 py-2 text-[11px] font-medium text-muted-foreground">
                Retry
              </th>
              <th className="px-3 py-2 text-[11px] font-medium text-muted-foreground">
                Meaning
              </th>
              <th className="hidden px-3 py-2 text-[11px] font-medium text-muted-foreground lg:table-cell">
                Client action
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.status}
                className="border-b border-border/60 transition-colors duration-150 last:border-0 hover:bg-elevated/40"
              >
                <td className="px-3 py-2 align-middle">
                  <div className="flex items-center gap-2">
                    <StatusIcon status={row.status} />
                    <div className="min-w-0">
                      <div className="mono text-xs font-medium text-foreground">
                        {row.status}
                      </div>
                      <div className="truncate text-[11px] text-muted-foreground">
                        {row.label}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2 align-middle">
                  <RetryBadge retry={row.retry} />
                </td>
                <td className="px-3 py-2 align-middle">
                  <span className="text-xs leading-relaxed text-muted-foreground">
                    {row.meaning}
                  </span>
                </td>
                <td className="hidden px-3 py-2 align-middle lg:table-cell">
                  <span className="text-xs leading-relaxed text-muted-foreground">
                    {row.action}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RetryBadge({ retry }: { retry: StatusMatrixRow["retry"] }) {
  if (retry === "safe") {
    return (
      <Badge variant="success">
        <RefreshCw className="size-3" />
        {RETRY_LABEL[retry]}
      </Badge>
    );
  }

  if (retry === "after-backoff") {
    return (
      <Badge variant="warning">
        <Clock3 className="size-3" />
        {RETRY_LABEL[retry]}
      </Badge>
    );
  }

  return <Badge variant="secondary">{RETRY_LABEL[retry]}</Badge>;
}

function StatusIcon({ status }: { status: number }) {
  if (status >= 200 && status < 300) {
    return <CheckCircle2 className="size-4 shrink-0 text-success" />;
  }

  if (status === 409 || status === 429) {
    return <RefreshCw className="size-4 shrink-0 text-warning" />;
  }

  return <AlertTriangle className="size-4 shrink-0 text-destructive" />;
}
