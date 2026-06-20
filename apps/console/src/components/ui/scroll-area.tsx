import * as React from "react";

import { cn } from "@/lib/utils";

export type ScrollAreaProps = React.HTMLAttributes<HTMLDivElement>;

/**
 * Lightweight styled overflow wrapper. Uses the global thin-scrollbar styling
 * from globals.css; no Radix dependency needed for the console's use cases.
 */
const ScrollArea = React.forwardRef<HTMLDivElement, ScrollAreaProps>(
  ({ className, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          "relative overflow-auto overscroll-contain [scrollbar-gutter:stable]",
          className,
        )}
        {...props}
      >
        {children}
      </div>
    );
  },
);
ScrollArea.displayName = "ScrollArea";

export { ScrollArea };
