import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  Braces,
  Code2,
  ListTree,
  Terminal,
} from "lucide-react";

import { apiDocs } from "@/lib/api-docs";
import {
  ConsolePage,
  ConsolePageContent,
  ConsolePageHeader,
  ConsoleEyebrow,
} from "@/components/common/console-primitives";
import { Badge } from "@/components/ui/badge";

export const metadata = {
  title: "API Docs - Promptetheus",
  description: "A focused guide to Promptetheus trace ingestion and API contracts.",
};

const DOC_PAGES = [
  {
    href: "/docs/quickstart",
    title: "Quickstart",
    description: "Install, configure, create a trace, and append your first event batch.",
    icon: Terminal,
    meta: "Start here",
  },
  {
    href: "/docs/reference",
    title: "Endpoint reference",
    description: "The locked 14-endpoint FastAPI surface with auth, errors, and SSE notes.",
    icon: ListTree,
    meta: "14 endpoints",
  },
  {
    href: "/docs/schema",
    title: "Event schema",
    description: "Envelope fields, payload types, ordering, idempotency, and schema parity.",
    icon: Braces,
    meta: `${apiDocs.schema.eventTypes.length} event types`,
  },
  {
    href: "/docs/examples",
    title: "Examples",
    description: "Copyable SDK and raw HTTP snippets for common integration paths.",
    icon: Code2,
    meta: "SDK + curl",
  },
];

export default function DocsPage() {
  return (
    <ConsolePage>
      <ConsolePageHeader narrow>
        <div className="min-w-0">
          <ConsoleEyebrow icon={<BookOpen className="size-3.5" strokeWidth={1.8} aria-hidden />}>
            API docs
          </ConsoleEyebrow>
          <h1 className="display text-5xl leading-[0.92] text-foreground sm:text-6xl">
            Promptetheus API
          </h1>
          <p className="mt-5 max-w-2xl text-sm leading-6 text-muted-foreground">
            Focused references for sending trace events, reading replay data,
            and driving analysis, fix-agent, and regression workflows through
            FastAPI.
          </p>
        </div>
      </ConsolePageHeader>

      <ConsolePageContent narrow className="flex flex-col gap-6 py-8">
        <section className="grid gap-3">
          {DOC_PAGES.map(({ href, title, description, icon: Icon, meta }) => (
            <Link
              key={href}
              href={href}
              className="surface surface-hover group grid gap-3 rounded-2xl p-5 transition-colors duration-150 sm:grid-cols-[2.5rem_minmax(0,1fr)_auto] sm:items-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="inline-flex size-10 items-center justify-center rounded-full border border-accent/20 bg-accent-muted text-accent">
                <Icon className="size-4" aria-hidden="true" strokeWidth={1.7} />
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-sm font-semibold tracking-tight text-foreground">
                    {title}
                  </h2>
                  <Badge variant="secondary" className="px-1.5 py-0.5 text-[10px]">
                    {meta}
                  </Badge>
                </div>
                <p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">
                  {description}
                </p>
              </div>
              <ArrowRight
                className="size-3.5 text-muted-foreground transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-accent sm:justify-self-end"
                aria-hidden="true"
              />
            </Link>
          ))}
        </section>

        <section className="surface grid gap-3 rounded-2xl p-5 text-xs leading-5 text-muted-foreground sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
          <div className="min-w-0">
            <p>
              Local base URL:{" "}
              <span className="mono text-foreground">
                {apiDocs.overview.baseUrls[0].url}
              </span>
            </p>
            <p className="mt-1">
              Auth: project API keys for SDK ingestion, Supabase JWTs for
              console reads, server-only credentials for internal writeback.
            </p>
          </div>
          <Link
            href="/docs/reference#auth"
            className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline sm:justify-self-end"
          >
            Auth details
            <ArrowRight className="size-3" aria-hidden="true" />
          </Link>
        </section>
      </ConsolePageContent>
    </ConsolePage>
  );
}
