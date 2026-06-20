-- Deterministic local/dev seed. Hosted deploys can override with real projects.

INSERT INTO workspace (id, name) VALUES ('ws_dev', 'Dev Workspace')
ON CONFLICT (id) DO NOTHING;

INSERT INTO project (id, workspace_id, name, api_key_hash)
VALUES (
  'proj_dev',
  'ws_dev',
  'Dev Project',
  encode(digest('pt_dev_key', 'sha256'), 'hex')
)
ON CONFLICT (id) DO NOTHING;
