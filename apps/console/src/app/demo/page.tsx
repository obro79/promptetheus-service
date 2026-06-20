import {
  LandingAppShell,
  LandingCard,
  LandingSection,
} from "@/components/landing/landing-primitives";

const demoAgents = ["Browser Agent", "Voice Agent", "Chat Agent"] as const;

export default function DemoPage() {
  return (
    <LandingAppShell>
      <LandingSection
        className="min-h-dvh py-5 sm:py-6 lg:h-dvh lg:min-h-0 lg:py-8"
        containerClassName="landing-use-case-container flex min-h-[calc(100dvh-2.5rem)] items-stretch lg:min-h-[calc(100dvh-4rem)]"
      >
        <h1 className="sr-only">Promptetheus demo agents</h1>
        <div className="landing-use-case-grid min-h-full w-full">
          {demoAgents.map((agent) => (
            <LandingCard
              key={agent}
              as="article"
              size="compact"
              className="landing-use-case-card group min-h-full transition-transform duration-200 hover:-translate-y-1"
            >
              <div className="landing-use-case-copy">
                <h2 className="text-2xl font-semibold text-foreground">{agent}</h2>
              </div>
            </LandingCard>
          ))}
        </div>
      </LandingSection>
    </LandingAppShell>
  );
}
