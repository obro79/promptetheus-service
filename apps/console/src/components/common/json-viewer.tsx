"use client";

import * as React from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

export interface JsonViewerProps {
  data: unknown;
  /** depth at which nodes start collapsed (default: 2). */
  collapseDepth?: number;
  className?: string;
}

function isPrimitive(v: unknown): boolean {
  return v === null || typeof v !== "object";
}

function Primitive({ value }: { value: unknown }) {
  if (value === null)
    return <span className="text-muted-foreground/70">null</span>;
  if (typeof value === "string")
    return <span className="text-success">&quot;{value}&quot;</span>;
  if (typeof value === "number")
    return <span className="text-accent tabular-nums">{value}</span>;
  if (typeof value === "boolean")
    return <span className="text-warning">{String(value)}</span>;
  return <span className="text-foreground">{String(value)}</span>;
}

interface NodeProps {
  name?: string;
  value: unknown;
  depth: number;
  collapseDepth: number;
  isLast: boolean;
}

function Node({ name, value, depth, collapseDepth, isLast }: NodeProps) {
  const collapsible = !isPrimitive(value);
  const [open, setOpen] = React.useState(depth < collapseDepth);

  const keyLabel =
    name !== undefined ? (
      <span className="text-muted-foreground">{name}: </span>
    ) : null;

  if (!collapsible) {
    return (
      <div className="leading-relaxed">
        {keyLabel}
        <Primitive value={value} />
        {isLast ? null : <span className="text-muted-foreground/40">,</span>}
      </div>
    );
  }

  const isArray = Array.isArray(value);
  const entries = isArray
    ? (value as unknown[]).map((v, i) => [String(i), v] as const)
    : Object.entries(value as Record<string, unknown>);
  const open_b = isArray ? "[" : "{";
  const close_b = isArray ? "]" : "}";
  const count = entries.length;

  return (
    <div className="leading-relaxed">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="group inline-flex items-center gap-0.5 rounded text-left hover:bg-elevated/60"
      >
        <ChevronRight
          className={cn(
            "size-3 shrink-0 text-muted-foreground/60 transition-transform duration-150",
            open && "rotate-90",
          )}
          strokeWidth={1.8}
        />
        {keyLabel}
        <span className="text-muted-foreground/60">{open_b}</span>
        {!open ? (
          <span className="text-muted-foreground/40">
            {count} {isArray ? "item" : "key"}
            {count === 1 ? "" : "s"}
            {close_b}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="border-l border-border/60 pl-3 ml-1.5">
          {entries.map(([k, v], i) => (
            <Node
              key={k}
              name={isArray ? undefined : k}
              value={v}
              depth={depth + 1}
              collapseDepth={collapseDepth}
              isLast={i === entries.length - 1}
            />
          ))}
        </div>
      ) : null}
      {open ? (
        <div className="text-muted-foreground/60">
          {close_b}
          {isLast ? null : <span className="text-muted-foreground/40">,</span>}
        </div>
      ) : null}
    </div>
  );
}

export function JsonViewer({
  data,
  collapseDepth = 2,
  className,
}: JsonViewerProps) {
  return (
    <div
      className={cn(
        "mono overflow-auto rounded-xl border border-border bg-canvas p-3 text-xs text-foreground",
        className,
      )}
    >
      <Node
        value={data}
        depth={0}
        collapseDepth={collapseDepth}
        isLast
      />
    </div>
  );
}
