"use client";

import * as React from "react";
import { Check, Clock, Loader2 } from "lucide-react";

import type { Project } from "@/lib/types";
import { updateProjectSettings } from "@/lib/promptetheus-api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export interface RetentionControlProps {
  project: Project;
}

const PRESETS = [7, 14, 30, 60, 90] as const;

export function RetentionControl({ project }: RetentionControlProps) {
  const [days, setDays] = React.useState(project.retention_days);
  const [saved, setSaved] = React.useState(project.retention_days);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const dirty = days !== saved;

  const handleSave = React.useCallback(() => {
    setSaving(true);
    setError(null);
    if (timer.current) clearTimeout(timer.current);
    void updateProjectSettings(project.id, { retention_days: days })
      .then((result) => {
        setSaved(result?.project.retention_days ?? days);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Could not save retention");
      })
      .finally(() => {
        setSaving(false);
      });
  }, [days, project.id]);

  return (
    <div className="surface rounded-2xl p-5">
      <div className="flex items-start gap-3">
        <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-full border border-accent/20 bg-accent-muted text-accent">
          <Clock className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-medium text-foreground">
              Trace retention
            </h3>
            <span className="mono text-xs tabular-nums text-accent">
              {days} days
            </span>
          </div>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
            How long sessions, events, and replay artifacts are kept before they
            are purged from storage.
          </p>
          {error ? (
            <p className="mt-2 text-xs text-destructive">{error}</p>
          ) : null}

          <div className="mt-4">
            <input
              type="range"
              min={7}
              max={90}
              step={1}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              aria-label="Retention days"
              className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-muted accent-accent"
            />
            <div className="mt-1 flex justify-between">
              <span className="mono text-[10px] text-muted-foreground/70">
                7d
              </span>
              <span className="mono text-[10px] text-muted-foreground/70">
                90d
              </span>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {PRESETS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setDays(p)}
                className={cn(
                  "mono rounded-md px-2.5 py-1.5 text-[11px] leading-none transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  days === p
                    ? "bg-accent/10 text-accent"
                    : "bg-elevated text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {p}d
              </button>
            ))}
            <div className="ml-auto">
              <Button
                size="sm"
                onClick={handleSave}
                disabled={!dirty || saving}
                variant={dirty ? "default" : "secondary"}
              >
                {saving ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : !dirty ? (
                  <Check className="size-3.5 text-success" />
                ) : null}
                {saving ? "Saving" : !dirty ? "Saved" : "Save"}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
