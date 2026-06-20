"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface LiveIndicatorProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  /** number of sessions currently running. */
  count: number;
}

/**
 * Small live badge with a pulsing dot. When nothing is running it falls back to
 * a quiet "idle" state so the feed header never looks broken.
 */
export function LiveIndicator({ count, className, ...props }: LiveIndicatorProps) {
  const live = count > 0;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors duration-150",
        live
          ? "border-accent/30 bg-accent-muted/30 text-accent"
          : "border-border bg-elevated text-muted-foreground",
        className,
      )}
      aria-live="polite"
      {...props}
    >
      <span className="relative flex size-1.5">
        {live ? (
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-70" />
        ) : null}
        <span
          className={cn(
            "relative inline-flex size-1.5 rounded-full",
            live ? "bg-accent" : "bg-muted-foreground",
          )}
        />
      </span>
      {live ? (
        <>
          <span className="mono tabular-nums">{count}</span> running
        </>
      ) : (
        "idle"
      )}
    </span>
  );
}
