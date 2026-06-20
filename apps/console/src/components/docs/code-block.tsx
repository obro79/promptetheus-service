"use client";

import * as React from "react";
import { Check, Copy, Terminal } from "lucide-react";

import { cn } from "@/lib/utils";

export interface CodeBlockProps {
  code: string;
  /** small label rendered in the header bar, e.g. "bash" / "python". */
  language?: string;
  /** optional filename rendered on the left of the header. */
  filename?: string;
  /** optional short title for the snippet. */
  title?: string;
  /** optional secondary text rendered below the title. */
  description?: string;
  /** optional actions rendered beside the copy button. */
  actions?: React.ReactNode;
  className?: string;
  preClassName?: string;
}

export function CodeBlock({
  code,
  language,
  filename,
  title,
  description,
  actions,
  className,
  preClassName,
}: CodeBlockProps) {
  const [copied, setCopied] = React.useState(false);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const handleCopy = React.useCallback(() => {
    void navigator.clipboard?.writeText(code).then(() => {
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1400);
    });
  }, [code]);

  return (
    <div
      className={cn(
        "group overflow-hidden rounded-lg bg-canvas",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-border bg-panel/60 px-3 py-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <Terminal className="size-3.5 shrink-0 text-muted-foreground/70" />
          <div className="min-w-0">
            {title ? (
              <div className="truncate text-xs font-medium text-foreground">
                {title}
              </div>
            ) : null}
            <div className="flex min-w-0 items-center gap-2">
              <span className="mono truncate text-[11px] text-muted-foreground/80">
                {filename ?? language ?? "code"}
              </span>
              {language && filename ? (
                <span className="mono text-[10px] text-muted-foreground/60">
                  {language}
                </span>
              ) : null}
            </div>
            {description ? (
              <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-muted-foreground">
                {description}
              </p>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {actions}
          <button
            type="button"
            onClick={handleCopy}
            aria-label={copied ? "Copied" : "Copy code"}
            className="inline-flex min-h-7 items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-muted-foreground/70 transition-colors duration-150 hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {copied ? (
              <>
                <Check className="size-3 text-success" />
                <span className="text-success">Copied</span>
              </>
            ) : (
              <>
                <Copy className="size-3" />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>
      <pre
        className={cn(
          "overflow-x-auto px-4 py-3 text-xs leading-relaxed",
          preClassName,
        )}
      >
        <code className="mono text-foreground/90">{code}</code>
      </pre>
    </div>
  );
}

export interface CodeSample {
  id: string;
  title: string;
  code: string;
  language?: string;
  filename?: string;
  description?: string;
}

export interface CodeSampleGridProps {
  samples: CodeSample[];
  className?: string;
}

export function CodeSampleGrid({ samples, className }: CodeSampleGridProps) {
  return (
    <div className={cn("grid grid-cols-1 gap-3 lg:grid-cols-2", className)}>
      {samples.map((sample) => (
        <CodeBlock
          key={sample.id}
          code={sample.code}
          language={sample.language}
          filename={sample.filename}
          title={sample.title}
          description={sample.description}
        />
      ))}
    </div>
  );
}
