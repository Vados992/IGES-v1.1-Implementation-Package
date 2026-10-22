-- Add award provenance to schema v2 without rewriting source bytes or audit history.
DO $$ BEGIN
  IF (SELECT version FROM schema_version) <> 2 THEN
    RAISE EXCEPTION 'Migration 003 requires schema version 2';
  END IF;
END $$;

ALTER TABLE evidence DROP CONSTRAINT evidence_provider_check;
ALTER TABLE evidence ADD CONSTRAINT evidence_provider_check CHECK(provider IN ('WORLD_BANK','USA_SPENDING'));
ALTER TABLE evidence ADD COLUMN request_sha256 char(64);
ALTER TABLE evidence ADD COLUMN source_request jsonb NOT NULL DEFAULT '{}'::jsonb;
UPDATE evidence SET request_sha256=encode(digest(convert_to('GET ' || source_url,'UTF8'),'sha256'),'hex');
ALTER TABLE evidence ALTER COLUMN request_sha256 SET NOT NULL;
ALTER TABLE evidence ADD CHECK(request_sha256 ~ '^[a-f0-9]{64}$');
ALTER TABLE evidence DROP CONSTRAINT evidence_project_id_provider_content_sha256_key;
ALTER TABLE evidence ADD UNIQUE(project_id,provider,content_sha256,request_sha256);

CREATE TABLE public_awards (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  evidence_id uuid NOT NULL,
  source_award_key text NOT NULL,
  external_award_id text, recipient_name text, awarding_agency text, funding_agency text,
  award_amount numeric CHECK(award_amount IS NULL OR
    award_amount NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)),
  currency char(3) NOT NULL DEFAULT 'USD' CHECK(currency='USD'),
  source_locator text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id,evidence_id,source_award_key),
  FOREIGN KEY(evidence_id,project_id) REFERENCES evidence(id,project_id)
);
CREATE INDEX awards_by_key ON public_awards(project_id,source_award_key);
ALTER TABLE public_awards ENABLE ROW LEVEL SECURITY;
ALTER TABLE public_awards FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_policy ON public_awards
  USING(project_id=public.runtime_project() AND project_id::text=current_setting('iges.project_id',true))
  WITH CHECK(project_id=public.runtime_project() AND project_id::text=current_setting('iges.project_id',true));
GRANT SELECT, INSERT ON public_awards TO iges_runtime;

ALTER TABLE schema_version DROP CONSTRAINT schema_version_version_check;
UPDATE schema_version SET version=3;
ALTER TABLE schema_version ADD CONSTRAINT schema_version_version_check CHECK(version=3);
