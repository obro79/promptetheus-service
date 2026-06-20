import type { Metadata } from "next";

import { LandingPage } from "@/components/landing/landing-page";
import { getOverviewStats } from "@/lib/data";

export const metadata: Metadata = {
  title: "Promptetheus — Incident response for AI agents",
  description:
    "Trace, replay, diagnose, fix, and prevent repeated AI agent failures.",
};

export default function Page() {
  return <LandingPage stats={getOverviewStats()} />;
}
