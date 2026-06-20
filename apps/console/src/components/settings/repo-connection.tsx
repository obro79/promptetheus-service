"use client";

import * as React from "react";
import { CheckCircle2, Github, Link2, Link2Off, Loader2 } from "lucide-react";

import type { Project } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export interface RepoConnectionProps {
  project: Project;
}

export function RepoConnection({ project }: RepoConnectionProps) {
  const [repo, setRepo] = React.useState<string | null>(project.connected_repo);
  const [pending, setPending] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const handleConnect = React.useCallback(() => {
    const value = draft.trim();
    if (!value) return;
    setPending(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setRepo(value);
      setDraft("");
      setPending(false);
    }, 900);
  }, [draft]);

  const handleDisconnect = React.useCallback(() => {
    setPending(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setRepo(null);
      setPending(false);
    }, 700);
  }, []);

  return (
    <div className="landing-framed-surface p-5">
      <div className="flex items-start gap-3">
        <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-full border border-border/50 bg-elevated text-foreground">
          <Github className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-medium text-foreground">
              GitHub repository
            </h3>
            {repo ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-success/10 px-2 py-1 text-[10px] font-medium leading-none text-success">
                <CheckCircle2 className="size-3" />
                connected
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-[10px] font-medium leading-none text-muted-foreground">
                not connected
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
            Fix-agent PRs open against this repo with the{" "}
            <span className="mono text-foreground">promptetheus/</span> branch
            prefix.
          </p>

          {repo ? (
            <div className="mt-3 flex items-center justify-between gap-3 rounded-md border border-border bg-canvas px-3 py-2">
              <a
                href={`https://github.com/${repo}`}
                className="mono inline-flex items-center gap-1.5 truncate text-xs text-accent transition-colors duration-150 hover:underline"
              >
                <Link2 className="size-3.5 shrink-0" />
                {repo}
              </a>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleDisconnect}
                disabled={pending}
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
              >
                {pending ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Link2Off className="size-3.5" />
                )}
                Disconnect
              </Button>
            </div>
          ) : (
            <div className="mt-3 flex items-center gap-2">
              <Input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleConnect();
                }}
                placeholder="owner/repo"
                className="mono h-8 text-xs"
                aria-label="Repository (owner/repo)"
              />
              <Button
                size="sm"
                onClick={handleConnect}
                disabled={pending || draft.trim().length === 0}
              >
                {pending ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Github className="size-3.5" />
                )}
                Connect
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
