"use client";

import * as React from "react";
import { CheckCircle2, ChevronRight } from "lucide-react";

import { CodeBlock, type CodeSample } from "@/components/docs/code-block";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface QuickstartStep {
  id: string;
  label: string;
  title: string;
  description?: string;
  code: string;
  language?: string;
  filename?: string;
  badge?: string;
}

export interface QuickstartBlocksProps {
  steps: QuickstartStep[];
  className?: string;
}

export function QuickstartBlocks({ steps, className }: QuickstartBlocksProps) {
  return (
    <div className={cn("space-y-3", className)}>
      {steps.map((step, index) => (
        <QuickstartStepBlock
          key={step.id}
          step={step}
          index={index}
          isLast={index === steps.length - 1}
        />
      ))}
    </div>
  );
}

export interface QuickstartStepBlockProps {
  step: QuickstartStep;
  index: number;
  isLast?: boolean;
  className?: string;
}

export function QuickstartStepBlock({
  step,
  index,
  isLast = false,
  className,
}: QuickstartStepBlockProps) {
  return (
    <section
      className={cn(
        "grid grid-cols-[2rem_minmax(0,1fr)] gap-3",
        className,
      )}
    >
      <div className="flex flex-col items-center">
        <div className="flex size-8 items-center justify-center rounded-full border border-accent/20 bg-accent-muted text-xs font-semibold text-accent">
          {index + 1}
        </div>
        {!isLast ? <div className="my-2 w-px flex-1 bg-border/70" /> : null}
      </div>

      <div className="min-w-0 pb-3">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            {step.label}
          </span>
          {step.badge ? <Badge variant="accent">{step.badge}</Badge> : null}
        </div>
        <CodeBlock
          code={step.code}
          language={step.language}
          filename={step.filename}
          title={step.title}
          description={step.description}
        />
      </div>
    </section>
  );
}

export interface CodeSampleTabsProps {
  samples: CodeSample[];
  defaultSampleId?: string;
  className?: string;
}

export function CodeSampleTabs({
  samples,
  defaultSampleId,
  className,
}: CodeSampleTabsProps) {
  const firstSample = samples[0];
  const [activeId, setActiveId] = React.useState(defaultSampleId ?? firstSample?.id);
  const active = samples.find((sample) => sample.id === activeId) ?? firstSample;

  if (!active) return null;

  return (
    <div className={cn("overflow-hidden rounded-lg bg-panel", className)}>
      <div className="flex gap-1 overflow-x-auto border-b border-border bg-elevated/30 p-1.5">
        {samples.map((sample) => {
          const selected = sample.id === active.id;

          return (
            <button
              key={sample.id}
              type="button"
              onClick={() => setActiveId(sample.id)}
              className={cn(
                "inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-xs text-muted-foreground transition-colors duration-150 hover:bg-panel hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                selected && "bg-panel text-foreground shadow-sm",
              )}
            >
              {selected ? (
                <CheckCircle2 className="size-3.5 text-success" />
              ) : (
                <ChevronRight className="size-3.5" />
              )}
              {sample.title}
            </button>
          );
        })}
      </div>
      <CodeBlock
        code={active.code}
        language={active.language}
        filename={active.filename}
        title={active.title}
        description={active.description}
        className="rounded-none bg-canvas"
      />
    </div>
  );
}
