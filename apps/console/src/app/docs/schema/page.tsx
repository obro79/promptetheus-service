import Link from "next/link";
import { ArrowLeft, Braces } from "lucide-react";

import { apiDocs } from "@/lib/api-docs";
import {
  EventSchemaGrid,
  SchemaFieldTable,
} from "@/components/docs/schema-event-cards";
import { Badge } from "@/components/ui/badge";
import {
  ConsolePage,
  ConsolePageContent,
  ConsoleEyebrow,
} from "@/components/common/console-primitives";

export const metadata = {
  title: "Event Schema - Promptetheus API Docs",
};

export default function SchemaPage() {
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
            <ConsoleEyebrow icon={<Braces className="size-3.5" aria-hidden />} className="mb-0">
              Event schema
            </ConsoleEyebrow>
            <Badge variant="secondary">
              {apiDocs.schema.eventTypes.length} event types
            </Badge>
          </div>
          <h1 className="display text-4xl leading-[0.96] text-foreground sm:text-5xl">
            One envelope, typed payloads
          </h1>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-muted-foreground">
            The Python TypedDict schema is the source of truth and the console
            mirrors it in zod. Unknown envelope fields pass through, but
            ordering and idempotency are enforced.
          </p>
        </header>

        <SchemaFieldTable
          fields={apiDocs.schema.envelopeFields}
          description={`${apiDocs.schema.sourceOfTruth} mirrors into ${apiDocs.schema.consoleMirror}. ${apiDocs.schema.orderingRule}`}
        />

        <EventSchemaGrid
          events={apiDocs.schema.eventTypes.map((event) => ({
            type: event.type,
            reserved: event.reserved,
            description: event.summary,
            fields: event.fields,
          }))}
        />
      </ConsolePageContent>
    </ConsolePage>
  );
}
