"""Interactive Authorization Code + PKCE login; keeps tokens only in memory."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import ssl
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from scripts.windows_pilot import STATE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingest-worldbank", action="store_true")
    args = parser.parse_args()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(32)
    response = {}
    redirect = "http://127.0.0.1:8765/callback"

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            target = urlsplit(self.path)
            query = parse_qs(target.query)
            if target.path != "/callback" or not secrets.compare_digest(query.get("state", [""])[0], state):
                self.send_error(400)
                return
            response.update({key: values[0] for key, values in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"IGES sign-in received. You can close this tab.")

        def log_message(self, *args):
            pass

    context = ssl.create_default_context(cafile=str(STATE / "ca.pem"))
    with httpx.Client(verify=context, timeout=20) as client:
        discovery = client.get("https://localhost:8443/realms/iges/.well-known/openid-configuration")
        discovery.raise_for_status()
        metadata = discovery.json()
        if metadata["issuer"] != "https://localhost:8443/realms/iges":
            raise RuntimeError("Unexpected local issuer")
        for key in ["authorization_endpoint", "token_endpoint"]:
            endpoint = urlsplit(metadata[key])
            if endpoint.scheme != "https" or endpoint.netloc != "localhost:8443":
                raise RuntimeError("Unexpected local OIDC endpoint")
        url = metadata["authorization_endpoint"] + "?" + urlencode({
            "client_id": "iges-desktop", "response_type": "code", "scope": "openid",
            "redirect_uri": redirect, "state": state, "code_challenge": challenge,
            "code_challenge_method": "S256", "max_age": "0", "prompt": "login"})
        with HTTPServer(("127.0.0.1", 8765), Callback) as server:
            server.timeout = 300
            webbrowser.open(url)
            server.handle_request()
        if "code" not in response:
            raise RuntimeError("OIDC login was not completed")
        token = client.post(metadata["token_endpoint"], data={"grant_type": "authorization_code",
            "client_id": "iges-desktop", "code": response["code"], "redirect_uri": redirect,
            "code_verifier": verifier})
        token.raise_for_status()
        headers = {"Authorization": "Bearer " + token.json()["access_token"]}
        identity = client.get("https://localhost:8444/v1/admin/whoami", headers=headers)
        identity.raise_for_status()
        print(json.dumps(identity.json(), indent=2))
        if args.ingest_worldbank:
            imported = client.post("https://localhost:8444/v1/admin/ingest/worldbank", headers=headers,
                json={"country": "PRT", "indicator": "SP.POP.TOTL", "start": 2022, "end": 2024}, timeout=45)
            imported.raise_for_status()
            print(json.dumps(imported.json(), indent=2))


if __name__ == "__main__":
    main()
