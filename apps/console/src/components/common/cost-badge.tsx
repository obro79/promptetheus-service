import * as React from "react";
import { Coins } from "lucide-react";

import { cn } from "@/lib/utils";

export interface CostBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tokens?: number;
  usd?: number;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function fmtUsd(n: number): string {
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

export function CostBadge({
  tokens,
  usd,
  className,
  ...props
}: CostBadgeProps) {
  const hasTokens = typeof tokens === "number";
  const hasUsd = typeof usd === "number";
  if (!hasTokens && !hasUsd) return null;

  return (
    <span
      className={cn(
        "mono inline-flex items-center gap-1 rounded-md bg-elevated px-2 py-1 text-[11px] leading-none text-muted-foreground tabular-nums",
        className,
      )}
      {...props}
    >
      <Coins className="size-3 text-muted-foreground/70" />
      {hasTokens ? (
        <span className="text-foreground">{fmtTokens(tokens)}</span>
      ) : null}
      {hasTokens ? <span className="text-muted-foreground/60">tok</span> : null}
      {hasTokens && hasUsd ? (
        <span className="text-muted-foreground/40">·</span>
      ) : null}
      {hasUsd ? <span className="text-foreground">{fmtUsd(usd)}</span> : null}
    </span>
  );
}
