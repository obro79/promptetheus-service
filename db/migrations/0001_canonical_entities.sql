-- P2 canonical entities. Tenant keys are text to match State-0 API principals (ws_dev, proj_dev).
-- Apply on a fresh Supabase Postgres project.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS workspace (
  id text PRIMARY KEY,
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project (
  id text PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  name text NOT NULL,
  api_key_hash text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS project_workspace_idx ON project (workspace_id);
CREATE UNIQUE INDEX IF NOT EXISTS project_workspace_name_uidx
  ON project (workspace_id, name);
CREATE UNIQUE INDEX IF NOT EXISTS project_api_key_hash_uidx ON project (api_key_hash)
  WHERE api_key_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS agent (
  id text PRIMARY KEY DEFAULT gen_random_uuid()::text,
  workspace_id text NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  project_id text REFERENCES project(id) ON DELETE SET NULL,
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_workspace_idx ON agent (workspace_id);
CREATE INDEX IF NOT EXISTS agent_project_idx ON agent (project_id);
CREATE UNIQUE INDEX IF NOT EXISTS agent_workspace_project_name_uidx
  ON agent (workspace_id, project_id, name);

CREATE TABLE IF NOT EXISTS trace_session (
  id text PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  project_id text REFERENCES project(id) ON DELETE SET NULL,
  user_goal text,
  agent text,
  environment text,
  status text NOT NULL DEFAULT 'running',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  tags jsonb NOT NULL DEFAULT '[]'::jsonb,
  started_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS trace_session_workspace_idx ON trace_session (workspace_id);
CREATE INDEX IF NOT EXISTS trace_session_project_idx ON trace_session (project_id);
CREATE INDEX IF NOT EXISTS trace_session_workspace_started_idx
  ON trace_session (workspace_id, started_at, id);

CREATE TABLE IF NOT EXISTS trace_event (
  id bigserial PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  project_id text REFERENCES project(id) ON DELETE SET NULL,
  session_id text NOT NULL REFERENCES trace_session(id) ON DELETE CASCADE,
  seq integer NOT NULL,
  idempotency_key text NOT NULL,
  type text NOT NULL,
  timestamp timestamptz NOT NULL,
  span_id text,
  parent_id text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata jsonb,
  UNIQUE (session_id, seq),
  UNIQUE (session_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS trace_event_session_seq ON trace_event (session_id, seq);
CREATE INDEX IF NOT EXISTS trace_event_workspace_idx ON trace_event (workspace_id);
CREATE INDEX IF NOT EXISTS trace_event_workspace_session_idx
  ON trace_event (workspace_id, session_id, seq);

CREATE TABLE IF NOT EXISTS replay_artifact (
  artifact_id text PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  project_id text REFERENCES project(id) ON DELETE SET NULL,
  session_id text NOT NULL REFERENCES trace_session(id) ON DELETE CASCADE,
  storage_path text NOT NULL,
  content_type text,
  size_bytes bigint,
  event_time_map jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS replay_artifact_session_idx ON replay_artifact (session_id);
CREATE INDEX IF NOT EXISTS replay_artifact_workspace_idx ON replay_artifact (workspace_id);
CREATE INDEX IF NOT EXISTS replay_artifact_lookup_idx
  ON replay_artifact (workspace_id, session_id, artifact_id);

CREATE TABLE IF NOT EXISTS analysis_result (
  session_id text PRIMARY KEY REFERENCES trace_session(id) ON DELETE CASCADE,
  workspace_id text NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  project_id text REFERENCES project(id) ON DELETE SET NULL,
  labels text[] NOT NULL DEFAULT '{}',
  critical_step_seq integer,
  confidence double precision,
  root_cause text,
  detections jsonb NOT NULL DEFAULT '[]'::jsonb,
  fallback boolean NOT NULL DEFAULT false,
  embedding vector(1536),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS analysis_result_workspace_idx ON analysis_result (workspace_id);
CREATE INDEX IF NOT EXISTS analysis_result_workspace_created_idx
  ON analysis_result (workspace_id, created_at);

CREATE TABLE IF NOT EXISTS incident (
  id text PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  project_id text REFERENCES project(id) ON DELETE SET NULL,
  label text NOT NULL,
  severity text,
  status text,
  representative_session_id text,
  owner_id text,
  session_ids text[] NOT NULL DEFAULT '{}',
  critical_step_seq integer,
  confidence double precision,
  pr_url text,
  fix_agent_result jsonb,
  embedding vector(1536),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS incident_inbox ON incident (workspace_id, status, created_at);
CREATE INDEX IF NOT EXISTS incident_workspace_idx ON incident (workspace_id);
CREATE INDEX IF NOT EXISTS incident_representative_session_idx
  ON incident (representative_session_id);

CREATE TABLE IF NOT EXISTS regression_run (
  id text PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  project_id text REFERENCES project(id) ON DELETE SET NULL,
  incident_id text NOT NULL REFERENCES incident(id) ON DELETE CASCADE,
  pr_url text,
  before_pass integer,
  before_fail integer,
  after_pass integer,
  after_fail integer,
  user_confirm_count integer NOT NULL DEFAULT 0,
  raw_results_json jsonb,
  fallback boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS regression_run_incident_idx ON regression_run (incident_id);
CREATE INDEX IF NOT EXISTS regression_run_workspace_idx ON regression_run (workspace_id);
CREATE INDEX IF NOT EXISTS regression_run_incident_created_idx
  ON regression_run (incident_id, created_at);

CREATE TABLE IF NOT EXISTS connected_repo (
  id text PRIMARY KEY DEFAULT gen_random_uuid()::text,
  workspace_id text NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  project_id text NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  provider text,
  url text,
  default_branch text,
  allowed_paths_json jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS connected_repo_workspace_idx ON connected_repo (workspace_id);
CREATE INDEX IF NOT EXISTS connected_repo_project_idx ON connected_repo (project_id);
CREATE UNIQUE INDEX IF NOT EXISTS connected_repo_project_provider_url_uidx
  ON connected_repo (project_id, provider, url);

CREATE TABLE IF NOT EXISTS audit_log (
  id bigserial PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  project_id text REFERENCES project(id) ON DELETE SET NULL,
  action text NOT NULL,
  incident_id text REFERENCES incident(id) ON DELETE SET NULL,
  actor_kind text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_log_workspace_idx ON audit_log (workspace_id, created_at);
CREATE INDEX IF NOT EXISTS audit_log_incident_idx ON audit_log (incident_id);
