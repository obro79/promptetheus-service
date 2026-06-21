"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

/**
 * Re-runs the (server) logs page on an interval so newly ingested runs appear
 * without a manual reload. The page reads with `cache: "no-store"`, so a
 * `router.refresh()` re-fetches live data.
 */
export function LogsAutoRefresh({ intervalMs = 4000 }: { intervalMs?: number }) {
  const router = useRouter();
  React.useEffect(() => {
    const id = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(id);
  }, [router, intervalMs]);
  return null;
}
