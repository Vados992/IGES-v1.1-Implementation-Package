"""Isolated per-user Windows pilot. No services, firewall rules or trust-store edits."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "work/windows-pilot"
STATE = ROOT / "private"
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def run(command, **kwargs):
    return subprocess.run(command, check=True, creationflags=FLAGS, **kwargs)  # noqa: S603


def paths():
    return (next((ROOT / "java").glob("*/bin/java.exe")).parents[1],
            next((ROOT / "identity").glob("keycloak-*")), ROOT / "database/pgsql/bin")


def certificate():
    if (STATE / "server.pem").exists():
        return
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "IGES local pilot CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                         key_encipherment=False, data_encipherment=False, key_agreement=False,
                         key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    leaf = (x509.CertificateBuilder().subject_name(x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])).issuer_name(ca_name)
        .public_key(server_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256()))
    for name, key in [("ca-key.pem", ca_key), ("server-key.pem", server_key)]:
        (STATE / name).write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (STATE / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (STATE / "server.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM)
                                      + ca.public_bytes(serialization.Encoding.PEM))


def realm(config):
    def mapper(name, provider, values):
        return {"name": name, "protocol": "openid-connect", "protocolMapper": provider,
                "config": {"access.token.claim": "true", "id.token.claim": "false", **values}}
    return {"realm": "iges", "enabled": True, "sslRequired": "all", "registrationAllowed": False,
        "resetPasswordAllowed": False, "rememberMe": False, "bruteForceProtected": True,
        "failureFactor": 5, "accessTokenLifespan": 300, "ssoSessionIdleTimeout": 900,
        "ssoSessionMaxLifespan": 3600, "eventsEnabled": True, "eventsExpiration": 604800,
        "adminEventsEnabled": True, "adminEventsDetailsEnabled": False,
        "passwordPolicy": "length(16) and notUsername and notEmail",
        "roles": {"realm": [{"name": role} for role in ["analyst", "reviewer", "ingestor", "editor", "counsel", "panel", "respondent", "reader", "administrator"]]},
        "browserFlow": "iges-mfa", "authenticationFlows": [
            {"alias": "iges-mfa", "providerId": "basic-flow", "topLevel": True, "builtIn": False,
             "authenticationExecutions": [
                 {"authenticator": "auth-username-password-form", "requirement": "REQUIRED", "priority": 10,
                  "authenticatorFlow": False, "authenticatorConfig": "iges-password-ref"},
                 {"authenticator": "auth-otp-form", "requirement": "REQUIRED", "priority": 20,
                  "authenticatorFlow": False, "authenticatorConfig": "iges-otp-ref"}]}],
        "authenticatorConfig": [
            {"alias": "iges-password-ref", "config": {"default.reference.value": "pwd", "default.reference.maxAge": "900"}},
            {"alias": "iges-otp-ref", "config": {"default.reference.value": "otp", "default.reference.maxAge": "900"}}],
        "clients": [{"clientId": "iges-desktop", "name": "IGES local operator", "enabled": True,
            "publicClient": True, "standardFlowEnabled": True, "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False, "redirectUris": ["http://127.0.0.1:8765/callback"],
            "attributes": {"pkce.code.challenge.method": "S256"},
            "protocolMappers": [
                mapper("project", "oidc-hardcoded-claim-mapper", {"claim.name": "project_id",
                       "claim.value": config["project_id"], "jsonType.label": "String"}),
                mapper("roles", "oidc-usermodel-realm-role-mapper", {"claim.name": "roles",
                       "multivalued": "true", "jsonType.label": "String"}),
                mapper("audience", "oidc-audience-mapper", {"included.custom.audience": "iges-api"}),
                mapper("authentication methods", "oidc-amr-mapper", {}),
                mapper("authentication time", "oidc-usersessionmodel-note-mapper", {
                       "user.session.note": "AUTH_TIME", "claim.name": "auth_time", "jsonType.label": "long"})]}],
        "users": [{"username": "iges-operator", "enabled": True,
            "firstName": "IGES", "lastName": "Operator",
            "requiredActions": ["UPDATE_PASSWORD", "CONFIGURE_TOTP"],
            "realmRoles": ["analyst", "reviewer", "ingestor"],
            "credentials": [{"type": "password", "value": config["operator_password"], "temporary": True}]}]}


def setup():
    if os.name != "nt":
        raise RuntimeError("This launcher is only for Windows")
    STATE.mkdir(parents=True, exist_ok=True)
    # Restrict the private state before creating credentials or keys.
    sid = run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout.split('"')[3]
    run(["icacls", str(STATE), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"], capture_output=True)
    config_path = STATE / "settings.json"
    if not config_path.exists():
        config_path.write_text(json.dumps({"project_id": str(uuid4()),
            **{name: secrets.token_urlsafe(36) for name in ["admin_password", "runtime_password",
                "identity_password", "bootstrap_password", "operator_password"]}}, indent=2), encoding="utf-8")
    config = json.loads(config_path.read_text())
    certificate()
    _, identity, pg = paths()
    data = STATE / "postgres"
    if not (data / "PG_VERSION").exists():
        password_file = STATE / "init-password"
        password_file.write_text(config["admin_password"], encoding="utf-8")
        try:
            run([str(pg / "initdb.exe"), "-D", str(data), "-U", "iges_admin", "--pwfile", str(password_file),
                 "--encoding=UTF8", "--locale=C", "--auth-host=scram-sha-256", "--auth-local=scram-sha-256"],
                stdout=(ROOT / "initdb.log").open("w"), stderr=subprocess.STDOUT)
        finally:
            password_file.unlink(missing_ok=True)
        with (data / "postgresql.conf").open("a") as handle:
            handle.write("\nlisten_addresses='127.0.0.1'\nport=55432\n")
    status = subprocess.run([str(pg / "pg_ctl.exe"), "-D", str(data), "status"],  # noqa: S603
                            capture_output=True, creationflags=FLAGS)
    if status.returncode != 0:
        run([str(pg / "pg_ctl.exe"), "-D", str(data), "-l", str(ROOT / "postgres.log"), "-w", "start"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    environment = {**os.environ, "PGPASSWORD": config["admin_password"]}
    psql = [str(pg / "psql.exe"), "-h", "127.0.0.1", "-p", "55432", "-U", "iges_admin", "-v", "ON_ERROR_STOP=1"]
    if not (STATE / "database-initialized").exists():
        init = ("CREATE DATABASE iges;\nCREATE ROLE iges_identity LOGIN PASSWORD '" + config["identity_password"]
                + "' NOSUPERUSER NOCREATEDB NOCREATEROLE;\nCREATE DATABASE iges_identity OWNER iges_identity;\n"
                "REVOKE ALL ON DATABASE iges_identity FROM PUBLIC;\nGRANT CONNECT ON DATABASE iges_identity TO iges_identity;\n")
        run([*psql, "-d", "postgres"], input=init, text=True, env=environment, capture_output=True)
        template = (REPO / "db/init/01_schema.template").read_text()
        variables = f"\\set runtime_password '{config['runtime_password']}'\n\\set project_id '{config['project_id']}'\n"
        migrations = ''.join('\n' + path.read_text() for path in sorted((REPO / 'db/migrations').glob('*.sql')))
        run([*psql, "-d", "iges", "--single-transaction"], input=variables + template + migrations,
            text=True, env=environment, capture_output=True)
        (STATE / "database-initialized").touch()
    imported = identity / "data/import"
    imported.mkdir(parents=True, exist_ok=True)
    import_file = imported / "iges-realm.json"
    import_file.write_text(json.dumps(realm(config), indent=2), encoding="utf-8")
    run(["icacls", str(import_file), "/inheritance:r", "/grant:r", f"*{sid}:F"], capture_output=True)
    print("Private state, localhost TLS and isolated PostgreSQL databases prepared", flush=True)


def environment():
    config = json.loads((STATE / "settings.json").read_text())
    from sqlalchemy.engine import URL
    return {**os.environ,
        "IGES_DATABASE_URL": URL.create("postgresql+psycopg", username="iges_runtime",
            password=config["runtime_password"], host="127.0.0.1", port=55432, database="iges").render_as_string(hide_password=False),
        "IGES_PUBLIC_PROJECT_ID": config["project_id"], "IGES_OIDC_ISSUER": "https://localhost:8443/realms/iges",
        "IGES_OIDC_AUDIENCE": "iges-api", "IGES_OIDC_JWKS_URL": "https://localhost:8443/realms/iges/protocol/openid-connect/certs",
        "IGES_OIDC_CA_FILE": str(STATE / "ca.pem"), "IGES_OIDC_REQUIRE_MFA": "true"}


def start():
    setup()
    java, identity, _ = paths()
    config = json.loads((STATE / "settings.json").read_text())
    with httpx.Client(verify=str(STATE / "ca.pem"), timeout=3) as client:
        try:
            client.get("https://localhost:8443/realms/iges/.well-known/openid-configuration").raise_for_status()
            identity_running = True
        except httpx.HTTPError:
            identity_running = False
    if not identity_running:
        env = {**os.environ, "JAVA_HOME": str(java), "KC_DB": "postgres",
            "KC_CACHE": "local",
            "KC_DB_URL": "jdbc:postgresql://127.0.0.1:55432/iges_identity", "KC_DB_USERNAME": "iges_identity",
            "KC_DB_PASSWORD": config["identity_password"], "KC_BOOTSTRAP_ADMIN_USERNAME": "iges-admin",
            "KC_BOOTSTRAP_ADMIN_PASSWORD": config["bootstrap_password"],
            "KC_HOSTNAME": "https://localhost:8443", "KC_HTTP_HOST": "127.0.0.1", "KC_HTTP_ENABLED": "false",
            "KC_HTTPS_CERTIFICATE_FILE": str(STATE / "server.pem"),
            "KC_HTTPS_CERTIFICATE_KEY_FILE": str(STATE / "server-key.pem")}
        process = subprocess.Popen([str(identity / "bin/kc.bat"), "start", "--import-realm"],  # noqa: S603
            cwd=identity, env=env, creationflags=FLAGS, stdout=(ROOT / "keycloak.log").open("a"), stderr=subprocess.STDOUT)
        (STATE / "keycloak.pid").write_text(str(process.pid))
    with httpx.Client(verify=str(STATE / "ca.pem"), timeout=3) as client:
        for _ in range(180):
            try:
                client.get("https://localhost:8443/realms/iges/.well-known/openid-configuration").raise_for_status()
                break
            except httpx.HTTPError:
                time.sleep(1)
        else:
            raise RuntimeError("Keycloak did not become ready; inspect local keycloak.log")
        try:
            client.get("https://localhost:8444/readyz").raise_for_status()
        except httpx.HTTPError:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",  # noqa: S603
                "--port", "8444", "--no-access-log", "--ssl-certfile", str(STATE / "server.pem"), "--ssl-keyfile", str(STATE / "server-key.pem")],
                cwd=REPO, env=environment(), creationflags=FLAGS, stdout=(ROOT / "api.log").open("a"), stderr=subprocess.STDOUT)
            (STATE / "api.pid").write_text(str(process.pid))
        for _ in range(30):
            try:
                client.get("https://localhost:8444/readyz").raise_for_status()
                break
            except httpx.HTTPError:
                time.sleep(1)
        else:
            raise RuntimeError("API did not become ready; inspect local api.log")
    print("Keycloak: https://localhost:8443 ; API: https://localhost:8444/docs", flush=True)
    (identity / "data/import/iges-realm.json").unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["setup", "start", "import", "verify"])
    action = parser.parse_args().action
    if action == "setup":
        setup()
    elif action == "start":
        start()
    else:
        module = "app.seed_worldbank" if action == "import" else "app.verify_integrity"
        args = ["--country", "PRT", "--indicator", "SP.POP.TOTL", "--start", "2022", "--end", "2024"] if action == "import" else []
        result = run([sys.executable, "-m", module, *args], cwd=REPO, env=environment(), capture_output=True, text=True)
        print(result.stdout, end="")


if __name__ == "__main__":
    main()

