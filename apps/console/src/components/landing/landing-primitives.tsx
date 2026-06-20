import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

type LandingSectionProps = HTMLAttributes<HTMLElement> & {
  containerClassName?: string;
  density?: "default" | "compact" | "hero";
  tone?: "plain" | "band";
};

export function LandingSection({
  children,
  className,
  containerClassName,
  density = "default",
  tone = "plain",
  ...props
}: LandingSectionProps) {
  return (
    <section
      className={cn(
        "landing-section",
        density === "compact" && "landing-section-compact",
        density === "hero" && "landing-section-hero",
        tone === "band" && "landing-band",
        className,
      )}
      {...props}
    >
      <div className={cn("landing-container", containerClassName)}>{children}</div>
    </section>
  );
}

type EyebrowProps = HTMLAttributes<HTMLParagraphElement> & {
  children: ReactNode;
  icon?: ReactNode;
  tone?: "accent" | "muted";
  variant?: "default" | "hero";
};

export function Eyebrow({
  children,
  className,
  icon,
  tone = "accent",
  variant = "default",
  ...props
}: EyebrowProps) {
  return (
    <p
      className={cn(
        "landing-eyebrow",
        tone === "muted" && "landing-eyebrow-muted",
        variant === "hero" && "landing-eyebrow-hero",
        className,
      )}
      {...props}
    >
      {icon}
      {children}
    </p>
  );
}

type SectionHeaderProps = {
  align?: "left" | "center";
  body?: ReactNode;
  className?: string;
  eyebrow: string;
  eyebrowTone?: "accent" | "muted";
  title: string;
};

export function SectionHeader({
  align = "left",
  body,
  className,
  eyebrow,
  eyebrowTone,
  title,
}: SectionHeaderProps) {
  return (
    <div className={cn(align === "center" && "mx-auto max-w-3xl text-center", className)}>
      <Eyebrow tone={eyebrowTone}>{eyebrow}</Eyebrow>
      <h2 className="landing-display-lg">{title}</h2>
      {body ? <p className="landing-copy mt-5">{body}</p> : null}
    </div>
  );
}

type LandingCardProps = HTMLAttributes<HTMLElement> & {
  as?: "article" | "div";
  size?: "default" | "compact" | "hero";
};

export function LandingCard({
  as: Component = "div",
  children,
  className,
  size = "default",
  ...props
}: LandingCardProps) {
  return (
    <Component
      className={cn(
        "surface landing-card",
        size === "compact" && "landing-card-compact",
        size === "hero" && "landing-card-hero",
        className,
      )}
      {...props}
    >
      {children}
    </Component>
  );
}

export function LandingAppShell({
  children,
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("landing-page min-h-dvh overflow-y-auto", className)} {...props}>
      <DecorativeField />
      {children}
    </div>
  );
}

export function LandingAppHeader({
  children,
  className,
  containerClassName,
  compact = false,
  ...props
}: HTMLAttributes<HTMLElement> & {
  compact?: boolean;
  containerClassName?: string;
}) {
  return (
    <LandingSection
      className={className}
      containerClassName={cn(
        "landing-use-case-container flex flex-col gap-7 lg:flex-row lg:items-end lg:justify-between",
        compact && "max-w-3xl",
        containerClassName,
      )}
      density="compact"
      {...props}
    >
      {children}
    </LandingSection>
  );
}

export function LandingAppContent({
  children,
  className,
  compact = false,
  ...props
}: HTMLAttributes<HTMLDivElement> & { compact?: boolean }) {
  return (
    <div
      className={cn(
        "landing-container landing-use-case-container relative z-10 pb-16",
        compact && "max-w-3xl",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function IconFrame({ children, className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span className={cn("landing-icon-frame", className)} {...props}>
      {children}
    </span>
  );
}

export function DecorativeField() {
  return (
    <div aria-hidden="true" className="landing-decorative-field">
      <div className="absolute left-[-16rem] top-[-9rem] h-[42rem] w-[42rem] rounded-full border border-border/25" />
      <div className="absolute left-[-11rem] top-[-4rem] h-[31rem] w-[31rem] rounded-full border border-border/20" />
      <div className="absolute right-[-13rem] top-[-4rem] h-[35rem] w-[35rem] rounded-full bg-accent/20 blur-3xl" />
      <div className="absolute right-[-3rem] top-24 h-[27rem] w-[17rem] rotate-12 rounded-[50%] border border-accent/20 bg-gradient-to-b from-accent/30 via-accent/12 to-transparent blur-sm" />
      <div className="absolute inset-x-0 top-[34rem] h-px bg-border/45" />
    </div>
  );
}
