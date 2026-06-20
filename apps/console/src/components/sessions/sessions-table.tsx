"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowUpRight, Inbox } from "lucide-react";

import type { TraceSession } from "@/lib/types";
import { cn, fmtDuration, fmtRelative } from "@/lib/utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { StatusPill } from "@/components/common/status-pill";
import { LabelTag } from "@/components/common/label-tag";
import { EmptyState } from "@/components/common/empty-state";

const EMPTY_RESULTS_ILLUSTRATION = {
  src: "/illustrations/empty-results.webp",
  width: 176,
  height: 107,
} as const;

export interface SessionsTableProps {
  sessions: TraceSession[];
}

/** Turn an incident id like "inc_browser_goal_mismatch" into "goal mismatch". */
function failureLabel(session: TraceSession): string | null {
  if (session.status !== "failed" && session.status !== "error") return null;
  if (session.incident_id) {
    const tail = session.incident_id.replace(/^inc_(browser_|agent_)?/, "");
    const words = tail.replace(/_/g, " ").trim();
    if (words) return words;
  }
  return session.status === "error" ? "runtime error" : "failure";
}

function rowHref(session: TraceSession): string {
  return `/sessions/${session.id}`;
}

export function SessionsTable({ sessions }: SessionsTableProps) {
  const router = useRouter();

  React.useEffect(() => {
    // Warm the route on mount-ish for snappy nav to the first few rows.
    sessions.slice(0, 8).forEach((s) => router.prefetch(rowHref(s)));
  }, [router, sessions]);

  if (sessions.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        illustration={EMPTY_RESULTS_ILLUSTRATION}
        title="No sessions match"
        description="No traces match the current filter. Clear the search or switch status to see the full feed."
      />
    );
  }

  return (
    <div className="landing-framed-surface overflow-x-auto">
      <Table>
        <TableHeader className="bg-muted/35">
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-[96px]">Status</TableHead>
            <TableHead className="min-w-[280px]">Goal</TableHead>
            <TableHead className="w-[160px]">Agent</TableHead>
            <TableHead className="w-[120px]">Env</TableHead>
            <TableHead className="w-[180px]">Failure</TableHead>
            <TableHead className="w-[80px] text-right">Events</TableHead>
            <TableHead className="w-[88px] text-right">Duration</TableHead>
            <TableHead className="w-[96px] text-right">Started</TableHead>
            <TableHead className="w-[36px]" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sessions.map((s) => {
            const href = rowHref(s);
            const failure = failureLabel(s);
            const failed = s.status === "failed" || s.status === "error";
            return (
              <TableRow
                key={s.id}
                tabIndex={0}
                role="link"
                aria-label={`Open session ${s.id}`}
                onClick={() => router.push(href)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    router.push(href);
                  }
                }}
                className={cn(
                  "group cursor-pointer outline-none focus-visible:bg-elevated focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
                  failed && "hover:bg-warning/[0.04]",
                )}
              >
                <TableCell className="py-2.5">
                  <StatusPill status={s.status} />
                </TableCell>

                <TableCell className="py-2.5">
                  <div className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className={cn(
                        "h-3.5 w-px shrink-0 rounded-full transition-colors duration-150",
                        failed
                          ? "bg-warning/60"
                          : s.status === "running"
                            ? "bg-accent/50"
                            : "bg-success/30",
                      )}
                    />
                    <span
                      title={s.user_goal ?? undefined}
                      className="block max-w-[460px] truncate text-sm text-foreground transition-colors duration-150 group-hover:text-foreground"
                    >
                      {s.user_goal ?? (
                        <span className="text-muted-foreground italic">
                          no goal recorded
                        </span>
                      )}
                    </span>
                  </div>
                </TableCell>

                <TableCell className="py-2.5">
                  <span className="mono truncate text-xs text-muted-foreground">
                    {s.agent ?? "—"}
                  </span>
                </TableCell>

                <TableCell className="py-2.5">
                  {s.environment ? (
                    <span className="mono inline-flex items-center rounded-md bg-elevated px-2 py-1 text-[10px] text-muted-foreground">
                      {s.environment}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>

                <TableCell className="py-2.5">
                  {failure ? (
                    <LabelTag
                      label={failure}
                      className="border-warning/30 bg-warning/10 text-warning hover:border-warning/50 hover:text-warning"
                    />
                  ) : (
                    <span className="text-xs text-muted-foreground/40">—</span>
                  )}
                </TableCell>

                <TableCell className="py-2.5 text-right">
                  <span className="mono text-xs tabular-nums text-muted-foreground">
                    {s.event_count}
                  </span>
                </TableCell>

                <TableCell className="py-2.5 text-right">
                  <span className="mono text-xs tabular-nums text-muted-foreground">
                    {fmtDuration(s.duration_ms)}
                  </span>
                </TableCell>

                <TableCell className="py-2.5 text-right">
                  <span
                    className="mono whitespace-nowrap text-xs tabular-nums text-muted-foreground"
                    title={s.started_at}
                  >
                    {fmtRelative(s.started_at)}
                  </span>
                </TableCell>

                <TableCell className="py-2.5 text-right">
                  <Link
                    href={href}
                    tabIndex={-1}
                    onClick={(e) => e.stopPropagation()}
                    aria-hidden
                    className="inline-flex text-muted-foreground/40 opacity-0 transition-all duration-150 group-hover:translate-x-0 group-hover:text-accent group-hover:opacity-100"
                  >
                    <ArrowUpRight className="size-3.5" />
                  </Link>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
