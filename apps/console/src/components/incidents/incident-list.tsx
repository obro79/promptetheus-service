"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, GitPullRequest, ShieldCheck } from "lucide-react";

import { SeverityBadge } from "@/components/common/severity-badge";
import { StatusPill } from "@/components/common/status-pill";
import type { Incident, Severity } from "@/lib/types";
import { cn, fmtRelative } from "@/lib/utils";

const SEVERITY_RANK: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

const DESKTOP_COLUMNS =
  "xl:grid-cols-[104px_minmax(260px,1fr)_160px_86px_60px_118px_76px_24px]";
const DESKTOP_HEADERS = [
  "Severity",
  "Failure record",
  "Pattern",
  "Status",
  "Runs",
  "Regression",
  "Last seen",
  "",
];

export function IncidentList({ incidents }: { incidents: Incident[] }) {
  const router = useRouter();
  const ordered = React.useMemo(
    () =>
      [...incidents].sort(
        (a, b) =>
          SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] ||
          b.updated_at.localeCompare(a.updated_at),
      ),
    [incidents],
  );
  const [activeIndex, setActiveIndex] = React.useState(-1);
  const refs = React.useRef<Map<string, HTMLAnchorElement>>(new Map());

  const focusIndex = (index: number) => {
    const bounded = Math.max(0, Math.min(index, ordered.length - 1));
    setActiveIndex(bounded);
    refs.current.get(ordered[bounded]?.id)?.focus();
  };

  return (
    <div
      className="surface overflow-hidden rounded-[1.75rem] border-border/70 bg-panel/78"
      role="list"
      aria-label="Failure inbox"
      onKeyDown={(event) => {
        if (event.key === "j" || event.key === "ArrowDown") {
          event.preventDefault();
          focusIndex(activeIndex + 1);
        }
        if (event.key === "k" || event.key === "ArrowUp") {
          event.preventDefault();
          focusIndex(activeIndex - 1);
        }
        if (event.key === "Enter" && activeIndex >= 0) {
          router.push(`/incidents/${ordered[activeIndex].id}`);
        }
      }}
    >
      <div
        className={cn(
          "hidden items-center border-b border-border/50 bg-elevated/25 px-5 py-3",
          DESKTOP_COLUMNS,
          "xl:grid",
        )}
      >
        {DESKTOP_HEADERS.map((label, index) => (
          <span
            key={`${label}-${index}`}
            className="mono text-[9px] font-semibold uppercase tracking-[0.18em] text-muted-foreground"
          >
            {label}
          </span>
        ))}
      </div>

      {ordered.map((incident, index) => {
        const covered = Boolean(incident.fix_agent_result?.regression_test);
        return (
          <Link
            key={incident.id}
            ref={(node) => {
              if (node) refs.current.set(incident.id, node);
              else refs.current.delete(incident.id);
            }}
            href={`/incidents/${incident.id}`}
            role="listitem"
            onFocus={() => setActiveIndex(index)}
            className={cn(
              "group relative grid min-h-[104px] grid-cols-[auto_minmax(0,1fr)_24px] items-center gap-x-3 border-b border-border/45 px-4 py-4 outline-none transition-[background-color,box-shadow] last:border-b-0 hover:bg-panel/95 hover:shadow-glow-sm focus-visible:bg-panel focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:px-5 xl:min-h-[86px] xl:gap-x-0 xl:py-3",
              DESKTOP_COLUMNS,
              index === activeIndex && "bg-panel shadow-glow-sm",
            )}
          >
            <SeverityBadge
              severity={incident.severity}
              className="self-start px-2 py-1.5 text-[10px] uppercase tracking-wide xl:self-center xl:justify-self-start"
            />

            <span className="min-w-0 xl:pr-4">
              <span className="flex min-w-0 items-center gap-2">
                <span className="display truncate text-2xl leading-none text-foreground sm:text-[1.7rem] xl:text-2xl">
                  {incident.title}
                </span>
                {incident.pr_url ? (
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-accent/25 bg-accent-muted text-accent">
                    <GitPullRequest className="size-3.5" aria-label="Pull request linked" />
                  </span>
                ) : null}
              </span>
              <span className="mt-2 hidden min-w-0 items-center gap-2 xl:flex">
                <span className="mono truncate text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  {incident.id}
                </span>
                <span className="size-0.5 shrink-0 rounded-full bg-muted-foreground/60" />
                <span className="truncate text-[11px] text-muted-foreground">
                  {incident.root_cause ?? "Awaiting root-cause analysis"}
                </span>
              </span>
              <span className="mt-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-muted-foreground xl:hidden">
                <StatusPill status={incident.status} className="text-[10px]" />
                <span className="text-muted-foreground/50">·</span>
                <span className="mono max-w-[170px] truncate">{incident.label}</span>
                <span className="text-muted-foreground/50">·</span>
                <span className="tabular-nums">
                  {incident.session_ids.length} run{incident.session_ids.length === 1 ? "" : "s"}
                </span>
                <span className="text-muted-foreground/50">·</span>
                <span>{covered ? "covered" : "not covered"}</span>
                <span className="text-muted-foreground/50">·</span>
                <span className="tabular-nums">{fmtRelative(incident.updated_at)}</span>
              </span>
            </span>

            <span className="mono hidden truncate text-[10px] text-muted-foreground xl:block">
              {incident.label}
            </span>
            <StatusPill status={incident.status} className="hidden text-[10px] xl:inline-flex" />
            <span className="mono hidden text-[10px] tabular-nums text-muted-foreground xl:block">
              {incident.session_ids.length}
            </span>
            <span
              className={cn(
                "mono hidden items-center gap-1.5 rounded-full border px-2 py-1 text-[9px] uppercase tracking-[0.14em] xl:inline-flex",
                covered ? "text-accent" : "text-warning",
                covered ? "border-accent/25 bg-accent-muted" : "border-warning/25 bg-warning/10",
              )}
            >
              <ShieldCheck className="size-3.5" />
              {covered ? "covered" : "not covered"}
            </span>
            <span className="mono hidden text-[10px] tabular-nums text-muted-foreground xl:block">
              {fmtRelative(incident.updated_at)}
            </span>
            <ChevronRight className="size-4 text-muted-foreground/45 transition-[transform,color] group-hover:translate-x-1 group-hover:text-accent" />

            <span className="absolute inset-y-5 left-0 w-1 scale-y-0 rounded-r-full bg-accent transition-transform group-hover:scale-y-100 group-focus-visible:scale-y-100" />
          </Link>
        );
      })}
    </div>
  );
}
