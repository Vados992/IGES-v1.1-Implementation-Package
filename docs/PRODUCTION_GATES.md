# Production deployment: explicit GO / NO-GO

| Gate | Evidence required | Status |
| --- | --- | --- |
| G1 Scoped single-project pilot | RLS and API test results | Automated disposable-DB checks supplied; inspect current CI |
| G2 Live source ingestion | Captured timestamped source snapshot | PENDING operator run |
| G3 Independent provenance review | Two reviewed source attestations | NOT VERIFIED |
| G4 Privileged user security | Identity provider, MFA, external security test | NOT IMPLEMENTED |
| G5 Financial integrity | Concurrent transaction tests + reconciliation | Concurrency checks supplied; external reconciliation absent |
| G6 Availability and disaster recovery | PITR restore drill, measured RPO/RTO | NOT IMPLEMENTED |
| G7 Public-site safety | HTTPS, WAF, alerts, backup, incident rotation | NOT IMPLEMENTED |
| G8 Legal/GDPR | DPIA when applicable, controller/legal signoff | NOT VERIFIED |
| G9 Public political findings | Editorial board, rebuttal process, correction history | NOT IMPLEMENTED |

**Current decision: NO-GO for publicly advertised, security-sensitive or multi-tenant operation.**

The following are not supplied by a GitHub repository: a domain, cloud resources,
TLS certificates, operator identity, OIDC tenant, production secrets, bank-data access,
independent reviewers and competent legal authorization.

A genuinely live public-data pilot requires a trusted operator to bring up Docker
and execute the upstream import command; the repository does not simulate or
pretend the data have been imported.
