-- Append-only, single-project evidence workspace. No legacy rows are removed.
DO $$ BEGIN
  IF (SELECT version FROM schema_version) <> 3 THEN
    RAISE EXCEPTION 'Migration 004 requires schema version 3';
  END IF;
END $$;
CREATE TABLE cases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL REFERENCES projects(id),
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  body jsonb NOT NULL CHECK(length(body->>'title') BETWEEN 3 AND 300),
  UNIQUE(id,project_id)
);
CREATE TABLE case_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL,
  case_id uuid NOT NULL, subject text NOT NULL, role text NOT NULL
    CHECK(role IN ('analyst','reader','reviewer','counsel','editor','panel','respondent')),
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(case_id,project_id) REFERENCES cases(id,project_id),
  UNIQUE(project_id,case_id,subject,role)
);
CREATE TABLE case_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  revision integer NOT NULL CHECK(revision>0), action text NOT NULL,
  payload jsonb NOT NULL, payload_sha256 char(64) NOT NULL,
  canonical_payload text NOT NULL, created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(payload=canonical_payload::jsonb),
  CHECK(payload_sha256=encode(digest(convert_to(canonical_payload,'UTF8'),'sha256'),'hex')),
  FOREIGN KEY(case_id,project_id) REFERENCES cases(id,project_id), UNIQUE(case_id,revision)
);
ALTER TABLE claims ALTER COLUMN evidence_id DROP NOT NULL;
ALTER TABLE claims ADD COLUMN case_id uuid;
ALTER TABLE claims ADD COLUMN body jsonb;
ALTER TABLE claims ADD COLUMN created_by text;
ALTER TABLE claims ADD FOREIGN KEY(case_id,project_id) REFERENCES cases(id,project_id);
ALTER TABLE claims ADD UNIQUE(id,case_id,project_id);
ALTER TABLE claims ADD CHECK((case_id IS NULL AND evidence_id IS NOT NULL) OR
  (case_id IS NOT NULL AND body IS NOT NULL AND length(body->>'exact_text')>=10
   AND body->>'period_from' IS NOT NULL AND body->>'period_to' IS NOT NULL
   AND (body->>'period_to')::date >= (body->>'period_from')::date));
CREATE TABLE hypotheses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  claim_id uuid NOT NULL, body jsonb NOT NULL,
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(length(body->>'falsifiers')>=10 AND length(body->>'expected_observations')>=10),
  FOREIGN KEY(claim_id,case_id,project_id) REFERENCES claims(id,case_id,project_id)
);
CREATE TABLE sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  body jsonb NOT NULL CHECK(body->>'primacy' IN ('primary','secondary','derivative')),
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(case_id,project_id) REFERENCES cases(id,project_id), UNIQUE(id,case_id,project_id)
);
CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  source_id uuid NOT NULL, sha256 char(64) NOT NULL,
  raw_bytes bytea NOT NULL CHECK(octet_length(raw_bytes) BETWEEN 1 AND 8388608),
  mime text NOT NULL, size_bytes integer NOT NULL, doc_version integer NOT NULL CHECK(doc_version>0),
  scan_status text NOT NULL DEFAULT 'PENDING' CHECK(scan_status='PENDING'),
  created_by text NOT NULL, retrieved_at timestamptz NOT NULL DEFAULT now(),
  CHECK(size_bytes=octet_length(raw_bytes)), CHECK(sha256=encode(digest(raw_bytes,'sha256'),'hex')),
  FOREIGN KEY(source_id,case_id,project_id) REFERENCES sources(id,case_id,project_id),
  UNIQUE(id,case_id,project_id), UNIQUE(source_id,sha256), UNIQUE(source_id,doc_version)
);
CREATE TABLE document_pages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  document_id uuid NOT NULL, page integer NOT NULL CHECK(page>0), text_content text NOT NULL,
  confidence numeric CHECK(confidence BETWEEN 0 AND 1), method text NOT NULL,
  content_sha256 char(64) NOT NULL,
  search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple',text_content)) STORED,
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(content_sha256=encode(digest(convert_to(text_content,'UTF8'),'sha256'),'hex')),
  FOREIGN KEY(document_id,case_id,project_id) REFERENCES documents(id,case_id,project_id),
  UNIQUE(document_id,page), UNIQUE(id,case_id,project_id)
);
CREATE INDEX document_pages_fts ON document_pages USING gin(search_vector);
CREATE TABLE document_processing (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  document_id uuid NOT NULL, status text NOT NULL CHECK(status IN ('READY','FAILED','QUARANTINED','RETRY_REQUESTED')),
  receipt jsonb NOT NULL, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(document_id,case_id,project_id) REFERENCES documents(id,case_id,project_id)
);
CREATE TABLE evidence_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  claim_id uuid NOT NULL, document_id uuid NOT NULL, page integer NOT NULL,
  quote text NOT NULL CHECK(length(quote)>0), direction text NOT NULL
    CHECK(direction IN ('supports','weakens','contextual')),
  body jsonb NOT NULL, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(claim_id,case_id,project_id) REFERENCES claims(id,case_id,project_id),
  FOREIGN KEY(document_id,case_id,project_id) REFERENCES documents(id,case_id,project_id),
  FOREIGN KEY(document_id,page) REFERENCES document_pages(document_id,page),
  UNIQUE(id,case_id,project_id)
);
CREATE FUNCTION validate_quote() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM public.document_pages WHERE document_id=NEW.document_id
    AND page=NEW.page AND case_id=NEW.case_id AND project_id=NEW.project_id
    AND strpos(text_content,NEW.quote)>0) THEN
    RAISE EXCEPTION 'QUOTE_NOT_ON_PAGE' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER evidence_quote BEFORE INSERT ON evidence_items FOR EACH ROW EXECUTE FUNCTION validate_quote();
