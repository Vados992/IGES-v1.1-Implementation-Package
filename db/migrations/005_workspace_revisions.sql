-- Preserve v4 originals and audit history while adding reversible identity resolution and case revisions.
DO $$ BEGIN
  IF (SELECT version FROM schema_version) <> 4 THEN RAISE EXCEPTION 'Migration 005 requires schema version 4'; END IF;
END $$;
CREATE TABLE entity_resolutions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
  subject_id uuid NOT NULL, object_id uuid NOT NULL, evidence_id uuid NOT NULL, body jsonb NOT NULL,
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(subject_id,case_id,project_id) REFERENCES entities(id,case_id,project_id),
  FOREIGN KEY(object_id,case_id,project_id) REFERENCES entities(id,case_id,project_id),
  FOREIGN KEY(evidence_id,case_id,project_id) REFERENCES evidence_items(id,case_id,project_id)
);

CREATE TABLE case_revisions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
 body jsonb NOT NULL, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(case_id,project_id) REFERENCES cases(id,project_id)
);
ALTER TABLE document_pages ADD COLUMN locator jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE case_members DROP CONSTRAINT case_members_project_id_case_id_subject_role_key;
CREATE INDEX ON case_members(case_id,subject,role);
CREATE TABLE case_member_revocations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL, case_id uuid NOT NULL,
 member_id uuid NOT NULL REFERENCES case_members(id), body jsonb NOT NULL,
 created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(case_id,project_id) REFERENCES cases(id,project_id), UNIQUE(member_id)
);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['entity_resolutions','case_revisions','case_member_revocations'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant_policy ON %I USING(project_id=public.runtime_project() AND project_id::text=current_setting(''iges.project_id'',true)) WITH CHECK(project_id=public.runtime_project() AND project_id::text=current_setting(''iges.project_id'',true))',t);
  EXECUTE format('GRANT SELECT,INSERT ON %I TO iges_runtime',t);
  EXECUTE format('CREATE INDEX ON %I(case_id)',t);
 END LOOP;
END $$;
ALTER TABLE schema_version DROP CONSTRAINT schema_version_version_check;
UPDATE schema_version SET version=5;
ALTER TABLE schema_version ADD CONSTRAINT schema_version_version_check CHECK(version=5);
CREATE FUNCTION validate_assessment() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE author text;
BEGIN
 SELECT submitted_by INTO author FROM public.claims WHERE id=NEW.claim_id AND case_id=NEW.case_id AND project_id=NEW.project_id;
 IF NOT FOUND OR NEW.revision<>(SELECT coalesce(max(revision),0) FROM public.case_events WHERE case_id=NEW.case_id) THEN
  RAISE EXCEPTION 'CLAIM_OR_REVISION_INVALID' USING ERRCODE='23514';
 END IF;
 IF EXISTS(SELECT 1 FROM public.assessments WHERE claim_id=NEW.claim_id AND status='WITHDRAWN_CORRECTED') THEN
  RAISE EXCEPTION 'WITHDRAWAL_IS_IRREVERSIBLE' USING ERRCODE='23514';
 END IF;
 IF NEW.status='WITHDRAWN_CORRECTED' AND author=NEW.created_by AND NEW.body->>'author_withdrawal'='true' THEN RETURN NEW; END IF;
 IF author=NEW.created_by OR EXISTS(SELECT 1 FROM public.evidence_items e JOIN public.documents d ON d.id=e.document_id
    WHERE e.claim_id=NEW.claim_id AND (e.created_by=NEW.created_by OR d.created_by=NEW.created_by))
    OR EXISTS(SELECT 1 FROM public.hypotheses WHERE claim_id=NEW.claim_id AND created_by=NEW.created_by) THEN
  RAISE EXCEPTION 'SELF_REVIEW_FORBIDDEN' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM public.review_assignments WHERE claim_id=NEW.claim_id AND reviewer_sub=NEW.created_by)
    OR NOT EXISTS(SELECT 1 FROM public.case_members WHERE case_id=NEW.case_id AND subject=NEW.created_by AND role='reviewer')
    OR NEW.body->>'conflict_declaration' IS DISTINCT FROM 'NO_CONFLICT'
    OR NEW.body->>'quotations_checked' IS DISTINCT FROM 'true'
    OR NEW.body->>'provenance_checked' IS DISTINCT FROM 'true'
    OR NOT EXISTS(SELECT 1 FROM public.hypotheses WHERE claim_id=NEW.claim_id)
    OR NOT EXISTS(SELECT 1 FROM public.evidence_items WHERE claim_id=NEW.claim_id) THEN
  RAISE EXCEPTION 'REVIEW_PREREQUISITES_REQUIRED' USING ERRCODE='23514';
 END IF;
 IF EXISTS(SELECT 1 FROM public.evidence_items e JOIN public.document_pages p ON p.document_id=e.document_id AND p.page=e.page
   WHERE e.claim_id=NEW.claim_id AND p.confidence<0.85) AND NEW.body->>'low_confidence_pages_visually_checked' IS DISTINCT FROM 'true' THEN
  RAISE EXCEPTION 'MANUAL_OCR_COMPARISON_REQUIRED' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER assessment_integrity BEFORE INSERT ON assessments FOR EACH ROW EXECUTE FUNCTION validate_assessment();
