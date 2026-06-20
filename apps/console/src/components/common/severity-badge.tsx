import * as React from "react";

import type { Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

export interface SeverityBadgeProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  severity: Severity;
  showIcon?: boolean;
}

export function SeverityBadge({
  severity,
  showIcon: _showIcon = true,
  className,
  ...props
}: SeverityBadgeProps) {
  return (
    <span
      className={cn(
        "mono inline-flex items-center text-[10px] uppercase tracking-[0.16em] text-muted-foreground",
        className,
      )}
      {...props}
    >
      {SEVERITY_LABEL[severity]}
    </span>
  );
}
