-- P2 RLS: cross-workspace access denied by default.
-- Console JWTs must carry workspace_id claim; service-role server writes bypass RLS.

CREATE OR REPLACE FUNCTION public.auth_workspace_id() RETURNS text
  LANGUAGE sql
  STABLE
AS $$
  SELECT NULLIF(auth.jwt() ->> 'workspace_id', '');
$$;

ALTER TABLE workspace ENABLE ROW LEVEL SECURITY;
ALTER TABLE project ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent ENABLE ROW LEVEL SECURITY;
ALTER TABLE trace_session ENABLE ROW LEVEL SECURITY;
ALTER TABLE trace_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE replay_artifact ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_result ENABLE ROW LEVEL SECURITY;
ALTER TABLE incident ENABLE ROW LEVEL SECURITY;
ALTER TABLE regression_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE connected_repo ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

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

-- workspace: members see only their workspace row (P3 will add membership table).
CREATE POLICY workspace_tenant_select ON workspace
  FOR SELECT USING (id = public.auth_workspace_id());

CREATE POLICY workspace_tenant_write ON workspace
  FOR ALL USING (id = public.auth_workspace_id())
  WITH CHECK (id = public.auth_workspace_id());

CREATE POLICY project_tenant_select ON project
  FOR SELECT USING (workspace_id = public.auth_workspace_id());

CREATE POLICY project_tenant_write ON project
  FOR ALL USING (workspace_id = public.auth_workspace_id())
  WITH CHECK (workspace_id = public.auth_workspace_id());

CREATE POLICY agent_tenant_all ON agent
  FOR ALL USING (workspace_id = public.auth_workspace_id())
  WITH CHECK (workspace_id = public.auth_workspace_id());

CREATE POLICY trace_session_tenant_all ON trace_session
  FOR ALL USING (workspace_id = public.auth_workspace_id())
  WITH CHECK (workspace_id = public.auth_workspace_id());

CREATE POLICY trace_event_tenant_all ON trace_event
  FOR ALL USING (workspace_id = public.auth_workspace_id())
  WITH CHECK (workspace_id = public.auth_workspace_id());

CREATE POLICY replay_artifact_tenant_all ON replay_artifact
  FOR ALL USING (workspace_id = public.auth_workspace_id())
  WITH CHECK (workspace_id = public.auth_workspace_id());

CREATE POLICY analysis_result_tenant_all ON analysis_result
  FOR ALL USING (workspace_id = public.auth_workspace_id())
  WITH CHECK (workspace_id = public.auth_workspace_id());

CREATE POLICY incident_tenant_all ON incident
  FOR ALL USING (workspace_id = public.auth_workspace_id())
  WITH CHECK (workspace_id = public.auth_workspace_id());

CREATE POLICY regression_run_tenant_all ON regression_run
  FOR ALL USING (workspace_id = public.auth_workspace_id())
  WITH CHECK (workspace_id = public.auth_workspace_id());

CREATE POLICY connected_repo_tenant_all ON connected_repo
  FOR ALL USING (workspace_id = public.auth_workspace_id())
  WITH CHECK (workspace_id = public.auth_workspace_id());

CREATE POLICY audit_log_tenant_all ON audit_log
  FOR ALL USING (workspace_id = public.auth_workspace_id())
  WITH CHECK (workspace_id = public.auth_workspace_id());
