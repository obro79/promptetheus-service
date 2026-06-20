import Link from "next/link";
import { ArrowLeft, Code2 } from "lucide-react";

import { apiDocs } from "@/lib/api-docs";
import { CodeSampleGrid } from "@/components/docs/code-block";
import { Badge } from "@/components/ui/badge";
import {
  ConsolePage,
  ConsolePageContent,
  ConsoleEyebrow,
} from "@/components/common/console-primitives";

export const metadata = {
  title: "Examples - Promptetheus API Docs",
};

export default function ExamplesPage() {
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
            <ConsoleEyebrow icon={<Code2 className="size-3.5" aria-hidden />} className="mb-0">
              Examples
            </ConsoleEyebrow>
            <Badge variant="secondary">copyable snippets</Badge>
          </div>
          <h1 className="display text-4xl leading-[0.96] text-foreground sm:text-5xl">
            SDK and raw HTTP examples
          </h1>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-muted-foreground">
            Small snippets for the common integration paths. Adapters should
            stay thin and emit through the public Session API.
          </p>
        </header>

        <section>
          <h2 className="mb-3 text-sm font-semibold text-foreground">
            SDK helpers
          </h2>
          <CodeSampleGrid
            samples={apiDocs.sdkExamples.map((example) => ({
              id: example.id,
              title: example.label,
              code: example.code,
              language: example.language,
              filename: example.filename,
            }))}
          />
        </section>

        <section>
          <h2 className="mb-3 text-sm font-semibold text-foreground">
            Raw HTTP
          </h2>
          <CodeSampleGrid
            samples={apiDocs.rawHttpExamples.map((example) => ({
              id: example.id,
              title: example.label,
              code: example.code,
              language: example.language,
              filename: example.filename,
            }))}
          />
        </section>
      </ConsolePageContent>
    </ConsolePage>
  );
}
