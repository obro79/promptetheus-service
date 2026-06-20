import { notFound } from "next/navigation";
import { AlertTriangle, Crosshair, Radio, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Eyebrow,
  LandingAppContent,
  LandingAppShell,
  LandingCard,
  LandingSection,
} from "@/components/landing/landing-primitives";

const SWATCHES = [
  ["Canvas", "bg-canvas"],
  ["Panel", "bg-panel"],
  ["Raised", "bg-elevated"],
  ["Focus", "bg-accent"],
  ["Warning", "bg-warning"],
  ["Destructive", "bg-destructive"],
] as const;

export default function DesignSystemPage() {
  if (process.env.NODE_ENV === "production") notFound();

  return (
    <LandingAppShell>
      <LandingSection density="compact" containerClassName="max-w-5xl">
        <Eyebrow>Internal fixture</Eyebrow>
        <h1 className="landing-display-lg">Observability interface system</h1>
        <p className="landing-copy mt-5 max-w-2xl">Token and component reference for integrated, evidence-first agent debugging.</p>
      </LandingSection>

      <LandingAppContent compact className="max-w-5xl space-y-8">
      <section>
        <h2 className="mb-3 text-sm font-semibold">Color signals</h2>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
          {SWATCHES.map(([label, color]) => (
            <div key={label} className="landing-framed-surface overflow-hidden">
              <div className={`h-16 ${color}`} />
              <p className="px-2.5 py-2 text-xs text-muted-foreground">{label}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-5 md:grid-cols-2">
        <LandingCard size="compact">
          <p className="micro mb-3">Actions</p>
          <div className="flex flex-wrap gap-2"><Button>Generate regression</Button><Button variant="secondary">Open replay</Button><Button variant="outline">Assign</Button><Button variant="destructive">Delete</Button></div>
        </LandingCard>
        <LandingCard size="compact">
          <p className="micro mb-3">Field</p>
          <label className="mb-1.5 block text-xs font-medium" htmlFor="fixture-search">Search events</label>
          <div className="relative"><Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" /><Input id="fixture-search" className="pl-9" placeholder="tool.call, user correction…" /></div>
        </LandingCard>
      </section>

      <section className="landing-framed-surface overflow-hidden">
        <div className="instrument-header"><span className="micro">State language</span><span className="text-[11px] text-muted-foreground">Icon + text + color</span></div>
        <div className="grid divide-y divide-border/70 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          <State Icon={Radio} label="Live" detail="Following event stream" tone="text-accent" />
          <State Icon={Crosshair} label="Critical step" detail="Selected cause" tone="text-warning" />
          <State Icon={AlertTriangle} label="Failure" detail="Goal was not achieved" tone="text-destructive" />
        </div>
      </section>
      </LandingAppContent>
    </LandingAppShell>
  );
}

function State({ Icon, label, detail, tone }: { Icon: typeof Radio; label: string; detail: string; tone: string }) {
  return <div className="flex items-center gap-3 bg-panel p-4"><Icon className={`size-4 ${tone}`} /><div><p className="text-sm font-medium">{label}</p><p className="text-xs text-muted-foreground">{detail}</p></div></div>;
}
