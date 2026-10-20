"""Replace temporary bootstrap management access with an owner enrollment account."""
import json
import secrets
import ssl
from datetime import datetime, timezone

import httpx

from scripts.windows_pilot import STATE, ROOT
from scripts.keycloak_validate import checked, IDP


def main():
    receipt = ROOT / "admin-handoff.json"
    if receipt.exists():
        print("Management handoff already recorded; do not re-enable bootstrap access")
        return
    config_path = STATE / "settings.json"
    config = json.loads(config_path.read_text())
    config.setdefault("owner_password", secrets.token_urlsafe(36))
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    with httpx.Client(verify=ssl.create_default_context(cafile=str(STATE / "ca.pem")), timeout=20) as client:
        authentication = client.post(IDP + "/realms/master/protocol/openid-connect/token", data={
            "grant_type": "password", "client_id": "admin-cli", "username": "iges-admin",
            "password": config["bootstrap_password"]})
        if authentication.status_code in {400, 401}:
            # Recover a completed handoff interrupted after disabling bootstrap.
            from scripts.local_status import management_status
            result = management_status()
            required = ["bootstrap_disabled", "old_bootstrap_password_denied", "owner_enabled",
                        "owner_has_management_role", "owner_password_change_required", "owner_otp_enrollment_required"]
            if not all(result.get(key) for key in required):
                raise RuntimeError("Bootstrap unavailable and management handoff could not be verified")
            receipt.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2))
            return
        token = checked(authentication).json()["access_token"]
        client.headers["Authorization"] = "Bearer " + token
        base = IDP + "/admin/realms/master"
        users = checked(client.get(base + "/users", params={"username": "iges-admin-owner", "exact": "true"})).json()
        if users:
            owner_id = users[0]["id"]
        else:
            created = checked(client.post(base + "/users", json={
                "username": "iges-admin-owner", "enabled": True, "firstName": "IGES", "lastName": "Owner",
                "requiredActions": ["UPDATE_PASSWORD", "CONFIGURE_TOTP"],
                "credentials": [{"type": "password", "value": config["owner_password"], "temporary": True}]}))
            owner_id = created.headers["location"].rsplit("/", 1)[1]
        role = checked(client.get(base + "/roles/admin")).json()
        checked(client.post(base + "/users/" + owner_id + "/role-mappings/realm", json=[role]))
        owners = checked(client.get(base + "/users/" + owner_id)).json()
        if not {"UPDATE_PASSWORD", "CONFIGURE_TOTP"}.issubset(owners.get("requiredActions", [])):
            raise RuntimeError("Owner account is not gated on password replacement and OTP enrollment")
        bootstrap = checked(client.get(base + "/users", params={"username": "iges-admin", "exact": "true"})).json()
        if len(bootstrap) != 1:
            raise RuntimeError("Unexpected bootstrap account lookup")
        checked(client.put(base + "/users/" + bootstrap[0]["id"], json={"enabled": False}))
        # Verify its old password can no longer obtain management tokens.
        denied = client.post(IDP + "/realms/master/protocol/openid-connect/token", data={
            "grant_type": "password", "client_id": "admin-cli", "username": "iges-admin",
            "password": config["bootstrap_password"]})
        if denied.status_code not in {400, 401} or "access_token" in denied.json():
            raise RuntimeError("Bootstrap access was not denied")
        result = {"checked_at": datetime.now(timezone.utc).isoformat(), "bootstrap_disabled": True,
                  "old_bootstrap_password_denied": True, "owner_account": "iges-admin-owner",
                  "owner_password_change_required": True, "owner_otp_enrollment_required": True,
                  "owner_enrollment_completed": False}
        receipt.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
