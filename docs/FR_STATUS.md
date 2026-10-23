# Specification v1.0 MVP: FR-01–FR-16 acceptance ledger

Scope: the supplied 27-page `IGES_Technical_Specification_v1_0_MVP_EN.pdf`,
sections 6 and 19. This ledger describes the implementation branch, not the
unchanged installed pilot or a production acceptance certificate.

**Implemented, bounded** means executable code and automated developer evidence
exist within the stated limits. It does not mean independent editorial, legal,
privacy or security acceptance. **Partial** identifies a remaining specification
gap. Test approvals and identities are explicitly synthetic control fixtures;
they are never represented as actual independent people or counsel approvals.

| FR | Priority | Status | Implementation and verification | Remaining boundary |
| --- | --- | --- | --- | --- |
| FR-01 Originals and formats | P0 | Implemented, bounded | Raw API upload, unchanged PostgreSQL bytes, durable intake queue; PDF, HTML, DOCX, CSV, JSON, images and bounded ZIP; parser format/security unit tests; actual RFC Editor PDF/image/EICAR pipeline in CI | 8 MiB originals; supported ZIP only, not arbitrary archive formats; no S3/Object Lock; Linux worker is the tested hostile-input boundary |
| FR-02 Integrity/provenance | P0 | Implemented, bounded | SHA-256, byte size, supplied and detected MIME, retrieval time, source, document version; re-verification and persistent mismatch incidents; seal/audit verifier; real official-source receipts | Hashes prove byte integrity, not authenticity, truth, copyright permission or independent timestamping |
| FR-03 Extraction/OCR | P0 | Implemented, bounded | Actual Poppler/Tesseract worker after ClamAV; per-page text/hash/method/locator/confidence; low-confidence review gate; real scanned image OCR CI | PDF/image physical pages; DOCX/text formats use explicitly labelled logical pages; no Office-layout rendering; manual original comparison remains human work; language packs bounded |
| FR-04 Cases/claims | P0 | Implemented, bounded | Required exact text, period, jurisdictions, scope and initial UNASSESSED state; append-only case amendments and superseding withdrawn claims; validation/lifecycle tests | No unrestricted in-place editing; amendments preserve prior versions |
| FR-05 Hypotheses | P0 | Implemented, bounded | Claim foreign key, expected observations and falsifiers required; a hypothesis is required before assessment | Text adequacy and falsifiability require a real reviewer |
| FR-06 Evidence | P0 | Implemented, bounded | Ready document, exact quote on specified page, direction, limitations and separate translation; cross-case/page/quote negatives and low-OCR checks tested | No claim of quote authenticity solely from OCR; visual original comparison is recorded by the reviewer |
| FR-07 Source catalogue | P0 | Implemented, bounded | Publisher, nullable author/date, language, primary/secondary/derivative role, independence group, URL and provenance basis; immutable records and references; separate derived-image/test-scanner source labels in CI | No inference of unknown dates/authors or automatic source-independence certification; source amendment UI is not supplied |
| FR-08 Entities/relationships | P0 | Implemented, bounded | Entity aliases/external IDs/identity basis; period-bound relationships require evidence; reversible manual alias resolution with cycle prevention, no destructive merge | Relationship status remains PROPOSED; not automatically a verified assertion. Identity judgements need people |
| FR-09 Transactions | P1 | Partial | Preserved Decimal/currency ledger, staged financial events, concurrent replay/refund/reversal constraints, actual USAspending awards with raw provenance | No complete case-level transaction editor linking payer/payee entities, type/date and evidence. Award obligations are not assumed cash payments; full currency-reference maintenance pending |
| FR-10 Search | P0 | Implemented, bounded | PostgreSQL full-text search on page text, scoped claims and entities; page/fragment/locator results; integration and real PDF search CI | `simple` dictionary and bounded cursor pages; no stemming/ranking quality or large-corpus capacity acceptance |
| FR-11 Independent review | P0 | Implemented, bounded | Assignment, current case+IdP reviewer role, author exclusion, explicit NO_CONFLICT, provenance/quote/countermaterial/limitations checks; changed findings require new evidence; disagreement requires independent panel disposition; terminal withdrawal | Independence/conflict statements are human attestations. Fixture reviewers demonstrate enforcement, not real independent acceptance |
| FR-12 Party responses | P1 | Partial | Evidence-linked response text, recorded outreach evidence, minimum 14-day reply window and disposition; current response/reply gate included alongside publication | No external mail/contact integration or authenticated public respondent portal; respondent cannot independently upload originals with respondent role alone; analyst-assisted intake required |
| FR-13 Exports | P1 | Implemented, bounded | Canonical publication JSON and sorted UTF-8/LF claims CSV; manifest SHA-256, CSV digest and spreadsheet formula protection; reproducibility tests | Exports cover approved publication snapshot and claims CSV, not a full private workspace backup or all collections as CSV |
| FR-14 Visualisation | P1 | Partial | RU/EN entity/relationship/source lists, evidence IDs and page-text/original controls in analyst UI; public reader and version history | Interactive graph canvas, evidence-click graph exploration, full timeline and transaction visualisation are not implemented |
| FR-15 Publication | P0 | Implemented, bounded | Operator switch off by default; current-revision independent review, legal/privacy approval/veto, reply and disputed-case panel gates; immutable canonical manifest, methodology/version/hash and public reader | No actual counsel approval or independently reviewed substantive case is claimed; external public gateway intentionally blocks publication/workspace routes |
| FR-16 Correction/retraction | P0 | Implemented, bounded | A new CORRECTED/WITHDRAWN version must supersede the latest version; old manifests remain retrievable and history marks successors; API/integration tests | No automated notification/subscription or external cache purge; legal takedown/retention requires an approved operational process |

