# Production deployment: explicit GO / NO-GO

| Gate | Evidence required | Status |
| --- | --- | --- |
| G1 Scoped single-project pilot | RLS and API test results | Automated disposable-DB checks supplied; inspect current CI |
| G2 Live source ingestion | Captured timestamped source snapshot | Bounded World Bank import verified in CI and Windows pilot; no coverage guarantee |
| G3 Independent provenance review | Two reviewed source attestations | NOT VERIFIED |
| G4 Privileged user security | Identity provider, MFA, external security test | Local Keycloak password/OTP and PKCE tested; owner enrollment and external review pending |
| G5 Financial integrity | Concurrent transaction tests + reconciliation | Concurrency checks supplied; external reconciliation absent |
| G6 Availability and disaster recovery | PITR restore drill, measured RPO/RTO | NOT IMPLEMENTED |
| G7 Public-site safety | HTTPS, WAF, alerts, backup, incident rotation | NOT IMPLEMENTED |
| G8 Legal/GDPR | DPIA when applicable, controller/legal signoff | NOT VERIFIED |
| G9 Public political findings | Editorial board, rebuttal process, correction history | NOT IMPLEMENTED |

**Current decision: NO-GO for publicly advertised, security-sensitive or multi-tenant operation.**

The following are not supplied by a GitHub repository: a domain, cloud resources,
TLS certificates, operator identity, OIDC tenant, production secrets, bank-data access,
independent reviewers and competent legal authorization.

A bounded public-data pilot has been run in disposable CI and the owner's native
Windows environment. Actual receipts distinguish imported source data from test
fixtures. This does not establish public service readiness, complete coverage,
independent source verification or the production gates above.
