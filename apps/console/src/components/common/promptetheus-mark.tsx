import { cn } from "@/lib/utils";

export function PromptetheusMark({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={cn("size-5", className)}
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="M7.65 8.4L12.05 12.05L16.35 7.8M12.05 12.05L8.15 16.45M12.05 12.05L16.7 16.15"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
      />
      <circle cx="12.05" cy="12.05" r="2.15" fill="currentColor" />
      <circle cx="7.65" cy="8.4" r="1.65" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="16.7" cy="16.15" r="1.65" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}
