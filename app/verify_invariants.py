"""Operator-run database invariants check; suitable for CI after service startup."""
from sqlalchemy import text

from app.database import tenant_session


def main():
    with tenant_session() as session:
        role = session.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).one()
        assert role[0] is False and role[1] is False, "app role must not bypass RLS"
        protections = session.execute(text("""
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class WHERE relname IN (
              'projects','evidence','observations','financial_events','claims',
              'reviews','audit_events','evidence_attestations')
            ORDER BY relname
        """)).all()
        assert len(protections) == 8
        assert all(row[1] and row[2] for row in protections)
        grants = session.execute(text("""
            SELECT has_table_privilege(current_user,'evidence','UPDATE'),
                   has_table_privilege(current_user,'audit_events','DELETE'),
                   has_table_privilege(current_user,'reviews','UPDATE')
        """)).one()
        assert grants == (False, False, False)
        project_name = session.execute(
            text("SELECT name FROM projects WHERE id=current_setting('iges.project_id')::uuid")
        ).scalar_one()
        assert project_name == "IGES public-data pilot"
    print("PASS: non-superuser app role, all forced RLS tables, no mutation grants")


if __name__ == "__main__":
    main()
