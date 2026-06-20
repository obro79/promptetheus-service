"use client";

import * as React from "react";
import Link from "next/link";
import { Check, Copy } from "lucide-react";

import { cn, shortId } from "@/lib/utils";

export interface MonoIdProps {
  id: string;
  href?: string;
  /** number of leading chars to keep before truncation. */
  head?: number;
  className?: string;
  /** show the copy affordance (default true). */
  copyable?: boolean;
}

export function MonoId({
  id,
  href,
  head = 8,
  className,
  copyable = true,
}: MonoIdProps) {
  const [copied, setCopied] = React.useState(false);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const handleCopy = React.useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      void navigator.clipboard?.writeText(id).then(() => {
        setCopied(true);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), 1200);
      });
    },
    [id],
  );

  const display = shortId(id, head);

  const label = href ? (
    <Link
      href={href}
      title={id}
      className="mono text-xs text-accent underline-offset-2 transition-colors duration-150 hover:underline"
    >
      {display}
    </Link>
  ) : (
    <span title={id} className="mono text-xs text-muted-foreground">
      {display}
    </span>
  );

  return (
    <span className={cn("group inline-flex items-center gap-1", className)}>
      {label}
      {copyable ? (
        <button
          type="button"
          onClick={handleCopy}
          aria-label={copied ? "Copied" : "Copy id"}
          className="rounded p-0.5 text-muted-foreground/60 opacity-0 transition-all duration-150 hover:bg-elevated hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring group-hover:opacity-100"
        >
          {copied ? (
            <Check className="size-3 text-success" />
          ) : (
            <Copy className="size-3" />
          )}
        </button>
      ) : null}
    </span>
  );
}
