import Link from "next/link";
import { ArrowLeft, Terminal } from "lucide-react";

import { apiDocs } from "@/lib/api-docs";
import { CodeSampleGrid } from "@/components/docs/code-block";
import { Badge } from "@/components/ui/badge";
import {
  ConsolePage,
  ConsolePageContent,
  ConsoleEyebrow,
} from "@/components/common/console-primitives";

export const metadata = {
  title: "Quickstart - Promptetheus API Docs",
};

export default function QuickstartPage() {
  return (
    <DocsArticle
      eyebrow="Quickstart"
      title="Send the first trace"
      description="Use the SDK for normal integrations. Raw HTTP is the same contract underneath for non-Python agents and fixtures."
      icon={<Terminal className="size-4" aria-hidden="true" />}
    >
      <div className="space-y-5">
        {apiDocs.quickstart.map((step, index) => (
          <section
            key={step.id}
            className="surface grid gap-4 rounded-2xl p-5 xl:grid-cols-[220px_minmax(0,1fr)]"
          >
            <div className="min-w-0">
              <div className="mb-2 flex items-center gap-2">
                <span className="mono inline-flex size-7 items-center justify-center rounded-md bg-accent/10 text-xs font-semibold text-accent">
                  {index + 1}
                </span>
                <h2 className="text-sm font-semibold text-foreground">{step.title}</h2>
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">{step.description}</p>
            </div>
            <CodeSampleGrid
              samples={step.examples.map((example) => ({
                id: example.id,
                title: example.label,
                code: example.code,
                language: example.language,
                filename: example.filename,
              }))}
            />
          </section>
        ))}
      </div>
    </DocsArticle>
  );
}

function DocsArticle({
  eyebrow,
  title,
  description,
  icon,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <ConsolePage>
      <ConsolePageContent className="flex max-w-[1180px] flex-col gap-7">
        <Link
          href="/docs"
          className="inline-flex w-fit items-center gap-1.5 text-xs font-medium text-accent hover:underline"
        >
          <ArrowLeft className="size-3.5" aria-hidden="true" />
          Docs
        </Link>
        <header className="border-b border-border/40 pb-6">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <ConsoleEyebrow icon={icon} className="mb-0">
              {eyebrow}
            </ConsoleEyebrow>
            <Badge variant="secondary">Promptetheus API</Badge>
          </div>
          <h1 className="display text-4xl leading-[0.96] text-foreground sm:text-5xl">
            {title}
          </h1>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        </header>
        {children}
      </ConsolePageContent>
    </ConsolePage>
  );
}
