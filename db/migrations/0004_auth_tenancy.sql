-- P4 auth + tenancy hardening.
-- Supabase Auth users are mapped to Promptetheus workspaces through membership rows.

ALTER TABLE project
  ADD COLUMN IF NOT EXISTS api_key_preview text,
  ADD COLUMN IF NOT EXISTS api_key_rotated_at timestamptz,
  ADD COLUMN IF NOT EXISTS retention_days integer NOT NULL DEFAULT 30;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'project_retention_days_check'
  ) THEN
    ALTER TABLE project
      ADD CONSTRAINT project_retention_days_check
      CHECK (retention_days >= 0 AND retention_days <= 3650)
      NOT VALID;
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS workspace_member (
  workspace_id text NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('owner', 'member')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS workspace_member_user_idx
  ON workspace_member (user_id, workspace_id);

CREATE SCHEMA IF NOT EXISTS promptetheus_private;
REVOKE ALL ON SCHEMA promptetheus_private FROM PUBLIC;
GRANT USAGE ON SCHEMA promptetheus_private TO authenticated;

CREATE OR REPLACE FUNCTION promptetheus_private.auth_user_id() RETURNS uuid
  LANGUAGE sql
  STABLE
AS $$
  SELECT auth.uid();
$$;

CREATE OR REPLACE FUNCTION promptetheus_private.workspace_role(target_workspace_id text) RETURNS text
  LANGUAGE sql
  STABLE
  SECURITY DEFINER
  SET search_path = public, promptetheus_private
AS $$
  SELECT wm.role
  FROM workspace_member wm
  WHERE wm.workspace_id = target_workspace_id
    AND wm.user_id = promptetheus_private.auth_user_id()
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION promptetheus_private.is_workspace_member(target_workspace_id text) RETURNS boolean
  LANGUAGE sql
  STABLE
  SECURITY DEFINER
  SET search_path = public, promptetheus_private
AS $$
  SELECT promptetheus_private.workspace_role(target_workspace_id) IN ('owner', 'member');
$$;

CREATE OR REPLACE FUNCTION promptetheus_private.is_workspace_owner(target_workspace_id text) RETURNS boolean
  LANGUAGE sql
  STABLE
  SECURITY DEFINER
  SET search_path = public, promptetheus_private
AS $$
  SELECT promptetheus_private.workspace_role(target_workspace_id) = 'owner';
$$;

GRANT EXECUTE ON FUNCTION promptetheus_private.auth_user_id() TO authenticated;
GRANT EXECUTE ON FUNCTION promptetheus_private.workspace_role(text) TO authenticated;
GRANT EXECUTE ON FUNCTION promptetheus_private.is_workspace_member(text) TO authenticated;
GRANT EXECUTE ON FUNCTION promptetheus_private.is_workspace_owner(text) TO authenticated;

ALTER TABLE workspace_member ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS workspace_tenant_select ON workspace;
DROP POLICY IF EXISTS workspace_tenant_write ON workspace;
DROP POLICY IF EXISTS project_tenant_select ON project;
DROP POLICY IF EXISTS project_tenant_write ON project;
DROP POLICY IF EXISTS agent_tenant_all ON agent;
DROP POLICY IF EXISTS trace_session_tenant_all ON trace_session;
DROP POLICY IF EXISTS trace_event_tenant_all ON trace_event;
DROP POLICY IF EXISTS replay_artifact_tenant_all ON replay_artifact;
DROP POLICY IF EXISTS analysis_result_tenant_all ON analysis_result;
DROP POLICY IF EXISTS incident_tenant_all ON incident;
DROP POLICY IF EXISTS regression_run_tenant_all ON regression_run;
DROP POLICY IF EXISTS connected_repo_tenant_all ON connected_repo;
DROP POLICY IF EXISTS audit_log_tenant_all ON audit_log;
DROP POLICY IF EXISTS workspace_member_select ON workspace_member;
DROP POLICY IF EXISTS workspace_member_owner_write ON workspace_member;

CREATE POLICY workspace_member_select ON workspace_member
  FOR SELECT
  USING (
    user_id = promptetheus_private.auth_user_id()
    OR promptetheus_private.is_workspace_owner(workspace_id)
  );

CREATE POLICY workspace_member_owner_write ON workspace_member
  FOR ALL
  USING (promptetheus_private.is_workspace_owner(workspace_id))
  WITH CHECK (promptetheus_private.is_workspace_owner(workspace_id));

CREATE POLICY workspace_tenant_select ON workspace
  FOR SELECT USING (promptetheus_private.is_workspace_member(id));

CREATE POLICY project_tenant_select ON project
  FOR SELECT USING (promptetheus_private.is_workspace_member(workspace_id));

CREATE POLICY agent_tenant_select ON agent
  FOR SELECT USING (promptetheus_private.is_workspace_member(workspace_id));

CREATE POLICY trace_session_tenant_select ON trace_session
  FOR SELECT USING (promptetheus_private.is_workspace_member(workspace_id));

CREATE POLICY trace_event_tenant_select ON trace_event
  FOR SELECT USING (promptetheus_private.is_workspace_member(workspace_id));

CREATE POLICY replay_artifact_tenant_select ON replay_artifact
  FOR SELECT USING (promptetheus_private.is_workspace_member(workspace_id));

CREATE POLICY analysis_result_tenant_select ON analysis_result
  FOR SELECT USING (promptetheus_private.is_workspace_member(workspace_id));

CREATE POLICY incident_tenant_select ON incident
  FOR SELECT USING (promptetheus_private.is_workspace_member(workspace_id));

CREATE POLICY regression_run_tenant_select ON regression_run
  FOR SELECT USING (promptetheus_private.is_workspace_member(workspace_id));

CREATE POLICY connected_repo_tenant_select ON connected_repo
  FOR SELECT USING (promptetheus_private.is_workspace_member(workspace_id));

CREATE POLICY audit_log_tenant_select ON audit_log
  FOR SELECT USING (promptetheus_private.is_workspace_member(workspace_id));

UPDATE project
SET
  api_key_preview = COALESCE(api_key_preview, 'pt_dev_..._key'),
  api_key_rotated_at = COALESCE(api_key_rotated_at, now()),
  retention_days = COALESCE(retention_days, 30)
WHERE id = 'proj_dev';
