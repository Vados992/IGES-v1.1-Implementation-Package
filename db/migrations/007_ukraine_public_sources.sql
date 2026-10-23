-- Add official Ukrainian source profiles and auditable collection attempts without rewriting history.
DO $$ BEGIN
 IF (SELECT version FROM schema_version) <> 6 THEN RAISE EXCEPTION 'Migration 007 requires v6'; END IF;
END $$;
ALTER TABLE evidence DROP CONSTRAINT evidence_provider_check;
ALTER TABLE evidence ADD CONSTRAINT evidence_provider_check CHECK(provider IN
 ('WORLD_BANK','USA_SPENDING','FDIC','ECB','BOE','US_TREASURY','CFTC','EUROSTAT','NYC_DOF','HM_LAND_REGISTRY','GLEIF','ALPACA','UA_RADA','UA_CEC'));
ALTER TABLE evidence DROP CONSTRAINT evidence_raw_bytes_check;
ALTER TABLE evidence ADD CONSTRAINT evidence_raw_bytes_check CHECK(octet_length(raw_bytes) BETWEEN 1 AND
 CASE WHEN provider='UA_CEC' THEN 32000000 WHEN provider='UA_RADA' THEN 8000000 ELSE 2000000 END);
CREATE TABLE source_collection_attempts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL REFERENCES projects(id),
 dataset text NOT NULL, body jsonb NOT NULL, body_sha256 char(64) NOT NULL CHECK(body_sha256 ~ '^[a-f0-9]{64}$'),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(id,project_id)
);
ALTER TABLE source_collection_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_collection_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_policy ON source_collection_attempts
 USING(project_id=public.runtime_project() AND project_id::text=current_setting('iges.project_id',true))
 WITH CHECK(project_id=public.runtime_project() AND project_id::text=current_setting('iges.project_id',true));
GRANT SELECT,INSERT ON source_collection_attempts TO iges_runtime;
CREATE INDEX source_collection_dataset ON source_collection_attempts(project_id,dataset,created_at);
ALTER TABLE schema_version DROP CONSTRAINT schema_version_version_check;
UPDATE schema_version SET version=7;
ALTER TABLE schema_version ADD CONSTRAINT schema_version_version_check CHECK(version=7);
