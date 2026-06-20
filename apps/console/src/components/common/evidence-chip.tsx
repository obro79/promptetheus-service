import * as React from "react";
import {
  AlertTriangle,
  Camera,
  Code2,
  FileText,
  Mic2,
  Video,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

export type EvidenceKind =
  | "screenshot"
  | "dom_snapshot"
  | "video"
  | "audio"
  | "text"
  | "warning";

const KIND_CONFIG: Record<
  EvidenceKind,
  { Icon: LucideIcon; tone: string }
> = {
  screenshot: { Icon: Camera, tone: "text-accent" },
  dom_snapshot: { Icon: Code2, tone: "text-accent" },
  video: { Icon: Video, tone: "text-accent" },
  audio: { Icon: Mic2, tone: "text-accent" },
  text: { Icon: FileText, tone: "text-muted-foreground" },
  warning: { Icon: AlertTriangle, tone: "text-warning" },
};

export interface EvidenceChipProps {
  kind: EvidenceKind;
  label: string;
  onClick?: () => void;
  className?: string;
}

export function EvidenceChip({
  kind,
  label,
  onClick,
  className,
}: EvidenceChipProps) {
  const { Icon, tone } = KIND_CONFIG[kind];
  const interactive = typeof onClick === "function";

  const content = (
    <>
      <Icon className={cn("size-3 shrink-0", tone)} />
      <span className="truncate text-xs text-muted-foreground">{label}</span>
    </>
  );

  const base =
    "inline-flex max-w-full items-center gap-1.5 rounded-md bg-elevated px-2 py-1.5 leading-none";

  if (interactive) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={cn(
          base,
          "transition-colors duration-150 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          className,
        )}
      >
        {content}
      </button>
    );
  }

  return <span className={cn(base, className)}>{content}</span>;
}
