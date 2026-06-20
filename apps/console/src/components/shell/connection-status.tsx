"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface ConnectionStatusProps {
  /** compact omits the text label, showing only the dot. */
  compact?: boolean;
  className?: string;
}

/**
 * Mock SSE connection indicator. The console subscribes to an authenticated,
 * workspace-filtered /api/stream; here we render the steady "Live" state.
 */
export function ConnectionStatus({ compact = false, className }: ConnectionStatusProps) {
  // Mock: a real client would toggle this from the EventSource readyState.
  const [connected] = React.useState(true);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-[11px] font-medium",
        connected ? "text-accent" : "text-muted-foreground",
        className,
      )}
      title={connected ? "Connected to live event stream" : "Reconnecting…"}
    >
      <span className="relative flex size-1.5">
        {connected ? (
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-60" />
        ) : null}
        <span
          className={cn(
            "relative inline-flex size-1.5 rounded-full",
            connected ? "bg-accent" : "bg-muted-foreground",
          )}
        />
      </span>
      {compact ? null : (
        <span className="mono uppercase tracking-wide">
          {connected ? "Live" : "Offline"}
        </span>
      )}
    </span>
  );
}
