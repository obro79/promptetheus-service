import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "group/btn relative inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-semibold transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-canvas disabled:pointer-events-none disabled:opacity-45 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-accent text-accent-foreground shadow-[0_16px_32px_hsl(var(--accent)/0.24)] hover:bg-accent-bright hover:shadow-[0_18px_42px_hsl(var(--accent)/0.3)] active:bg-accent/90",
        secondary:
          "border border-border/80 bg-panel/80 text-secondary-foreground shadow-sm hover:bg-elevated active:bg-elevated/80",
        ghost: "text-muted-foreground hover:bg-panel/70 hover:text-foreground",
        outline:
          "border border-border/90 bg-panel/30 text-foreground hover:border-accent/35 hover:bg-panel/80",
        destructive:
          "bg-destructive text-destructive-foreground shadow-[0_16px_32px_hsl(var(--destructive)/0.18)] hover:bg-destructive/90 active:bg-destructive/80",
        link: "text-accent underline-offset-4 hover:underline hover:text-accent-bright",
      },
      size: {
        sm: "min-h-8 px-2.5 text-xs [&_svg]:size-3.5",
        md: "min-h-10 px-3.5",
        lg: "min-h-11 px-5 text-sm",
        icon: "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "md",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
