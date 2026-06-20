# Infrastructure

Hosted deploy wiring (Supabase, Railway, Vercel, GitHub App) is specified in
[`docs/infra/state-0-runbook.md`](../docs/infra/state-0-runbook.md) and implemented
in epics P2, P6, P17, and P27.

## FastAPI on Railway

The repository now includes a root [`Dockerfile`](../Dockerfile) and
[`railway.toml`](../railway.toml) for the FastAPI ingestion service.

Railway settings:

- Builder: Dockerfile
- Healthcheck: `/health`
- Start command:
  `uvicorn promptetheus.server.app:create_app --factory --host 0.0.0.0 --port ${PORT}`

Required hosted env is listed in
[`docs/infra/state-0-runbook.md`](../docs/infra/state-0-runbook.md#environment-variables).

Smoke:

```bash
curl -fsS "https://<railway-host>/health"
curl -fsS -H "Authorization: Bearer pt_console_token" "https://<railway-host>/api/sessions"
curl -fsS -X POST \
  -H "Authorization: Bearer ${PROMPTETHEUS_SERVER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"dry_run":true,"limit":25}' \
  "https://<railway-host>/internal/retention/run"
```

Artifact storage is selected with `PROMPTETHEUS_ARTIFACT_STORAGE`:

- `local` writes bytes under `PROMPTETHEUS_ARTIFACT_DIR` and returns dev signed URLs.
- `supabase` uses `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and
  `PROMPTETHEUS_SUPABASE_ARTIFACT_BUCKET`.

## Hosted Supabase Project

Current dashboard project ref: `fmminjzwowwpoujpbafv`.

Hosted auth/storage env:

- `PROMPTETHEUS_AUTH_MODE=supabase`
- `SUPABASE_URL=https://fmminjzwowwpoujpbafv.supabase.co`
- `SUPABASE_JWT_SECRET`
- `SUPABASE_SERVICE_ROLE_KEY`
- `PROMPTETHEUS_ARTIFACT_STORAGE=supabase`
- `PROMPTETHEUS_SUPABASE_ARTIFACT_BUCKET=artifacts`
- `PROMPTETHEUS_SERVER_TOKEN`

Apply `db/migrations/0004_auth_tenancy.sql` and
`db/migrations/0005_supabase_storage_artifacts.sql` to provision membership
RLS plus the private `artifacts` bucket, MIME limits, and Storage policies.
FastAPI uploads, signs, and deletes objects with the service role; browser clients use
`GET /artifacts/{id}` which now returns a `307` to a short-lived signed URL
(`?format=json` returns the JSON shape for tools).

Retention cleanup is run through:

```bash
python scripts/retention_cleanup.py --api-url "https://<railway-host>"
python scripts/retention_cleanup.py --api-url "https://<railway-host>" --execute
```

Local development uses `promptetheus dev` (FastAPI on `:4318`) with `InMemoryStore`.
