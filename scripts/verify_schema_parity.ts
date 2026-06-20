/** Verify Python validate_event and TS zod agree on fixture events. */
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { validateEvent } from "../apps/console/src/lib/schema.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const fixturesPath = join(root, "tests/fixtures/schema_parity_samples.json");
const samples = JSON.parse(readFileSync(fixturesPath, "utf8")) as unknown[];

let failed = 0;
for (const [index, event] of samples.entries()) {
  try {
    validateEvent(event);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(`TS zod rejected sample ${index}:`, message);
    failed += 1;
    continue;
  }
  const py = spawnSync(
    "python3",
    [
      "-c",
      "import json,sys; from promptetheus.schema import validate_event; validate_event(json.load(sys.stdin))",
    ],
    {
      input: JSON.stringify(event),
      encoding: "utf8",
      cwd: join(root, "packages/promptetheus"),
      env: { ...process.env, PYTHONPATH: join(root, "packages/promptetheus") },
    },
  );
  if (py.status !== 0) {
    console.error(`Python rejected sample ${index}:`, py.stderr || py.stdout);
    failed += 1;
  }
}

if (failed) {
  process.exit(1);
}
console.log(`schema parity ok (${samples.length} samples)`);