CREATE TABLE entities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  body jsonb NOT NULL CHECK(length(body->>'canonical_name')>0),
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(case_id,project_id) REFERENCES cases(id,project_id), UNIQUE(id,case_id,project_id)
);
CREATE TABLE relationships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  subject_id uuid NOT NULL, object_id uuid NOT NULL, evidence_id uuid NOT NULL,
  body jsonb NOT NULL, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(subject_id,case_id,project_id) REFERENCES entities(id,case_id,project_id),
  FOREIGN KEY(object_id,case_id,project_id) REFERENCES entities(id,case_id,project_id),
  FOREIGN KEY(evidence_id,case_id,project_id) REFERENCES evidence_items(id,case_id,project_id)
);
CREATE TABLE review_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  claim_id uuid NOT NULL, reviewer_sub text NOT NULL, created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(claim_id,case_id,project_id) REFERENCES claims(id,case_id,project_id),
  UNIQUE(claim_id,reviewer_sub)
);
CREATE TABLE assessments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  claim_id uuid NOT NULL, revision integer NOT NULL CHECK(revision>0),
  status text NOT NULL CHECK(status IN ('SUPPORTED','CONTRADICTED','MIXED','INSUFFICIENT_EVIDENCE','WITHDRAWN_CORRECTED')),
  body jsonb NOT NULL, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(claim_id,case_id,project_id) REFERENCES claims(id,case_id,project_id),
  UNIQUE(claim_id,revision,created_by)
);
CREATE TABLE publication_gates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  revision integer NOT NULL, gate text NOT NULL CHECK(gate IN ('legal_privacy','panel','reply')),
  body jsonb NOT NULL, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(case_id,project_id) REFERENCES cases(id,project_id)
);
CREATE TABLE responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  body jsonb NOT NULL, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(case_id,project_id) REFERENCES cases(id,project_id)
);
CREATE TABLE publications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  version integer NOT NULL CHECK(version>0), revision integer NOT NULL,
  kind text NOT NULL CHECK(kind IN ('PUBLISHED','CORRECTED','WITHDRAWN')),
  supersedes_id uuid REFERENCES publications(id), canonical_manifest text NOT NULL,
  manifest_hash char(64) NOT NULL,
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(manifest_hash=encode(digest(convert_to(canonical_manifest,'UTF8'),'sha256'),'hex')),
  FOREIGN KEY(case_id,project_id) REFERENCES cases(id,project_id), UNIQUE(case_id,version)
);
CREATE TABLE write_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL REFERENCES projects(id),
  actor text NOT NULL, request_path text NOT NULL, key text NOT NULL, request_hash char(64) NOT NULL,
  response jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id,actor,request_path,key)
);
CREATE TABLE integrity_incidents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL REFERENCES projects(id),
  document_id uuid NOT NULL, observed_hash char(64) NOT NULL,
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE record_seals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL REFERENCES projects(id),
  table_name text NOT NULL, object_id uuid NOT NULL, canonical_record text NOT NULL,
  record_sha256 char(64) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(record_sha256=encode(digest(convert_to(canonical_record,'UTF8'),'sha256'),'hex')),
  UNIQUE(table_name,object_id)
);
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['cases','case_members','case_events','hypotheses','sources','documents',
    'document_pages','document_processing','evidence_items','entities','relationships','review_assignments','assessments',
    'publication_gates','responses','publications','write_receipts','integrity_incidents','record_seals'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY tenant_policy ON %I USING(project_id=public.runtime_project() AND project_id::text=current_setting(''iges.project_id'',true)) WITH CHECK(project_id=public.runtime_project() AND project_id::text=current_setting(''iges.project_id'',true))',t);
    EXECUTE format('GRANT SELECT,INSERT ON %I TO iges_runtime',t);
    EXECUTE format('CREATE INDEX ON %I(project_id)',t);
  END LOOP;
END $$;
CREATE INDEX claims_case ON claims(case_id);
CREATE INDEX hypotheses_claim ON hypotheses(claim_id);
CREATE INDEX sources_case ON sources(case_id);
CREATE INDEX documents_case ON documents(case_id);
CREATE INDEX evidence_claim ON evidence_items(claim_id);
CREATE INDEX relationships_case ON relationships(case_id);
CREATE INDEX assessments_revision ON assessments(case_id,revision);
CREATE INDEX gates_revision ON publication_gates(case_id,revision);
ALTER TABLE schema_version DROP CONSTRAINT schema_version_version_check;
UPDATE schema_version SET version=4;
ALTER TABLE schema_version ADD CONSTRAINT schema_version_version_check CHECK(version=4);
