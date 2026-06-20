import * as React from "react";
import { Boxes, Braces, Database } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface SchemaField {
  name: string;
  type: string;
  required?: boolean;
  description?: string;
}

export interface SchemaEvent {
  type: string;
  fields: SchemaField[];
  reserved?: boolean;
  description?: string;
}

export const EVENT_ENVELOPE_FIELDS: SchemaField[] = [
  { name: "type", type: "EventType", required: true },
  { name: "session_id", type: "string", required: true },
  { name: "timestamp", type: "ISO 8601 string", required: true },
  { name: "seq", type: "integer >= 0", required: true },
  { name: "idempotency_key", type: "string", required: true },
  { name: "payload", type: "object", required: true },
  { name: "metadata", type: "object", required: false },
  { name: "span_id", type: "string", required: false },
  { name: "parent_id", type: "string | null", required: false },
];

export interface SchemaFieldTableProps {
  fields?: SchemaField[];
  title?: string;
  description?: string;
  className?: string;
}

export function SchemaFieldTable({
  fields = EVENT_ENVELOPE_FIELDS,
  title = "Event envelope",
  description,
  className,
}: SchemaFieldTableProps) {
  return (
    <section className={cn("overflow-hidden rounded-lg bg-panel", className)}>
      <div className="flex items-start gap-3 border-b border-border bg-elevated/30 px-4 py-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">
          <Database className="size-4" />
        </span>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          {description ? (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-elevated/20 text-left">
              <th className="px-3 py-2 text-[11px] font-medium text-muted-foreground">
                Field
              </th>
              <th className="px-3 py-2 text-[11px] font-medium text-muted-foreground">
                Type
              </th>
              <th className="px-3 py-2 text-[11px] font-medium text-muted-foreground">
                Required
              </th>
              <th className="hidden px-3 py-2 text-[11px] font-medium text-muted-foreground md:table-cell">
                Notes
              </th>
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => (
              <tr
                key={field.name}
                className="border-b border-border/60 transition-colors duration-150 last:border-0 hover:bg-elevated/40"
              >
                <td className="px-3 py-2 align-middle">
                  <span className="mono text-xs text-foreground">
                    {field.name}
                  </span>
                </td>
                <td className="px-3 py-2 align-middle">
                  <span className="mono text-xs text-muted-foreground">
                    {field.type}
                  </span>
                </td>
                <td className="px-3 py-2 align-middle">
                  {field.required ? (
                    <Badge variant="accent">required</Badge>
                  ) : (
                    <Badge variant="secondary">optional</Badge>
                  )}
                </td>
                <td className="hidden px-3 py-2 align-middle md:table-cell">
                  <span className="text-xs text-muted-foreground">
                    {field.description ?? "Pass-through safe"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export interface EventSchemaGridProps {
  events: SchemaEvent[];
  className?: string;
  maxFields?: number;
}

export function EventSchemaGrid({
  events,
  className,
  maxFields = 5,
}: EventSchemaGridProps) {
  return (
    <div className={cn("grid grid-cols-1 gap-3 sm:grid-cols-2", className)}>
      {events.map((event) => (
        <EventSchemaCard
          key={event.type}
          event={event}
          maxFields={maxFields}
        />
      ))}
    </div>
  );
}

export interface EventSchemaCardProps {
  event: SchemaEvent;
  maxFields?: number;
  className?: string;
}

export function EventSchemaCard({
  event,
  maxFields = 5,
  className,
}: EventSchemaCardProps) {
  const visibleFields = event.fields.slice(0, maxFields);
  const hiddenCount = Math.max(0, event.fields.length - visibleFields.length);

  return (
    <article
      className={cn(
        "flex min-h-44 flex-col overflow-hidden rounded-lg bg-panel transition-colors duration-150 hover:bg-elevated/70",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Braces className="size-3.5 shrink-0 text-accent" />
          <span className="mono truncate text-xs font-medium text-accent">
            {event.type}
          </span>
        </div>
        {event.reserved ? <Badge variant="warning">reserved</Badge> : null}
      </div>

      <div className="flex flex-1 flex-col px-3 py-2.5">
        {event.description ? (
          <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
            {event.description}
          </p>
        ) : null}

        {visibleFields.length === 0 ? (
          <p className="text-[11px] italic text-muted-foreground/70">
            no payload fields
          </p>
        ) : (
          <dl className="space-y-1.5">
            {visibleFields.map((field) => (
              <div
                key={field.name}
                className="flex min-w-0 items-baseline justify-between gap-3"
              >
                <dt className="mono truncate text-[11px] text-foreground/90">
                  {field.name}
                </dt>
                <dd className="mono max-w-[55%] truncate text-right text-[11px] text-muted-foreground">
                  {field.type}
                </dd>
              </div>
            ))}
          </dl>
        )}

        <div className="mt-auto flex items-center justify-between gap-3 pt-3">
          <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
            <Boxes className="size-3" />
            {event.fields.length} payload fields
          </span>
          {hiddenCount > 0 ? (
            <Badge variant="outline">+{hiddenCount} more</Badge>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export interface SchemaJsonShape {
  events: Record<
    string,
    {
      properties?: Record<string, { type?: unknown; enum?: unknown }>;
      reserved?: boolean;
      description?: string;
    }
  >;
}

export function eventsFromSchemaJson(
  schema: SchemaJsonShape,
  eventTypes: string[],
): SchemaEvent[] {
  return eventTypes.map((type) => {
    const event = schema.events[type];

    return {
      type,
      reserved: Boolean(event?.reserved),
      description: event?.description,
      fields: Object.entries(event?.properties ?? {}).map(([name, def]) => ({
        name,
        type: formatSchemaType(def),
      })),
    };
  });
}

function formatSchemaType(def: { type?: unknown; enum?: unknown }): string {
  if (Array.isArray(def.enum)) {
    return def.enum.map((value) => `"${String(value)}"`).join(" | ");
  }

  if (typeof def.type === "string") return def.type;
  if (Array.isArray(def.type)) return def.type.map(String).join(" | ");

  return "any";
}
