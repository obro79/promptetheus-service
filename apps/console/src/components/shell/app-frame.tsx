"use client";

import * as React from "react";
import { usePathname } from "next/navigation";

import { AppSidebar } from "@/components/shell/app-sidebar";
import { TopBar } from "@/components/shell/top-bar";

export function AppFrame({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isStandalone = pathname === "/" || pathname === "/demo";

  if (isStandalone) {
    return (
      <main id="main-content" className="min-h-dvh overflow-x-hidden">
        {children}
      </main>
    );
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      <AppSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main id="main-content" className="min-h-0 flex-1 overflow-y-auto bg-canvas">
          {children}
        </main>
      </div>
    </div>
  );
}
