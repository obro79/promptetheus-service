import * as React from "react";
import { ExternalLink, FileCode2, GitBranch, GitPullRequest } from "lucide-react";

import type { FixAgentResult } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface PRCardProps {
  prUrl: string | null;
  fingerprint: string;
  fix: FixAgentResult | null;
  className?: string;
}

/** Derive a stable promptetheus/ branch name from the incident fingerprint. */
function branchFromFingerprint(fingerprint: string): string {
  const slug = fingerprint
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return `promptetheus/fix-${slug || "incident"}`;
}

function prNumberFromUrl(url: string): string | null {
  const m = url.match(/\/pull\/(\d+)/);
  return m ? m[1] : null;
}

export function PRCard({ prUrl, fingerprint, fix, className }: PRCardProps) {
  const branch = branchFromFingerprint(fingerprint);
  const fileCount = fix?.changed_files.length ?? 0;

  if (!prUrl) {
    return (
      <div
        className={cn(
          "rounded-lg border border-dashed border-border bg-panel/40 px-4 py-4",
          className,
        )}
      >
        <div className="flex items-center gap-2">
          <GitPullRequest className="size-4 text-muted-foreground" />
          <span className="text-sm font-medium text-foreground">
            No pull request yet
          </span>
        </div>
        <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
          Generate and approve a fix bundle to open a PR on the connected
          repository.
        </p>
        <div className="mt-2.5 flex items-center gap-1.5 rounded-md border border-border bg-canvas px-2 py-1.5">
          <GitBranch className="size-3 shrink-0 text-muted-foreground" />
          <span className="mono truncate text-[11px] text-muted-foreground/80">
            {branch}
          </span>
        </div>
      </div>
    );
  }

  const prNumber = prNumberFromUrl(prUrl);

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border border-success/30 bg-panel",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border bg-success/5 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <GitPullRequest className="size-4 text-success" />
          <span className="text-sm font-semibold text-foreground">
            Pull request opened
          </span>
        </div>
        {prNumber ? (
          <span className="mono rounded border border-success/30 bg-success/10 px-1.5 py-0.5 text-[11px] tabular-nums text-success">
            #{prNumber}
          </span>
        ) : null}
      </div>

      <div className="flex flex-col gap-3 px-4 py-3">
        <div className="flex items-center gap-1.5 rounded-md border border-border bg-canvas px-2 py-1.5">
          <GitBranch className="size-3 shrink-0 text-accent" />
          <span className="mono truncate text-[11px] text-foreground/90">
            {branch}
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <FileCode2 className="size-3.5 shrink-0 text-muted-foreground" />
          {fileCount > 0 ? (
            <span>
              <span className="mono tabular-nums text-foreground">
                {fileCount}
              </span>{" "}
              {fileCount === 1 ? "file" : "files"} changed
            </span>
          ) : (
            <span>Diff attached to PR</span>
          )}
        </div>

        <a
          href={prUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-md border border-border bg-secondary px-3.5 text-sm font-medium text-secondary-foreground transition-colors duration-150 hover:border-success/40 hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
        >
          <ExternalLink className="size-4" />
          View PR on GitHub
        </a>
      </div>
    </div>
  );
}
