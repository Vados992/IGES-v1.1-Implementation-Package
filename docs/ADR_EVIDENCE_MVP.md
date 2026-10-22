# Evidence MVP implementation decisions

Status: executable controlled pilot, pending independent acceptance. The supplied
v1.0 specification is the requirements baseline; the choices below are deliberate
bounded substitutions, not claims that every suggested component was deployed.

## History and migration boundary

The implementation branch merges `main` at `d2b8734` with the hardened PR #1
baseline at `7a1caa9`, including deployment/MFA history from `ede76a2`. The merge
retains World Bank, USAspending, strict Decimal/null parsing, Windows setup,
OIDC/Keycloak, PostgreSQL/RLS and existing audit/financial histories. PR #1 and the
older unfinished cleanup checkout are preserved. There is no force push or merge
into main. PR #4 is the review vehicle.

Schema v2 remains a frozen bootstrap input; migrations 003/004/005 produce v5.
Fresh initialization is one transaction. Existing databases require a verified
backup and explicit administrator migration, with an advisory lock and version
checks. Unsupported unversioned/v1 installations fail for separate review. The
working Windows installation is not silently upgraded or reconfigured.

## System of record and ownership

| Record/control | System of record | IGES responsibility and limitation |
| --- | --- | --- |
| Population observations | World Bank official response | Preserve exact response, request/page locator and Decimal/null values; no independent truth or completeness claim |
| US federal award rows | USAspending official response | Preserve request/response hash and award semantics; do not recast obligations as bank payments |
| Documentary source publication | Original publisher | Catalogue provenance and retain unchanged bytes; no arbitrary URL fetch service, authenticity or copyright inference |
| Cases, claims, evidence, reviews, corrections | IGES PostgreSQL | Append-only records, scope, authorship, current-revision human gates and publication snapshots |
| Identity, MFA, global roles | Configured OIDC IdP/Keycloak | Verify signed claims and recent MFA; enforce case memberships/revocations in API; no owner enrollment by proxy |
| Legal/privacy approval | Named competent human/controller process | Record current-revision approval/veto and rationale; code cannot establish legal authority or GDPR compliance |
| Audit chain | IGES PostgreSQL, externally anchored later | Detect internal corruption and verify content linkage; no independent guarantee against host/DB administrator rewrite |
| Backups, encryption, keys, public hosting | Operator infrastructure | Repository provides runbooks and disposable restore tests; provisioning/independent validation remain gates |

## Storage, processing and API choices

1. **PostgreSQL originals instead of S3/Object Lock.** Unchanged `bytea` originals
   up to 8 MiB share atomic transactions, references, seals and backup semantics
   with metadata. Runtime cannot update/delete them. This does not provide WORM,
   host encryption, independent key custody or large-object capacity. Retain an
   object-store migration as future work with byte/hash comparison and no deletion.
2. **Durable PostgreSQL pending queue instead of RabbitMQ/Celery.** A separate
   worker uses advisory locks and append-only processing receipts; retry is explicit.
   Actual ClamAV must pass before extraction. Separate parser children, Linux OS
   limits and internal container networks reduce exposure. No external metadata
   URL is fetched by a parser. This is not a complete VM sandbox.
3. **Versioned transactional SQL instead of Alembic.** Administrator-owned schema
   version, explicit upgrades and real PostgreSQL repeat/preservation tests are
   implemented. No destructive down migration or automatic startup upgrade.
4. **FastAPI typed API and static RU/EN forms instead of a React SPA.** Forms use
   the generated OpenAPI schema. Browser Authorization Code + PKCE uses a separately
   approved public IdP client; bearer tokens stay in memory. A saved OpenAPI artifact
   supports review. No public gateway for private work is deployed.
5. **Project RLS plus API case authorization.** One project-bound runtime login
   prevents cross-project context changes. API checks both current signed role
   and unrevoked case membership. End users never receive runtime DB credentials.
   This architecture is not certified hostile multi-tenant isolation.
6. **Human findings only.** Importers create source facts with UNASSESSED status.
   Sources, hypotheses, evidence direction and scope are separate records. Exact
   quotations and translations remain distinct. No AI integration is supplied;
   future AI output must be suggestion-only and separately human-reviewed.

## Publication and data protection

Content edits append new revisions and invalidate substantive approvals. Reviewers
cannot assess material they authored. Conflicts cannot be declared away by an
administrator role. Legal/privacy gates record basis, minimisation, copyright,
retention and explicit public-content consent to the exact revision. Reply windows
require actual outreach evidence, or an explicit no-affected-party rationale.

Publication is disabled by default. A permitted editor still needs current human
gates. The canonical manifest includes scoped findings, source/quote/locator hashes,
methodology, review limitations, response disposition and deterministic CSV digest.
Private original bytes, full extracted pages and actor subjects are omitted. Source
and finding text can still contain personal information: competent review of the
whole public snapshot is mandatory. Corrections/retractions append a successor;
old versions remain marked and accessible. An approved legal erasure/retention
procedure and external cache handling are operational gaps, not an unaudited delete.

See the exact [FR ledger](FR_STATUS.md) and [NO-GO gates](PRODUCTION_GATES.md).
