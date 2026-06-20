import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";

import "./globals.css";

import { AppFrame } from "@/components/shell/app-frame";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const themeInitializer = `
  try {
    var theme = localStorage.getItem("promptetheus.theme");
    var root = document.documentElement;
    root.classList.remove("dark", "light");
    root.classList.add(theme === "dark" ? "dark" : "light");
  } catch {}
`;

export const metadata: Metadata = {
  title: "Promptetheus — Agent debugging console",
  description:
    "Observe, detect, replay, attribute, fix, and prevent agent failures.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={cn("light", GeistSans.variable, GeistMono.variable)}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitializer }} />
      </head>
      <body className="bg-canvas font-sans text-foreground antialiased">
        <TooltipProvider delayDuration={200}>
          <a
            href="#main-content"
            className="fixed left-3 top-3 z-[100] -translate-y-20 rounded bg-accent px-3 py-2 text-sm font-medium text-accent-foreground focus:translate-y-0"
          >
            Skip to content
          </a>
          <AppFrame>{children}</AppFrame>
        </TooltipProvider>
      </body>
    </html>
  );
}
