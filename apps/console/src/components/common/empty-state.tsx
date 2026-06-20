import * as React from "react";
import type { LucideIcon } from "lucide-react";
import Image from "next/image";

import { cn } from "@/lib/utils";

export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  icon?: LucideIcon;
  illustration?: {
    src: string;
    width: number;
    height: number;
    className?: string;
  };
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({
  icon: Icon,
  illustration,
  title,
  description,
  action,
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-4 rounded-lg bg-panel/60 px-6 py-14 text-center",
        className,
      )}
      {...props}
    >
      {illustration ? (
        <Image
          src={illustration.src}
          width={illustration.width}
          height={illustration.height}
          alt=""
          aria-hidden="true"
          sizes={`${illustration.width}px`}
          className={cn("h-auto max-w-full object-contain", illustration.className)}
        />
      ) : Icon ? (
        <div className="flex size-10 items-center justify-center rounded-lg bg-elevated text-muted-foreground">
          <Icon className="size-5" />
        </div>
      ) : null}
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        {description ? (
          <p className="text-balance max-w-sm text-[13px] leading-relaxed text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
