-- P4 hosted Supabase Storage hardening for replay artifacts.
-- The FastAPI service role writes/deletes objects; console users receive signed URLs.

INSERT INTO storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
VALUES (
  'artifacts',
  'artifacts',
  false,
  52428800,
  ARRAY['video/webm', 'image/png', 'image/jpeg']
)
ON CONFLICT (id) DO UPDATE SET
  public = false,
  file_size_limit = EXCLUDED.file_size_limit,
  allowed_mime_types = EXCLUDED.allowed_mime_types;

DROP POLICY IF EXISTS artifacts_member_select ON storage.objects;
DROP POLICY IF EXISTS artifacts_owner_write ON storage.objects;

CREATE POLICY artifacts_member_select ON storage.objects
  FOR SELECT
  USING (
    bucket_id = 'artifacts'
    AND (storage.foldername(name))[1] = 'artifacts'
    AND promptetheus_private.is_workspace_member((storage.foldername(name))[2])
  );

CREATE POLICY artifacts_owner_write ON storage.objects
  FOR ALL
  USING (
    bucket_id = 'artifacts'
    AND (storage.foldername(name))[1] = 'artifacts'
    AND promptetheus_private.is_workspace_owner((storage.foldername(name))[2])
  )
  WITH CHECK (
    bucket_id = 'artifacts'
    AND (storage.foldername(name))[1] = 'artifacts'
    AND promptetheus_private.is_workspace_owner((storage.foldername(name))[2])
  );
