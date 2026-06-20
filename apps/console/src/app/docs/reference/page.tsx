import Link from "next/link";
import { ArrowLeft, ListTree, Radio } from "lucide-react";

import { apiDocs, type ApiEndpoint } from "@/lib/api-docs";
import { CodeBlock } from "@/components/docs/code-block";
import { EndpointMethodBadge, EndpointTable } from "@/components/docs/endpoint-table";
import { Badge } from "@/components/ui/badge";
import {
  ConsolePage,
  ConsolePageContent,
  ConsoleEyebrow,
} from "@/components/common/console-primitives";

export const metadata = {
  title: "Endpoint Reference - Promptetheus API Docs",
};

const BATCH_RESPONSE = `{
  "accepted": 1,
  "rejected": [
    {
      "index": 1,
      "idempotency_key": "trace_curl_1:dev:1",
      "reason": "seq must be monotonic for this session"
    }
  ]
}`;

const SSE_EXAMPLE = `curl "http://127.0.0.1:4318/api/stream?project_id=proj_acmemeet&after_seq=18" \\
  -H "Authorization: Bearer $SUPABASE_SESSION_JWT" \\
  -H "Accept: text/event-stream"`;

export default function ReferencePage() {
  const groupedEndpoints = apiDocs.endpoints.reduce<Record<string, ApiEndpoint[]>>(
    (groups, endpoint) => {
      groups[endpoint.group] = groups[endpoint.group] ?? [];
      groups[endpoint.group].push(endpoint);
      return groups;
    },
    {},
  );

  return (
    <ConsolePage>
      <ConsolePageContent className="flex max-w-[1180px] flex-col gap-7">
      <Link href="/docs" className="inline-flex w-fit items-center gap-1.5 text-xs font-medium text-accent hover:underline">
        <ArrowLeft className="size-3.5" aria-hidden="true" />
        Docs
      </Link>
      <header id="auth" className="border-b border-border/40 pb-6">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <ConsoleEyebrow icon={<ListTree className="size-3.5" aria-hidden />} className="mb-0">
            Endpoint reference
          </ConsoleEyebrow>
          <Badge variant="secondary">14 endpoints</Badge>
        </div>
        <h1 className="display text-4xl leading-[0.96] text-foreground sm:text-5xl">
          The locked FastAPI surface
        </h1>
        <p className="mt-4 max-w-3xl text-sm leading-6 text-muted-foreground">
          Local and hosted deployments use the same API shape. Hosted routes may add a
          project prefix later, but the request bodies and semantics stay aligned.
        </p>
      </header>

      <section className="grid gap-4 md:grid-cols-3">
        {apiDocs.auth.map((auth) => (
          <div key={auth.id} className="surface rounded-2xl p-5">
            <h2 className="text-sm font-semibold text-foreground">{auth.label}</h2>
            <p className="mono mt-2 break-words text-xs text-accent">{auth.credential}</p>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{auth.description}</p>
          </div>
        ))}
      </section>

      <EndpointTable />

      <section className="space-y-4">
        {Object.entries(groupedEndpoints).map(([group, endpoints]) => (
          <div key={group} className="surface overflow-hidden rounded-2xl">
            <div className="border-b border-border/50 bg-muted/30 px-4 py-3">
              <h2 className="text-sm font-medium text-foreground">{group}</h2>
            </div>
            <div className="divide-y divide-border/50">
              {endpoints.map((endpoint) => (
                <div
                  key={endpoint.id}
                  className="grid gap-2 px-4 py-3 text-xs md:grid-cols-[76px_minmax(220px,0.8fr)_minmax(0,1fr)] md:items-center"
                >
                  <EndpointMethodBadge method={endpoint.method} />
                  <span className="mono min-w-0 break-all text-foreground">{endpoint.path}</span>
                  <span className="leading-relaxed text-muted-foreground">{endpoint.purpose}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <CodeBlock code={BATCH_RESPONSE} language="json" filename="batch-response.json" title="Batch response" />
        <CodeBlock code={SSE_EXAMPLE} language="bash" filename="stream.sh" title="SSE stream" />
      </section>

      <section className="surface rounded-2xl p-5">
        <Radio className="mb-3 size-4 text-accent" aria-hidden="true" />
        <h2 className="text-sm font-medium text-foreground">SSE reconnect behavior</h2>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          {apiDocs.sse.reconnect}
        </p>
      </section>

      <section className="surface overflow-hidden rounded-2xl">
        <div className="border-b border-border/50 bg-muted/30 px-4 py-3">
          <h2 className="text-sm font-medium text-foreground">Standard errors</h2>
        </div>
        <table className="w-full border-collapse text-sm">
          <tbody>
            {apiDocs.errors.map((error) => (
              <tr key={error.status} className="border-b border-border/50 last:border-0 hover:bg-elevated/30">
                <td className="px-3 py-2 align-top">
                  <span className="mono text-xs text-foreground">{error.status}</span>
                </td>
                <td className="px-3 py-2 align-top">
                  <Badge variant={error.retry === "backoff" ? "warning" : error.retry === "no" ? "secondary" : "outline"}>
                    {error.retry}
                  </Badge>
                </td>
                <td className="px-3 py-2 align-top text-xs leading-relaxed text-muted-foreground">
                  {error.label}: {error.meaning}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      </ConsolePageContent>
    </ConsolePage>
  );
}
