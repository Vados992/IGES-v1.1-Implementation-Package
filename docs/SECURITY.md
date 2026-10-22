# Security boundary of the evidence MVP

The application is a controlled **single-project, public-source** pilot. No
confidential-source vault, hostile tenant isolation, legal certification or
production security assurance is claimed.

## Implemented controls

- Privileged requests verify OIDC signature/JWKS over verified HTTPS, issuer,
  audience, expiry, subject, project, typed roles, signed MFA and recent authentication.
  Missing configuration fails closed. Browser and desktop use Authorization Code
  + PKCE; their password grants/service accounts are disabled.
- A current IdP role and unrevoked per-case membership are required. Authors of
  claims/evidence/documents/hypotheses cannot review their own material. Assigned
  reviewers declare conflicts; SQL also enforces independence/revision/quotation
  prerequisites. Author withdrawal is terminal.
- Runtime login is non-superuser/NOBYPASSRLS and administrator-bound to one project.
  Forced RLS requires that binding and transaction context. Runtime has SELECT/INSERT,
  no UPDATE/DELETE/TRUNCATE on the trail. The DB does not authenticate individual JWT
  subjects: case authorization is an API boundary. Never expose shared DB credentials
  to end users or treat them as a hostile-tenant isolation mechanism.
- Original/page hashes, foreign keys, quote-on-page constraints, content seals and
  audit sequencing detect corruption. The verifier checks both official adapters'
  raw values/locators, workspace content/seals, revisions, manifests and audit linkage.
- An 8 MiB original limit and separate child/worker constrain parsing by time, CPU,
  memory, archive expansion/depth/path and image pixels. Original downloads require
  successful actual ClamAV scan and extraction. Children receive no DB credentials.
  Compose worker has read-only root, no capabilities and internal networks; scanner
  can update signatures through its separate network attachment.
- No arbitrary URL ingestion exists. Official adapters construct allowlisted HTTPS
  requests, reject redirects, bound bytes/records and retain nulls. Catalogue URLs
  are metadata, never fetched by parsers.
- Core writes have atomic idempotency receipts and audited content. If-Match rejects
  stale revisions. A content revision invalidates substantive approvals. Publication
  is off by default and requires current review, legal/privacy, reply and disputed-case
  panel gates. Published versions are immutable.
- Bearer auth uses no session cookies. Source text is rendered as text under CSP.
  Access tokens stay in memory; temporary PKCE state/verifier is deleted on callback.
  Originals use attachment/nosniff headers and never appear publicly.
- JSON bodies are bounded to 64 KiB; original uploads to 8 MiB. Bounded per-process
  rate limits return RFC 9457 HTTP 429. Structured request logs include generated
  trace IDs, method/status/duration, not paths, queries, tokens or document text.
  Default API access logging is disabled.
- Public-source gateway blocks workspace/case/publication/auth routes. No AI service
  is deployed; source importers cannot assign findings or approve publication.
  Any future AI needs separate suggestion-only permissions and threat review.

## Residual risks and deployment gates

An administrator can rewrite a local DB and audit chain; internal hashing is not
an independent timestamp, signature or external anchor. PostgreSQL originals are
not S3 Object Lock. Host encryption/KMS, encrypted immutable offsite backups,
signed artifacts, external anchors and key rotation need operational provisioning
and independent validation. Legal erasure/retention requires an approved controller
process; no unaudited destructive erasure API is supplied.

Native Windows child processing has fewer OS controls than Linux. Use the tested
isolated worker before hostile uploads. Confinement is not a complete VM sandbox or
penetration-test result. ClamAV cannot prove safety/authenticity. OCR confidence is
an engine signal, not calibrated factual probability; low-confidence quotations
require a human page-image comparison.

Full target capacity/availability, distributed WAF/rate limiting, centralized
alerts, offsite recovery/PITR, package/image supply-chain attestations and independent
adversarial testing are not certified by bounded CI. Continue advisory scans;
selected SQL/subprocess scan exclusions concern fixed allowlisted identifiers and
argument arrays, not broad vulnerability suppression.

See [FR status](FR_STATUS.md), [operations](OPERATIONS.md) and [production gates](PRODUCTION_GATES.md).
Production, confidential-source and hostile multi-tenant operation remain **NO-GO**.

The added public finance/property batches are available only to eligible
authenticated project research roles. They are project-wide source records,
while admission/changes to a case still require membership. No party names or
full property address table is fetched from NYC/HMLR. LEI is not a banking licence
or beneficial-owner determination. Broker output is explicitly labelled IEX and,
for app captures, connector-normalized. Keys stay in operator environment and
never enter request hashes/URLs, originals or browser configuration. HTTP-client
URL INFO logs are suppressed. Public gateway and public-source exports exclude
the new source routes/batches; case publication still needs exact content review.
