"use client";

import * as React from "react";
import { Check, Copy, Eye, EyeOff, KeyRound, RefreshCw } from "lucide-react";

import type { Project } from "@/lib/types";
import { rotateProjectApiKey } from "@/lib/promptetheus-api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export interface ApiKeyRowProps {
  project: Project;
}

export function ApiKeyRow({ project }: ApiKeyRowProps) {
  const [revealed, setRevealed] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const [regenerating, setRegenerating] = React.useState(false);
  const [rawKey, setRawKey] = React.useState<string | null>(null);
  const [preview, setPreview] = React.useState(project.api_key_preview);
  const [error, setError] = React.useState<string | null>(null);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const display = revealed && rawKey ? rawKey : preview;

  const handleCopy = React.useCallback(() => {
    const value = rawKey ?? preview;
    void navigator.clipboard?.writeText(value).then(() => {
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1400);
    });
  }, [preview, rawKey]);

  const handleRegenerate = React.useCallback(() => {
    setRegenerating(true);
    setError(null);
    if (timer.current) clearTimeout(timer.current);
    void rotateProjectApiKey(project.id)
      .then((result) => {
        if (result) {
          setRawKey(result.api_key);
          setPreview(result.api_key_preview);
          setRevealed(true);
          return;
        }
        const suffix = Math.random().toString(16).slice(2, 8);
        setRawKey(null);
        setPreview(`pt_live_...${suffix}`);
        setRevealed(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Could not rotate key");
      })
      .finally(() => {
        setRegenerating(false);
      });
  }, [project.id]);

  return (
    <div className="landing-framed-surface flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-center gap-3">
        <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-full border border-accent/20 bg-accent-muted text-accent">
          <KeyRound className="size-4" />
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-foreground">
              {project.name}
            </span>
            {rawKey ? (
              <span className="mono rounded-md bg-success/10 px-2 py-1 text-[10px] leading-none text-success">
                new key shown once
              </span>
            ) : null}
          </div>
          <code className="mono mt-1 block truncate text-xs text-muted-foreground">
            {display}
          </code>
          {error ? (
            <p className="mt-1 text-xs text-destructive">{error}</p>
          ) : null}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setRevealed((v) => !v)}
          disabled={!rawKey}
          aria-label={revealed ? "Hide key" : "Reveal key"}
        >
          {revealed ? (
            <>
              <EyeOff className="size-3.5" /> Hide
            </>
          ) : (
            <>
              <Eye className="size-3.5" /> Reveal
            </>
          )}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleCopy}
          aria-label="Copy key"
        >
          {copied ? (
            <>
              <Check className="size-3.5 text-success" /> Copied
            </>
          ) : (
            <>
              <Copy className="size-3.5" /> Copy
            </>
          )}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRegenerate}
          disabled={regenerating}
        >
          <RefreshCw
            className={cn("size-3.5", regenerating && "animate-spin")}
          />
          {regenerating ? "Rotating" : "Regenerate"}
        </Button>
      </div>
    </div>
  );
}
