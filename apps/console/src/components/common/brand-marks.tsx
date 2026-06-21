/**
 * Inline SVG brand marks for the infrastructure the heal loop runs on, so the
 * Runs DAG and the Actions list can show *who did what* with recognizable logos
 * instead of generic icons. These are simplified, brand-colored marks (not the
 * exact trademarked logos) drawn at 1em so they inherit sizing from `className`.
 */
import { cn } from "@/lib/utils";

type MarkProps = {
  className?: string;
  title?: string;
};

/** Browserbase — stylized browser frame on a base line. */
export function BrowserbaseMark({ className, title = "Browserbase" }: MarkProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("size-4", className)}
      role="img"
      aria-label={title}
      fill="none"
    >
      <title>{title}</title>
      <rect x="3" y="4" width="18" height="13" rx="2.5" stroke="#F4A23B" strokeWidth="1.6" />
      <path d="M3 8h18" stroke="#F4A23B" strokeWidth="1.6" />
      <circle cx="6" cy="6" r="0.9" fill="#F4A23B" />
      <path d="M8 21h8M12 17v4" stroke="#F4A23B" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** Redis — the classic stacked-cube silhouette, simplified. */
export function RedisMark({ className, title = "Redis" }: MarkProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("size-4", className)}
      role="img"
      aria-label={title}
      fill="none"
    >
      <title>{title}</title>
      <path
        d="M12 4 21 8l-9 4-9-4 9-4Z"
        stroke="#DC382C"
        strokeWidth="1.5"
        strokeLinejoin="round"
        fill="#DC382C"
        fillOpacity="0.12"
      />
      <path
        d="M3 12l9 4 9-4"
        stroke="#DC382C"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M3 16l9 4 9-4"
        stroke="#DC382C"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Devin (Cognition) — rounded orb monogram. */
export function DevinMark({ className, title = "Devin" }: MarkProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("size-4", className)}
      role="img"
      aria-label={title}
      fill="none"
    >
      <title>{title}</title>
      <circle cx="12" cy="12" r="8.5" stroke="#6E56CF" strokeWidth="1.6" />
      <path
        d="M9.5 8.2v7.6c2.6 0 4.4-1.5 4.4-3.8s-1.8-3.8-4.4-3.8Z"
        fill="#6E56CF"
      />
    </svg>
  );
}

/** Claude / Anthropic — the sunburst mark, simplified. */
export function ClaudeMark({ className, title = "Claude" }: MarkProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("size-4", className)}
      role="img"
      aria-label={title}
      fill="#D97757"
    >
      <title>{title}</title>
      <path d="M12 2.6c.5 3 .9 4.7 1.7 5.8.8 1 2.5 1.6 5.7 2.4-3.2.8-4.9 1.4-5.7 2.4-.8 1.1-1.2 2.8-1.7 5.8-.5-3-.9-4.7-1.7-5.8-.8-1-2.5-1.6-5.7-2.4 3.2-.8 4.9-1.4 5.7-2.4.8-1.1 1.2-2.8 1.7-5.8Z" />
    </svg>
  );
}
