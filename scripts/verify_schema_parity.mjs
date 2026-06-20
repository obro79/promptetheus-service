#!/usr/bin/env node
/** Verify fixture events pass a zod mirror of generated schema.ts. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(join(root, "apps/console/package.json"));
const { z } = require("zod");

const schemaTs = readFileSync(
  join(root, "apps/console/src/lib/schema.ts"),
  "utf8",
);
const match = schemaTs.match(/export const EVENT_TYPES = (\[[^\n]+\]) as const;/);
if (!match) {
  console.error("could not read EVENT_TYPES from generated schema.ts");
  process.exit(1);
}
const eventTypes = JSON.parse(match[1]);
const EventSchema = z
  .object({
    type: z.enum(eventTypes),
    session_id: z.string().min(1),
    timestamp: z.string(),
    seq: z.number().int().min(0),
    idempotency_key: z.string().min(1),
    payload: z.record(z.unknown()),
    metadata: z.record(z.unknown()).optional(),
    span_id: z.string().min(1).optional(),
    parent_id: z.string().nullable().optional(),
  })
  .passthrough();

const fixtures = JSON.parse(
  readFileSync(join(root, "tests/fixtures/schema_parity_samples.json"), "utf8")
);

for (const [index, event] of fixtures.entries()) {
  const result = EventSchema.safeParse(event);
  if (!result.success) {
    console.error(`fixture ${index} failed zod parse:`, result.error.format());
    process.exit(1);
  }
}

console.log(`schema parity ok (${fixtures.length} events)`);
