-- Preserve all previous evidence and audit rows; add bounded public-source provenance.
DO $$ BEGIN
 IF (SELECT version FROM schema_version) <> 5 THEN RAISE EXCEPTION 'Migration 006 requires v5'; END IF;
END $$;
ALTER TABLE evidence DROP CONSTRAINT evidence_provider_check;
ALTER TABLE evidence ADD CONSTRAINT evidence_provider_check CHECK(provider IN
 ('WORLD_BANK','USA_SPENDING','FDIC','ECB','BOE','US_TREASURY','CFTC','EUROSTAT','NYC_DOF','HM_LAND_REGISTRY','GLEIF','ALPACA'));

CREATE TABLE source_batches (
 id uuid PRIMARY KEY, project_id uuid NOT NULL, dataset text NOT NULL,
 metadata jsonb NOT NULL, metadata_sha256 char(64) NOT NULL,
 CHECK(metadata_sha256 ~ '^[a-f0-9]{64}$'),
 FOREIGN KEY(id,project_id) REFERENCES evidence(id,project_id), UNIQUE(id,project_id)
);
CREATE TABLE source_records (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL,
 evidence_id uuid NOT NULL, source_key text NOT NULL CHECK(length(source_key) BETWEEN 1 AND 500),
 body jsonb NOT NULL, source_locator text NOT NULL, record_sha256 char(64) NOT NULL,
 provenance_state text NOT NULL DEFAULT 'UNASSESSED' CHECK(provenance_state='UNASSESSED'),
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(record_sha256 ~ '^[a-f0-9]{64}$'),
 FOREIGN KEY(evidence_id,project_id) REFERENCES source_batches(id,project_id),
 UNIQUE(evidence_id,source_key), UNIQUE(id,project_id)
);
CREATE INDEX source_batches_dataset ON source_batches(project_id,dataset,id);
CREATE INDEX source_records_batch ON source_records(project_id,evidence_id,id);
CREATE INDEX source_records_key ON source_records(project_id,source_key);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['source_batches','source_records'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant_policy ON public.%I USING(project_id=public.runtime_project() AND project_id::text=current_setting(''iges.project_id'',true)) WITH CHECK(project_id=public.runtime_project() AND project_id::text=current_setting(''iges.project_id'',true))',t);
  EXECUTE format('GRANT SELECT,INSERT ON public.%I TO iges_runtime',t);
 END LOOP;
END $$;
ALTER TABLE schema_version DROP CONSTRAINT schema_version_version_check;
UPDATE schema_version SET version=6;
ALTER TABLE schema_version ADD CONSTRAINT schema_version_version_check CHECK(version=6);
