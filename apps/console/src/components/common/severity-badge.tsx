import * as React from "react";
import { AlertOctagon, AlertTriangle, Info, Minus } from "lucide-react";

import type { Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEVERITY_CONFIG: Record<
  Severity,
  { label: string; className: string; Icon: React.ComponentType<{ className?: string }> }
> = {
  critical: {
    label: "Critical",
    className: "border-warning/30 bg-warning/10 text-warning",
    Icon: AlertOctagon,
  },
  high: {
    label: "High",
    className: "border-warning/30 bg-warning/10 text-warning",
    Icon: AlertTriangle,
  },
  medium: {
    label: "Medium",
    className: "border-border/60 bg-elevated/70 text-muted-foreground",
    Icon: Info,
  },
  low: {
    label: "Low",
    className: "border-border/50 bg-muted/70 text-muted-foreground",
    Icon: Minus,
  },
};

export interface SeverityBadgeProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  severity: Severity;
  showIcon?: boolean;
}

export function SeverityBadge({
  severity,
  showIcon = true,
  className,
  ...props
}: SeverityBadgeProps) {
  const { label, className: tone, Icon } = SEVERITY_CONFIG[severity];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold leading-none",
        tone,
        className,
      )}
      {...props}
    >
      {showIcon ? <Icon className="size-3" /> : null}
      {label}
    </span>
  );
}
