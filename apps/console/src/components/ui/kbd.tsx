import * as React from "react";

import { cn } from "@/lib/utils";

export type KbdProps = React.HTMLAttributes<HTMLElement>;

const Kbd = React.forwardRef<HTMLElement, KbdProps>(
  ({ className, children, ...props }, ref) => {
    return (
      <kbd
        ref={ref}
        className={cn(
          "mono inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded border border-border bg-elevated px-1.5 text-[10px] font-medium uppercase leading-none tracking-wide text-muted-foreground",
          className,
        )}
        {...props}
      >
        {children}
      </kbd>
    );
  },
);
Kbd.displayName = "Kbd";

export { Kbd };
