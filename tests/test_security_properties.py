from pathlib import Path

from app.worldbank import ALLOWED_INDICATORS
from app.ledger import stage_totals


def test_source_provider_is_explicit_allowlist():
    assert "SP.POP.TOTL" in ALLOWED_INDICATORS
    assert "file:///etc/passwd" not in ALLOWED_INDICATORS


def test_finance_stages_do_not_infer_spending_from_promise():
    out = stage_totals([{"stage": "COMMITMENT", "amount": "9999999999"}])
    assert out["DISBURSEMENT"] == "0"


def test_schema_contains_forced_rls_and_separate_role():
    schema = (Path(__file__).resolve().parents[1] / "db/init/01_schema.template").read_text()
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "NOSUPERUSER" in schema
    assert "GRANT SELECT, INSERT" in schema
    assert "GRANT UPDATE" not in schema


def test_public_read_path_has_no_raw_evidence_body():
    main = (Path(__file__).resolve().parents[1] / "app/main.py").read_text()
    assert "GET /v1/public/claims" not in main
    assert "raw_bytes" not in main
