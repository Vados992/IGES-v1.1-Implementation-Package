# Native Windows controlled pilot

This deployment uses the existing Python environment, portable PostgreSQL 16.15,
Temurin Java 21 and Keycloak 26.8.1, without Docker/WSL, Windows services, firewall
rules or system-wide runtime installation. It is bound to this Windows account
and must be started after a reboot. A portable publisher archive is not a signed
or independently audited deployment; exact download receipts are retained locally.

## Use the installed pilot

From the repository, run `deploy/windows/Start-IGES.ps1` to start and
`deploy/windows/Stop-IGES.ps1` to stop only this installation. Persistent state is
under ignored `work/windows-pilot/private`; it contains passwords, keys and the
new database cluster. Do not copy it into GitHub, an audit bundle or a shared folder.

- API and OpenAPI: `https://localhost:8444/docs`.
- Keycloak: `https://localhost:8443`.
- PostgreSQL: `127.0.0.1:55432`, no LAN listener.
- Keycloak uses a local cache; cluster discovery/listener ports are disabled.

The user declined installation of a trusted root certificate. Windows trust is
unchanged. Application clients trust only the generated project CA file; TLS
verification is enabled. Browsers may display a warning for localhost. The CA
certificate can be inspected independently; do not disable global TLS verification.
The server certificate expires after 90 days and needs an operator-managed renewal.

Run `deploy/windows/Login-IGES.ps1` in your own terminal. It displays the initial
operator password locally, opens an Authorization Code + PKCE browser login, and
requires password replacement and OTP enrollment using your authenticator. Tokens
stay in memory and are never printed or saved. A successful login displays the
API's verified identity. The optional `python -m scripts.desktop_login
--ingest-worldbank` performs an authorized import in that session.

## Identity boundaries

`iges-operator` has analyst, reviewer and ingestor roles for this pilot only. The
same subject still cannot review its own claim. Independent substantive reviews
need a separately enrolled person; no fictitious second person is provisioned.
The application client forbids password/direct grants and service accounts. The
browser flow requires password and OTP and emits signed AMR claims. API access
also requires recent auth_time (15 minutes by default), issuer, audience, project,
expiry, signature and route role. Arbitrary MFA headers have no authority.

The setup validation is followed by `python -m scripts.keycloak_admin_handoff`:
it provisions `iges-admin-owner`, requires password replacement and OTP enrollment,
then disables temporary bootstrap access and checks that its old password is denied.
Run `deploy/windows/Login-IGES.ps1 -Administrator` in your own terminal to complete
management enrollment. Until that step succeeds, management access is pending;
it is not reported as a completed owner MFA login. Master-realm management and
recovery paths still require independent review.

## Validation and audit

`python -m scripts.keycloak_validate` uses the initial bootstrap administrator to
create a short-lived test user, exercises the actual password/OTP + PKCE flow,
verifies the token through the live API and deletes the test user. Its redacted
receipt explicitly distinguishes test success from your own enrollment. It cannot
run with retired bootstrap credentials; do not re-enable them just for this test.

`python -m scripts.windows_pilot import` imports actual World Bank source records.
`python -m scripts.windows_pilot verify` checks evidence/observation/audit integrity.
No fixture observations are inserted into the working local pilot.
This local cluster is separate from any previous databases on the computer.

External security review is not completed. See
`docs/INDEPENDENT_SECURITY_REVIEW.md` for scope, required evidence and acceptance.
This remains NO-GO for public deployment, confidential sources and hostile tenancy.

Primary documentation: [PostgreSQL Windows binaries](https://www.postgresql.org/download/windows/),
[Keycloak TLS](https://www.keycloak.org/server/enabletls),
[Keycloak authentication and AMR](https://www.keycloak.org/docs/latest/server_admin/).
