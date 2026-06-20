"use client";

import * as React from "react";

export function AppFrame({ children }: { children: React.ReactNode }) {
  return (
    <main id="main-content" className="min-h-dvh overflow-x-hidden bg-canvas">
      {children}
    </main>
  );
}
