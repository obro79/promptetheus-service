import * as React from "react";
import type { HTMLAttributes } from "react";
import type { LucideIcon } from "lucide-react";

import {
  Eyebrow,
  LandingAppContent,
  LandingAppHeader,
  LandingAppShell,
  LandingCard,
} from "@/components/landing/landing-primitives";
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
    <LandingAppShell className={className} {...props}>
      {children}
    </LandingAppShell>
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
    <LandingAppHeader compact={narrow} className={className} {...props}>
      {children}
    </LandingAppHeader>
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
    <LandingAppContent compact={narrow} className={className} {...props}>
      {children}
    </LandingAppContent>
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
    <Eyebrow className={className} icon={icon} {...props}>
      {children}
    </Eyebrow>
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
    <LandingCard size="compact" className={cn("min-w-0 sm:min-w-[150px]", className)}>
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
    </LandingCard>
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
        "inline-flex min-h-8 items-center gap-1.5 rounded-full border border-border/70 bg-panel/70 px-3 text-[11px] font-medium text-muted-foreground backdrop-blur",
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
    <LandingCard className={className} {...props}>
      {children}
    </LandingCard>
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
