\set ON_ERROR_STOP on
CREATE ROLE iges_runtime LOGIN PASSWORD :'runtime_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE projects (
  id uuid PRIMARY KEY, name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO projects (id,name) VALUES (:'project_id'::uuid, 'IGES public-data pilot');

CREATE TABLE evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  provider text NOT NULL CHECK (provider IN ('WORLD_BANK')),
  source_url text NOT NULL,
  retrieved_at timestamptz NOT NULL DEFAULT now(),
  content_sha256 char(64) NOT NULL CHECK(content_sha256 ~ '^[a-f0-9]{64}$'),
  raw_bytes bytea NOT NULL,
  provenance_state text NOT NULL DEFAULT 'UNASSESSED'
    CHECK (provenance_state IN ('UNASSESSED','DISPUTED','CORROBORATED','REJECTED')),
  media_type text NOT NULL DEFAULT 'application/json',
  UNIQUE (project_id, provider, content_sha256),
  UNIQUE (id, project_id)
);
CREATE TABLE observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  evidence_id uuid NOT NULL,
  country_code varchar(3) NOT NULL CHECK (country_code ~ '^[A-Z]{3}$'),
  indicator_code text NOT NULL,
  period int NOT NULL CHECK (period BETWEEN 1900 AND 2100),
  numeric_value numeric(38,10),
  observation_status text,
  source_locator text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, evidence_id, country_code, indicator_code, period),
  FOREIGN KEY (evidence_id, project_id) REFERENCES evidence (id, project_id)
);
CREATE INDEX observations_recent ON observations(project_id,country_code,indicator_code,period DESC);

CREATE TABLE financial_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  evidence_id uuid NOT NULL,
  idempotency_key varchar(128) NOT NULL,
  stage text NOT NULL CHECK (stage IN (
    'COMMITMENT','APPROPRIATION','OBLIGATION','CONTRACT',
    'DISBURSEMENT','RECEIPT','EXPENDITURE','REFUND','REVERSAL')),
  original_amount numeric(32,8) NOT NULL CHECK(original_amount >= 0),
  currency char(3) NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
  external_reference text NOT NULL,
  payer_name text, payee_name text,
  related_event_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id,idempotency_key),
  UNIQUE(id,project_id),
  FOREIGN KEY(evidence_id,project_id) REFERENCES evidence(id,project_id),
  FOREIGN KEY(related_event_id,project_id) REFERENCES financial_events(id,project_id)
);
CREATE TABLE claims (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  evidence_id uuid NOT NULL,
  statement text NOT NULL CHECK(length(statement) BETWEEN 10 AND 5000),
  submitted_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  state text NOT NULL DEFAULT 'UNASSESSED'
    CHECK(state='UNASSESSED'),
  UNIQUE(id,project_id),
  FOREIGN KEY(evidence_id,project_id) REFERENCES evidence(id,project_id)
);
CREATE TABLE reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  claim_id uuid NOT NULL,
  reviewer_sub text NOT NULL,
  verdict text NOT NULL CHECK(verdict IN ('SUPPORT','CONTRADICT','INSUFFICIENT')),
  rationale text NOT NULL CHECK(length(rationale) BETWEEN 20 AND 5000),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id,claim_id,reviewer_sub),
  FOREIGN KEY(claim_id,project_id) REFERENCES claims(id,project_id)
);
CREATE TABLE audit_events (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id),
  actor_sub text NOT NULL,
  action text NOT NULL,
  subject_id text NOT NULL,
  occurred_at timestamptz NOT NULL,
  previous_hash char(64) NOT NULL,
  entry_hash char(64) NOT NULL,
  UNIQUE(project_id,entry_hash)
);
CREATE INDEX audit_chain_order ON audit_events(project_id,occurred_at,id);

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['projects','evidence','observations','financial_events','claims','reviews','audit_events']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    IF t = 'projects' THEN
      EXECUTE format('CREATE POLICY tenant_policy ON %I USING (id::text = current_setting(''iges.project_id'',true)) WITH CHECK (id::text = current_setting(''iges.project_id'',true))',t);
    ELSE
      EXECUTE format('CREATE POLICY tenant_policy ON %I USING (project_id::text = current_setting(''iges.project_id'',true)) WITH CHECK (project_id::text = current_setting(''iges.project_id'',true))',t);
    END IF;
  END LOOP;
END $$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO iges_runtime;
GRANT SELECT ON projects TO iges_runtime;
GRANT SELECT, INSERT ON evidence, observations, financial_events, claims, reviews, audit_events TO iges_runtime;
-- Neither UPDATE nor DELETE on the evidence trail are granted to the runtime.
-- Superusers can still modify data: independent backup and external audit anchoring remain production gates.