## Cross-cutting acceptance

- Schema v6: transactional fresh bootstrap, explicit administrator-only v2/v3/v4/v5
  upgrade, repeat-safe migration and preserved original evidence/audit tested.
  Normal startup checks schema/project/role/RLS/grants and fails closed on drift.
- Authorization: signed OIDC/MFA plus current case memberships/revocations; no
  administrator evidence/publication bypass. The DB runtime is project-bound;
  individual-subject case ABAC is enforced at the API, not by distinct DB logins.
- Audit: canonical payload chain, content seals and case revision linkage;
  verifier detects changed/unsealed records and mismatched originals/manifests.
  No external anchor or protection from a DB/host administrator rewriting history.
- Writes: transactional idempotency and collision detection, If-Match revision
  checks, bounded bodies/rate limits, RFC 9457 errors with generated request IDs.
- Interface: RU/EN resources, analyst/reviewer/counsel/editor forms, original
  download/page text, browser SSO + PKCE. No AI service or automated factual verdict.

## Evidence and its limits

Verified CI baseline: [seven passing jobs at 83bd9a1](https://github.com/Vados992/IGES-v1.1-Implementation-Package/actions/runs/39813085729).
The current PR's checks must pass at its **current head** before review/merge;
an earlier green run does not certify later edits.

- Native isolated PostgreSQL run: 120 tests passed (104 unit, 16 integration),
  migration repeat/integrity checks; the existing Windows pilot was not changed.
- CI: Python 3.11/3.12 lint/unit; PostgreSQL RLS/API/concurrency/migrations/restart/
  dump+restore; dependency audit and Bandit; real source and intake jobs; real
  disposable Keycloak desktop/web password+OTP+PKCE/signature/audience checks.
- Live source job: three World Bank PRT population observations (2022–2024) and
  five USAspending FY2025 award rows; bounded imports, no synthetic fallback.
- Intake job: actual [RFC 9457 PDF](https://www.rfc-editor.org/rfc/rfc9457.pdf),
  214,288 bytes, SHA-256 `9e556f5dcbf7dd780928cfe03ec7f2080a635e1bcb41ddbeecbe8141c67d09ed`,
  16 physical pages; image derived from that PDF labelled separately; EICAR is a
  clearly labelled scanner-control fixture, never factual evidence.
- Browser check: actual RU/EN forms created an explicitly test-authenticated case
  and UNASSESSED documentary claim in a separate disposable PostgreSQL cluster.
  This was UI verification, not a real human review or owner MFA enrollment.

Full-scale latency, target corpus capacity, RPO/RTO, offsite recovery, independent
penetration testing, real editorial acceptance and legal/privacy authority remain
unverified. See [production gates](PRODUCTION_GATES.md), [security](SECURITY.md)
and [implementation decisions](ADR_EVIDENCE_MVP.md).

The subsequent [finance/property expansion](FINANCE_PROPERTY_SOURCES.md) adds
20 profiles across 10 providers, preserving the original two adapters. This adds
source records and source-to-case admission; it does not close FR-09's complete
transaction workflow, FR-12's respondent delivery or FR-14's graph/timeline gaps.
Current-head source tests and live CI supplement the historical baseline above;
actual account data or independent human/legal acceptance are still not claimed.
