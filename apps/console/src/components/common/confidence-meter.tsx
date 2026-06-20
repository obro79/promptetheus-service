import * as React from "react";

import { cn, pct } from "@/lib/utils";

export interface ConfidenceMeterProps
  extends React.HTMLAttributes<HTMLDivElement> {
  /** 0..1 */
  value: number;
  showLabel?: boolean;
}

export function ConfidenceMeter({
  value,
  showLabel = true,
  className,
  ...props
}: ConfidenceMeterProps) {
  const clamped = Math.max(0, Math.min(1, value));
  const tone =
    clamped >= 0.75
      ? "bg-accent"
      : clamped >= 0.4
        ? "bg-warning"
        : "bg-muted-foreground";

  return (
    <div
      className={cn("flex items-center gap-2", className)}
      {...props}
    >
      <div className="h-1.5 w-full min-w-[3rem] overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all duration-300", tone)}
          style={{ width: `${clamped * 100}%` }}
        />
      </div>
      {showLabel ? (
        <span className="mono shrink-0 text-xs tabular-nums text-muted-foreground">
          {pct(clamped)}
        </span>
      ) : null}
    </div>
  );
}
