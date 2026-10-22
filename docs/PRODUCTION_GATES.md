# Production deployment: explicit GO / NO-GO

| Gate | Evidence required | Status |
| --- | --- | --- |
| G1 Scoped single-project pilot | RLS and API test results | Automated disposable-DB checks supplied; inspect current CI |
| G2 Live source ingestion | Captured timestamped source snapshot | Bounded World Bank and USAspending imports, plus actual primary-document intake, verified in CI; no coverage/authenticity guarantee |
| G3 Independent provenance review | Two reviewed source attestations | NOT VERIFIED |
| G4 Privileged user security | Identity provider, MFA, external security test | Actual disposable Keycloak desktop/web password/OTP and PKCE tested; owner enrollment is not evidenced by those tests; real reviewer provisioning and external review pending |
| G5 Financial integrity | Concurrent transaction tests + reconciliation | Concurrency checks supplied; external reconciliation absent |
| G6 Availability and disaster recovery | PITR restore drill, measured RPO/RTO | Disposable same-cluster dump/restore tested; encrypted offsite backup/PITR and measured RPO/RTO NOT VERIFIED |
| G7 Public-site safety | HTTPS, WAF, alerts, backup, incident rotation | NOT IMPLEMENTED |
| G8 Legal/GDPR | DPIA when applicable, controller/legal signoff | NOT VERIFIED |
| G9 Public political findings | Editorial board, rebuttal process, correction history | Revision-bound review/reply/legal gates and immutable corrections implemented/tested; actual independent editorial/legal acceptance NOT VERIFIED |

**Current decision: NO-GO for publicly advertised, security-sensitive or multi-tenant operation.**

The repository's localhost certificates and isolated test IdP are not production
infrastructure. An actual domain, protected hosting, production TLS/key custody,
operator identity, enrolled IdP users, production secrets, bank-data authorization,
independent reviewers and competent legal authority require real provisioning.

A bounded public-data pilot has been run in disposable CI and the owner's native
Windows environment. Actual receipts distinguish imported source data from test
fixtures. This does not establish public service readiness, complete coverage,
independent source verification or the production gates above.

The exact [FR-01–FR-16 ledger](FR_STATUS.md) records bounded P0 implementation and
partial P1 requirements. Automated technical gates do not certify GDPR compliance
or authorize publication of an actual case. Confidential sources, personal-data
retention/erasure, rights requests and public corrections require an approved
controller process and independent legal/security review.
