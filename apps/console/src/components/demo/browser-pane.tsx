"use client";

import * as React from "react";
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  Lock,
  RotateCw,
} from "lucide-react";

import { cn } from "@/lib/utils";

export interface BrowserPaneProps {
  /** The highest event seq that has "played" so far. -1 = nothing yet. */
  activeSeq: number;
  className?: string;
}

const TIME_SLOTS = [
  { time: "01:00", label: "1:00 AM" },
  { time: "02:00", label: "2:00 AM" },
  { time: "09:00", label: "9:00 AM" },
  { time: "11:00", label: "11:00 AM" },
  { time: "13:00", label: "1:00 PM" },
  { time: "14:00", label: "2:00 PM" },
  { time: "15:00", label: "3:00 PM" },
  { time: "16:00", label: "4:00 PM" },
];

export function BrowserPane({ activeSeq, className }: BrowserPaneProps) {
  // Derive UI state from the playhead — mirrors the hero session timeline.
  const pageOpen = activeSeq >= 4; // browser_action navigate
  const dayPicked = activeSeq >= 7; // click day
  const timePicked = activeSeq >= 11; // click 2:00 (AM)
  const warningVisible = activeSeq >= 14; // dom_snapshot with warning
  const claimedSuccess = activeSeq >= 17; // agent_message "Done"

  return (
    <div
      className={cn(
        "flex h-full flex-col overflow-hidden rounded-lg border border-border bg-canvas",
        className,
      )}
    >
      {/* Browser chrome */}
      <div className="shrink-0 border-b border-border bg-panel">
        <div className="flex items-center gap-2 px-3 py-2">
          <div className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full bg-destructive/70" />
            <span className="size-2.5 rounded-full bg-warning/70" />
            <span className="size-2.5 rounded-full bg-success/70" />
          </div>
          <div className="ml-2 flex flex-1 items-center gap-2 rounded-md border border-border bg-canvas px-2.5 py-1">
            <Lock className="size-3 text-success/80" />
            <span className="mono truncate text-[11px] text-muted-foreground">
              acmemeet.com/book/demo
            </span>
            <RotateCw className="ml-auto size-3 text-muted-foreground/60" />
          </div>
          <span className="mono rounded border border-accent/25 bg-accent-muted/30 px-1.5 py-0.5 text-[9px] uppercase leading-none tracking-wide text-accent">
            agent
          </span>
        </div>
      </div>

      {/* Page body */}
      <div className="relative flex-1 overflow-auto bg-gradient-to-b from-canvas to-panel/30 p-5">
        {!pageOpen ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex flex-col items-center gap-2 text-muted-foreground/50">
              <Calendar className="size-8" />
              <span className="text-xs">Waiting for agent…</span>
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-sm animate-fade-in">
            {/* AcmeMeet brand */}
            <div className="mb-5 flex items-center gap-2">
              <span className="inline-flex size-6 items-center justify-center rounded-md bg-accent text-[11px] font-bold text-accent-foreground">
                A
              </span>
              <span className="text-sm font-semibold text-foreground">
                AcmeMeet
              </span>
              <span className="ml-auto text-[11px] text-muted-foreground">
                Book a demo
              </span>
            </div>

            {/* Date card */}
            <div
              className={cn(
                "mb-3 rounded-lg border bg-elevated/40 px-3 py-2.5 transition-colors duration-300",
                dayPicked ? "border-accent/40" : "border-border",
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Date</span>
                {dayPicked ? (
                  <CheckCircle2 className="size-3.5 text-accent" />
                ) : null}
              </div>
              <p
                className={cn(
                  "mt-0.5 text-sm font-medium",
                  dayPicked ? "text-foreground" : "text-muted-foreground/50",
                )}
              >
                {dayPicked ? "Tuesday, June 23" : "Select a day"}
              </p>
            </div>

            {/* Time grid */}
            <div className="mb-3">
              <span className="mb-1.5 block text-xs text-muted-foreground">
                Available times
              </span>
              <div className="grid grid-cols-4 gap-1.5">
                {TIME_SLOTS.map((slot) => {
                  const selected = timePicked && slot.time === "02:00";
                  const target = slot.time === "14:00";
                  return (
                    <div
                      key={slot.time}
                      className={cn(
                        "rounded-md border px-1.5 py-1.5 text-center text-[11px] transition-all duration-300",
                        selected
                          ? "border-destructive/50 bg-destructive/15 font-semibold text-destructive ring-1 ring-destructive/30"
                          : target && warningVisible
                            ? "border-success/40 bg-success/10 text-success"
                            : "border-border bg-canvas text-muted-foreground/70",
                      )}
                    >
                      {slot.label}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Timezone warning */}
            {warningVisible ? (
              <div className="mb-3 animate-slide-in rounded-lg border border-warning/40 bg-warning/10 px-3 py-2.5">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />
                  <div>
                    <p className="text-xs font-medium text-warning">
                      Selected 2:00 AM PDT
                    </p>
                    <p className="mt-0.5 text-[11px] leading-snug text-warning/80">
                      This is an early-morning slot (2:00 AM). Did you mean
                      2:00&nbsp;PM? Click to change.
                    </p>
                  </div>
                </div>
              </div>
            ) : null}

            {/* Agent's false claim banner */}
            {claimedSuccess ? (
              <div className="animate-slide-in rounded-lg border border-border bg-elevated/60 px-3 py-2.5">
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-success" />
                  <p className="text-[11px] leading-snug text-muted-foreground">
                    <span className="text-foreground">Agent:</span> Done — I&apos;ve
                    booked Tuesday at 2pm Pacific and stopped at the confirmation
                    screen as requested.
                  </p>
                </div>
              </div>
            ) : (
              <button
                type="button"
                disabled
                className="w-full cursor-default rounded-md border border-border bg-accent/90 py-2 text-xs font-medium text-accent-foreground opacity-90"
              >
                Continue to confirmation
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
