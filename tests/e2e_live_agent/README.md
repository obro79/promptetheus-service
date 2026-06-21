# Live Agent Supabase MCP E2E

This suite is opt-in because it writes isolated rows to a hosted Supabase
database.

## Required Environment

```bash
export PROMPTETHEUS_LIVE_E2E=1
export PROMPTETHEUS_LIVE_DATABASE_URL='postgresql://postgres:<password>@db.fmminjzwowwpoujpbafv.supabase.co:5432/postgres'
```

The test uses this local SDK checkout by default:

```text
/Users/owenfisher/Desktop/projects/promptetheus-sdk/packages/promptetheus
```

Set `PROMPTETHEUS_SDK_PATH` only to override that path.

Do not `uv add promptetheus` into this service venv for the live test. The SDK
and service both use the `promptetheus` package/import name, so installing both
into one environment makes imports ambiguous. The live test starts the service
with the service package on `PYTHONPATH`, then starts the SDK agent subprocess
with the SDK package first on `PYTHONPATH`.

The active Supabase project discovered through the connector is:

- name: `promptetheus`
- ref: `fmminjzwowwpoujpbafv`
- host: `db.fmminjzwowwpoujpbafv.supabase.co`

Use a non-production database URL. The test creates a unique workspace/project
and deletes the workspace at the end, relying on cascade cleanup. To keep rows
for debugging:

```bash
export PROMPTETHEUS_E2E_KEEP_ROWS=1
```

## Run

```bash
PROMPTETHEUS_LIVE_E2E=1 \
packages/promptetheus/.venv/bin/python -m pytest tests/e2e_live_agent -s
```

Without `PROMPTETHEUS_LIVE_E2E=1`, the suite skips cleanly.
