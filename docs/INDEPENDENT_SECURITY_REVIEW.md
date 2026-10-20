# External security review brief — not a completed independent audit

Owner: repository owner. Auditor: not selected. Acceptance: a named reviewer outside
the implementation team must issue a dated, commit-bound report with reproducible
findings, severity, scope, exclusions, retest evidence and signed disposition.
Automated tests and scans supplied by this repository are developer evidence only.

## Authorized scope to agree before an external test

Use an isolated copy of this pilot with public data and disposable identities.
The Windows deployment binds PostgreSQL (55432), Keycloak (8443) and API (8444) to
loopback. Do not expose it externally or share local secrets to grant audit access.
Arrange an isolated auditor environment and explicit rules of engagement first.
No external auditor is contacted or commissioned by this repository.

## Required checks and artifacts

| Area | Required review evidence |
| --- | --- |
| OIDC | Authorization Code + PKCE S256, state handling, issuer/audience/signature checks, expiry, key rotation and IdP outage behavior |
| MFA | Real password/OTP enrollment and login; denied single-factor tokens; signed AMR/auth_time and configured ACR; recovery, factor reset and privileged-user policy |
| Keycloak | Direct grants disabled on the application client; no client service accounts; password/brute-force policy; bootstrap administrator lifecycle and master-realm MFA |
| Database | Actual restricted login, forced RLS, cross-project GUC manipulation, composite references, append-only grants, SQL injection and SQL-level review/return rules |
| Financial events | Parallel replay/refund/reversal tests; duplicate conflict handling; currency and decimal precision; evidence does not establish actual banking execution |
| Evidence | Exact upstream bytes/digests/locators, pagination/NULL semantics, bounded requests, SSRF/redirect rejection and revision retention |
| Audit | Canonical payload reconstruction, concurrency, tampering and truncation limitations; verify developer evidence against the exact reviewed commit |
| Windows | ACLs on keys/passwords/data, process ownership on stop/restart, loopback bindings including Java cache/discovery ports, TLS chain validation and certificate expiry |
| Dependencies | Publisher download receipts, application dependency list, package/container scans, secrets scan and excluded areas |
| Recovery | Encrypted/offline backup policy, isolated full-cluster restore and role provisioning; measured recovery evidence, not only a same-cluster CI restore |

## Release disposition

Keep production/confidential-source/multi-tenant NO-GO until blockers are closed.
Record each finding as: ID, affected commit/path, reproduction, impact, severity,
owner, fix commit and independent retest result. An implementation team's statement
that tests passed cannot replace the external reviewer's report.

Sources: [Keycloak administration](https://www.keycloak.org/docs/latest/server_admin/),
[Keycloak TLS](https://www.keycloak.org/server/enabletls),
[PostgreSQL Windows distribution](https://www.postgresql.org/download/windows/).
