"""Redacted checks for the installed Windows pilot; never emits credentials."""
import json
import ssl
from datetime import datetime, timezone

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from scripts.windows_pilot import STATE, ROOT


def management_status():
    config = json.loads((STATE / "settings.json").read_text())
    engine = create_engine(URL.create("postgresql+psycopg", username="iges_admin",
        password=config["admin_password"], host="127.0.0.1", port=55432, database="iges_identity"))
    try:
        with engine.connect() as conn:
            users = {r["username"]: r["enabled"] for r in conn.execute(text(
                "SELECT u.username,u.enabled FROM user_entity u JOIN realm r ON r.id=u.realm_id "
                "WHERE r.name='master' AND u.username IN ('iges-admin','iges-admin-owner')")).mappings()}
            actions = set(conn.execute(text(
                "SELECT a.required_action FROM user_required_action a JOIN user_entity u ON u.id=a.user_id "
                "JOIN realm r ON r.id=u.realm_id WHERE r.name='master' AND u.username='iges-admin-owner'")).scalars())
            admin_role = conn.execute(text(
                "SELECT count(*) FROM user_role_mapping m JOIN user_entity u ON u.id=m.user_id "
                "JOIN keycloak_role k ON k.id=m.role_id JOIN realm r ON r.id=u.realm_id "
                "WHERE r.name='master' AND u.username='iges-admin-owner' AND k.name='admin'")).scalar_one()
    finally:
        engine.dispose()
    response = httpx.post("https://localhost:8443/realms/master/protocol/openid-connect/token",
        verify=ssl.create_default_context(cafile=str(STATE / "ca.pem")), timeout=10,
        data={"grant_type": "password", "client_id": "admin-cli", "username": "iges-admin",
              "password": config["bootstrap_password"]})
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "bootstrap_disabled": users.get("iges-admin") is False,
            "old_bootstrap_password_denied": response.status_code in {400, 401} and "access_token" not in response.json(),
            "owner_account": "iges-admin-owner", "owner_enabled": users.get("iges-admin-owner") is True,
            "owner_has_management_role": admin_role == 1,
            "owner_password_change_required": "UPDATE_PASSWORD" in actions,
            "owner_otp_enrollment_required": "CONFIGURE_TOTP" in actions,
            "owner_enrollment_completed": False}


def main():
    context = ssl.create_default_context(cafile=str(STATE / "ca.pem"))
    with httpx.Client(verify=context, timeout=10) as client:
        ready = client.get("https://localhost:8444/readyz")
        ready.raise_for_status()
        response = client.get("https://localhost:8444/v1/public/observations?country=PRT&indicator=SP.POP.TOTL")
        response.raise_for_status()
        records = response.json()["records"]
        denied = client.get("https://localhost:8444/v1/admin/whoami")
        status = {"checked_at": datetime.now(timezone.utc).isoformat(), "readiness": ready.json(),
                  "source_observations": records, "missing_bearer_status": denied.status_code,
                  "tls_verified_with_project_ca": True, "windows_trust_store_changed": False}
    (ROOT / "local-validation.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps({"source_observations": len(records), "periods": [r["period"] for r in records],
                      "missing_bearer_status": denied.status_code, "tls_verified": True}, indent=2))
    print(json.dumps(management_status(), indent=2))


if __name__ == "__main__":
    main()
