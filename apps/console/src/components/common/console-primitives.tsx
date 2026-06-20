import * as React from "react";
import type { HTMLAttributes } from "react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

// ─── Page wrapper ─────────────────────────────────────────────────────────────

/** Full-page wrapper: warm canvas bg + the two decorative radial glows used on
 *  the incidents page. Non-landing console pages should use this as their root. */
export function ConsolePage({
  children,
  className,
  ...props
}: HTMLAttributes<HTMLElement>) {
  return (
    <main
      className={cn(
        "relative flex min-h-full flex-col overflow-hidden bg-canvas",
        className,
      )}
      {...props}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute left-[-12rem] top-[-9rem] h-[28rem] w-[28rem] rounded-full border border-border/25 opacity-70"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute right-[-9rem] top-[-11rem] h-[30rem] w-[30rem] rounded-full bg-accent/15 blur-3xl"
      />
      {children}
    </main>
  );
}

// ─── Page header ──────────────────────────────────────────────────────────────

/** Sticky glass header bar, matching the incidents page treatment. Children are
 *  laid out inside the max-width content rail. For a two-column header (title
 *  left + readouts right) pass two direct children. */
export function ConsolePageHeader({
  children,
  className,
  narrow = false,
  ...props
}: HTMLAttributes<HTMLElement> & { narrow?: boolean }) {
  return (
    <header
      className={cn(
        "relative z-20 border-b border-border/40 bg-canvas/68 backdrop-blur-xl lg:sticky lg:top-0",
        className,
      )}
      {...props}
    >
      <div
        className={cn(
          "mx-auto flex w-full flex-col gap-7 px-4 py-7 sm:px-6 lg:flex-row lg:items-end lg:justify-between lg:py-9",
          narrow ? "max-w-3xl" : "max-w-[1500px]",
        )}
      >
        {children}
      </div>
    </header>
  );
}

/** Content area below the sticky header. */
export function ConsolePageContent({
  children,
  className,
  narrow = false,
  ...props
}: HTMLAttributes<HTMLDivElement> & { narrow?: boolean }) {
  return (
    <div
      className={cn(
        "relative z-10 mx-auto w-full flex-1 px-4 py-6 sm:px-6 lg:py-8",
        narrow ? "max-w-3xl" : "max-w-[1500px]",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

// ─── Eyebrow ──────────────────────────────────────────────────────────────────

interface ConsoleEyebrowProps extends HTMLAttributes<HTMLParagraphElement> {
  icon?: React.ReactNode;
}

/** Pill-shaped eyebrow label placed above the page heading. */
export function ConsoleEyebrow({
  children,
  className,
  icon,
  ...props
}: ConsoleEyebrowProps) {
  return (
    <p
      className={cn(
        "mb-4 inline-flex items-center gap-2 rounded-full border border-border/70 bg-panel/72 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-accent shadow-sm",
        className,
      )}
      {...props}
    >
      {icon}
      {children}
    </p>
  );
}

// ─── Metric readout ───────────────────────────────────────────────────────────

interface MetricReadoutProps {
  label: string;
  value: number | string;
  tone?: "warning" | "signal";
  className?: string;
}

/** Surface card with a large display-font number and a small label — used in
 *  the incidents header and now shared across all top-level console pages. */
export function MetricReadout({
  label,
  value,
  tone,
  className,
}: MetricReadoutProps) {
  const numStr =
    typeof value === "number" ? String(value).padStart(2, "0") : value;
  return (
    <div
      className={cn(
        "surface flex min-w-0 flex-col gap-3 rounded-2xl px-4 py-4 sm:min-w-[150px]",
        className,
      )}
    >
      <dt className="text-[9px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </dt>
      <dd
        className={cn(
          "display order-first text-4xl leading-none tabular-nums",
          tone === "warning"
            ? "text-warning"
            : tone === "signal"
              ? "text-success"
              : "text-foreground",
        )}
      >
        {numStr}
      </dd>
    </div>
  );
}

// ─── Signal chip ──────────────────────────────────────────────────────────────

interface SignalChipProps {
  Icon: LucideIcon;
  label: string;
  className?: string;
}

/** Feature/signal pill chip placed below the page heading. */
export function SignalChip({ Icon, label, className }: SignalChipProps) {
  return (
    <span
      className={cn(
        "inline-flex min-h-8 items-center gap-1.5 rounded-full border border-border/55 bg-panel/62 px-3 text-[11px] font-medium text-muted-foreground",
        className,
      )}
    >
      <Icon className="size-3.5 text-accent" aria-hidden="true" strokeWidth={1.8} />
      {label}
    </span>
  );
}

// ─── Console surface card ─────────────────────────────────────────────────────

/** Generalized glassy surface card. Prefer the `surface` CSS class for inline
 *  usage; use this component when you also need rounded-2xl + padding. */
export function ConsoleSurface({
  children,
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("surface rounded-2xl", className)} {...props}>
      {children}
    </div>
  );
}

// ─── Section header (for settings / docs pages) ───────────────────────────────

interface ConsoleSectionHeaderProps {
  eyebrow?: React.ReactNode;
  eyebrowIcon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  trailing?: React.ReactNode;
  className?: string;
}

/** Compact section header used inside narrow pages like settings and docs. */
export function ConsoleSectionHeader({
  eyebrow,
  eyebrowIcon,
  title,
  description,
  trailing,
  className,
}: ConsoleSectionHeaderProps) {
  return (
    <div className={cn("min-w-0", className)}>
      {eyebrow ? (
        <ConsoleEyebrow icon={eyebrowIcon}>{eyebrow}</ConsoleEyebrow>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="display text-4xl leading-[0.96] text-foreground sm:text-5xl">
            {title}
          </h1>
          {description ? (
            <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        {trailing ? <div className="shrink-0">{trailing}</div> : null}
      </div>
    </div>
  );
}
