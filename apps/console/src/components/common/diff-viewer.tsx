import * as React from "react";

import { cn } from "@/lib/utils";

export interface DiffViewerProps {
  /** A unified diff string. */
  diff: string;
  className?: string;
}

type LineKind = "add" | "del" | "hunk" | "meta" | "context";

function classify(line: string): LineKind {
  if (line.startsWith("@@")) return "hunk";
  if (
    line.startsWith("+++") ||
    line.startsWith("---") ||
    line.startsWith("diff ") ||
    line.startsWith("index ") ||
    line.startsWith("new file") ||
    line.startsWith("deleted file") ||
    line.startsWith("rename ")
  )
    return "meta";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  return "context";
}

const LINE_STYLES: Record<LineKind, string> = {
  add: "bg-success/10 text-success",
  del: "bg-destructive/10 text-destructive",
  hunk: "bg-accent-muted/30 text-accent",
  meta: "text-muted-foreground/70",
  context: "text-muted-foreground",
};

const GUTTER_MARK: Record<LineKind, string> = {
  add: "+",
  del: "-",
  hunk: "",
  meta: "",
  context: " ",
};

export function DiffViewer({ diff, className }: DiffViewerProps) {
  const lines = React.useMemo(() => diff.replace(/\n$/, "").split("\n"), [diff]);

  return (
    <div
      className={cn(
        "mono overflow-auto rounded-xl border border-border bg-canvas text-xs leading-relaxed",
        className,
      )}
    >
      <pre className="min-w-full">
        <code className="block">
          {lines.map((line, i) => {
            const kind = classify(line);
            return (
              <span
                key={i}
                className={cn(
                  "flex w-full whitespace-pre px-3",
                  LINE_STYLES[kind],
                )}
              >
                <span className="mr-3 inline-block w-3 select-none text-right opacity-60">
                  {GUTTER_MARK[kind]}
                </span>
                <span className="flex-1">{line || " "}</span>
              </span>
            );
          })}
        </code>
      </pre>
    </div>
  );
}
