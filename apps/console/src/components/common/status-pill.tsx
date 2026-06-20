import * as React from "react";

import type { IncidentStatus, SessionStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

type AnyStatus = SessionStatus | IncidentStatus;

const STATUS_CONFIG: Record<
  AnyStatus,
  { label: string; dot: string; text: string; pulse?: boolean }
> = {
  // SessionStatus
  running: {
    label: "Running",
    dot: "bg-accent",
    text: "text-accent",
    pulse: true,
  },
  passed: { label: "Passed", dot: "bg-success", text: "text-success" },
  failed: { label: "Failed", dot: "bg-warning", text: "text-warning" },
  error: { label: "Error", dot: "bg-warning", text: "text-warning" },
  // IncidentStatus
  open: { label: "Open", dot: "bg-warning", text: "text-warning" },
  triaged: { label: "Triaged", dot: "bg-warning", text: "text-warning" },
  fixing: {
    label: "Fixing",
    dot: "bg-accent",
    text: "text-accent",
    pulse: true,
  },
  fixed: { label: "Fixed", dot: "bg-success", text: "text-success" },
  ignored: {
    label: "Ignored",
    dot: "bg-muted-foreground",
    text: "text-muted-foreground",
  },
};

export interface StatusPillProps extends React.HTMLAttributes<HTMLSpanElement> {
  status: AnyStatus;
}

export function StatusPill({ status, className, ...props }: StatusPillProps) {
  const config = STATUS_CONFIG[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs font-medium",
        config.text,
        className,
      )}
      {...props}
    >
      <span className="relative flex size-1.5">
        {config.pulse ? (
          <span
            className={cn(
              "absolute inline-flex size-full animate-ping rounded-full opacity-60",
              config.dot,
            )}
          />
        ) : null}
        <span
          className={cn(
            "relative inline-flex size-1.5 rounded-full",
            config.dot,
          )}
        />
      </span>
      {config.label}
    </span>
  );
}
