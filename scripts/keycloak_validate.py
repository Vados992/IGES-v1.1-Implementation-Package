"""Exercise the actual local IdP with a temporary password/OTP test account."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import ssl
import struct
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from scripts.windows_pilot import STATE, ROOT

IDP = "https://localhost:8443"


class Form(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.action = None
        self.fields = {}
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("method", "").lower() == "post":
            self.action = attrs["action"]
        if tag == "input" and attrs.get("name"):
            self.fields[attrs["name"]] = attrs.get("value", "")


def totp(secret):
    digest = hmac.new(secret.encode(), struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f"{(struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000:06}"


def checked(response):
    if response.status_code >= 400:
        # Never include token exchange bodies, credentials or form values in logs.
        raise RuntimeError(f"Keycloak request failed with HTTP {response.status_code} at {response.request.url.path}")
    return response


def main(client_id='iges-desktop', redirect='http://127.0.0.1:8765/callback'):
    config = json.loads((STATE / "settings.json").read_text())
    context = ssl.create_default_context(cafile=str(STATE / "ca.pem"))
    with httpx.Client(verify=context, timeout=20) as admin:
        access = checked(admin.post(IDP + "/realms/master/protocol/openid-connect/token", data={
            "grant_type": "password", "client_id": "admin-cli", "username": "iges-admin",
            "password": config["bootstrap_password"]})).json()["access_token"]
        admin.headers["Authorization"] = "Bearer " + access
        base = IDP + "/admin/realms/iges"
        # Set AMR references on actual execution configs, including an existing imported realm.
        executions = checked(admin.get(base + "/authentication/flows/iges-mfa/executions")).json()
        for execution in executions:
            config_id = execution.get("authenticationConfig")
            if not config_id:
                continue
            item = checked(admin.get(base + "/authentication/config/" + config_id)).json()
            method = {"iges-password-ref": "pwd", "iges-otp-ref": "otp"}.get(item["alias"])
            if method:
                item["config"] = {"default.reference.value": method, "default.reference.maxAge": "900"}
                checked(admin.put(base + "/authentication/config/" + item["id"], json=item))
        username = "mfa-probe-" + secrets.token_hex(6)
        password = secrets.token_urlsafe(32)
        secret = secrets.token_urlsafe(24)
        created = checked(admin.post(base + "/users", json={
            "username": username, "enabled": True, "firstName": "Temporary", "lastName": "Security Probe",
            "email": username + "@example.invalid", "emailVerified": True,
            "credentials": [{"type": "password", "value": password, "temporary": False},
                {"type": "otp", "secretData": json.dumps({"value": secret}),
                 "credentialData": json.dumps({"subType": "totp", "digits": 6, "counter": 0,
                                                "period": 30, "algorithm": "HmacSHA1"})}]}))
        user_url = created.headers["location"]
        result = {"checked_at": datetime.now(timezone.utc).isoformat(), "issuer": IDP + "/realms/iges", 'client_id': client_id}
        try:
            role = checked(admin.get(base + "/roles/ingestor")).json()
            checked(admin.post(user_url + "/role-mappings/realm", json=[role]))
            verifier = secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            state = secrets.token_urlsafe(32)
            auth_url = IDP + "/realms/iges/protocol/openid-connect/auth?" + urlencode({
                "client_id": client_id, "response_type": "code", "scope": "openid",
                "redirect_uri": redirect, "state": state, "code_challenge": challenge,
                "code_challenge_method": "S256"})
            with httpx.Client(verify=context, timeout=20, follow_redirects=False) as browser:
                form = Form(checked(browser.get(auth_url)).text)
                response = checked(browser.post(form.action, data={**form.fields, "username": username, "password": password}))
                form = Form(response.text)
                if response.status_code != 200 or "otp" not in form.fields:
                    raise RuntimeError("Password-only login did not require OTP")
                result["password_only_denied"] = True
                wrong = f"{(int(totp(secret)) + 123) % 1000000:06}"
                response = checked(browser.post(form.action, data={**form.fields, "otp": wrong}))
                form = Form(response.text)
                if response.status_code != 200 or "otp" not in form.fields:
                    raise RuntimeError("Incorrect OTP was not rejected")
                result["incorrect_otp_denied"] = True
                response = checked(browser.post(form.action, data={**form.fields, "otp": totp(secret)}))
                target = urlsplit(response.headers.get("location", ""))
                query = parse_qs(target.query)
                if target.netloc != urlsplit(redirect).netloc or target.path != urlsplit(redirect).path or query.get("state") != [state] or "code" not in query:
                    raise RuntimeError("OTP login did not return the expected authorization code")
                origin = urlsplit(redirect).scheme + '://' + urlsplit(redirect).netloc
                token_response = checked(browser.post(IDP + "/realms/iges/protocol/openid-connect/token", data={
                    "grant_type": "authorization_code", "client_id": client_id, "code": query["code"][0],
                    "redirect_uri": redirect, "code_verifier": verifier}, headers={'Origin': origin} if client_id == 'iges-web' else {}))
                if client_id == 'iges-web':
                    if token_response.headers.get('access-control-allow-origin') != origin:
                        raise RuntimeError('Browser token exchange CORS origin was not approved')
                    result['browser_token_cors_verified'] = True
                token = token_response.json()['access_token']
                api = browser.get("https://localhost:8444/v1/admin/whoami", headers={"Authorization": "Bearer " + token})
                if api.status_code != 200:
                    raise RuntimeError(f"Actual IdP token denied by API: {api.status_code} {api.json().get('detail')}")
                identity = api.json()
                if not identity["mfa_enforced"] or not {"pwd", "otp"}.issubset(identity["amr"]):
                    raise RuntimeError("API did not confirm real password/OTP context")
                result["authorization_code_pkce"] = True
                result["api_signature_and_mfa_validated"] = True
                result["amr"] = identity["amr"]
                result["operator_enrollment_completed"] = False
        finally:
            checked(admin.delete(user_url))
            result["temporary_user_removed"] = True
        (ROOT / "mfa-validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
