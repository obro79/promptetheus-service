import * as React from "react";

import { cn } from "@/lib/utils";

export interface LabelTagProps extends React.HTMLAttributes<HTMLSpanElement> {
  label: string;
}

export function LabelTag({ label, className, ...props }: LabelTagProps) {
  return (
    <span
      className={cn(
        "mono inline-flex items-center whitespace-nowrap rounded-md bg-elevated px-2 py-1 text-[11px] leading-none text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground",
        className,
      )}
      {...props}
    >
      {label}
    </span>
  );
}
