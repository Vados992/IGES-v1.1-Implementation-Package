# Ukrainian public-office records, requested period 2014–2026

This is an executable, private research collection of real official published
records, not a complete dossier on all politicians or a financial/offence finding.
The requested end year is incomplete as of **2026-10-23**. The installed Windows
pilot is unchanged; actual data were inserted into a separate PostgreSQL corpus
inside the implementation checkout. No control fixtures, findings, approvals,
private accounts or synthetic observations were inserted into that corpus.

## Actual imported scope

| Official dataset | Source rows retained | What the records establish |
| --- | ---: | --- |
| Rada VII membership | 469 | Published membership overlapping 2014; 9 of the 478 source rows ended before 2014 and were excluded |
| Rada VIII membership | 467 | Published 2014–2019 convocation membership and supplied individual dates |
| Rada IX membership | 471 | Published IX membership history; six repeated card-ID rows preserved separately; these are not 471 unique people |
| Rada VII parliamentary posts | 4,671 | Posts/organizations by member card; no post date ranges; VII includes 2012–2014 and cannot be reduced to 2014 posts from this file alone |
| Rada VIII parliamentary posts | 3,538 | Published posts/organizations, without dated appointment history |
| Rada IX parliamentary posts | 3,929 | Published posts/organizations, without dated appointment history |
| CEC local election results, 2020 cycle | 43,343 | 41,947 deputy and 1,396 named head records, 25 regions and 1,575 councils; includes published repeat/by-elections |
| **Total Ukrainian records** | **56,888** | **Seven original-backed batches; records, not unique people or independently verified findings** |

CEC XML contains 1,419 head elements, of which **23 are empty** and not counted
as people. CEC row keys use source region/council/role/position: the source supplies
no persistent person ID. Matching names are never automatically linked.
Source spelling is preserved, including apparent typos. Correcting a source name
requires a separate attributed human record, not overwriting the original.

Primary catalogue/attribution:

- [Verkhovna Rada open-data catalogue](https://data.rada.gov.ua/open/data/mps).
  Publisher: Апарат Верховної Ради України. Fixed roster endpoints:
  `https://data.rada.gov.ua/ogd/mps/skl{7|8|9}/mps0{7|8|9}-data.json`.
  Posts: `.../skl{7|8|9}/mp-posts_full.csv`. Exact response bytes, hashes and
  JSON-array/CSV-row locators are retained.
- [CEC published election open data](https://www.cvk.gov.ua/pls/vm2020/pvm013pt001f01=695.html),
  [unchanged XML archive](https://www.cvk.gov.ua/pls/vm2020/opendata_obr.xml),
  [publisher XSD](https://www.cvk.gov.ua/pls/vm2020/opendata_obr_xsd.xml).
  Publisher: Центральна виборча комісія України; source attribution required.

## Financial declarations and explicit gaps

[NAZK's official public API documentation](https://public.nazk.gov.ua/public_api)
describes reporting years from **2015**, with 100-result pages and a 100-page cap.
The 2014 year is not supplied by this API. On 2026-10-23, twelve bounded requests
for 2015–2026, workplace `Верховна Рада`, page 1, each returned **HTTP 403**.
The database stores twelve availability receipts with exact URL, reporting year,
time, status and response checksum, bound to the audit chain. **Zero declaration
records were imported**. These are service-access probes, not evidence of empty
declarations or absence of assets. There is no bypass, synthetic replacement,
credential harvesting or unvalidated declaration parser.

| Requested years | Available collection | Unresolved coverage |
| --- | --- | --- |
| 2014 | VII/VIII parliamentary membership overlap | Full local mandates, cabinet/presidential/regional appointment history, financial declarations |
| 2015–2018 | VIII membership and undated parliamentary posts | NAZK access; full local/political executive history |
| 2019 | VIII/IX membership | Dated executive/regional transitions and local office changes |
| 2020–2022 | IX membership, CEC published election-cycle results | Later terminations/appointments; CEC result is not current office |
| 2023–2026 | Latest published IX membership/posts | Full current local/executive status, NAZK access, complete 2026 reporting |

The collection does not establish a universe of all national/local politicians,
all annual office holders, relatives, assets, beneficial ownership, bank transfers,
brokerage positions or criminal conduct. President, cabinet, regional appointments,
local 2014–2019 terms, resignations, deceased/replaced officials and subsequent
terminations need additional authoritative ingestion and reconciliation.

## Implementation and privacy boundaries

- Schema **v7**, explicit preserving migration 007, extends only fixed Ukrainian
  source profiles. Existing source providers retain their 2 MB bound; Rada fixed
  flat files have an 8 MB bound, the fixed CEC XML archive 32 MB/50,000-record bound.
  DTDs/entities/external XML references and unexpected schemas are rejected.
- Original Rada/CEC archives contain personal fields. Normalized search records
  exclude birth dates, residential locations, education, private employment and
  private party-membership fields. Professional public posts and election
  nomination bodies remain source-attributed. Purpose, lawful basis, retention,
  special-category handling and publication require independent legal/privacy review;
  this collection does not certify GDPR compliance.
- Original archive access requires **counsel**, is authenticated and audited.
  Whole-archive case admission is blocked: a separately minimized, attributed case
  document needs human privacy review through the existing case workflow. No full
  archive or personal-record export is put into Git or public CI artifacts.
- Source records remain **UNASSESSED**. No AI-generated name resolution,
  inferred political affiliation, inferred current office, accusation or risk score.
  Public publication still requires current-revision legal/privacy/human gates.
- `GET /v1/sources/ukraine/search` performs Unicode-casefolded, literal name search
  with bounded pagination. `%`/`_` cannot turn into arbitrary SQL wildcards.
  `GET /v1/sources/ukraine/coverage` exposes counts, availability receipts and gaps.
  RU/EN workspace: Public-source datasets → Ukraine. Full archive imports clearly
  state that page-size limits do not apply to fixed flat files.
- Source collection attempts are append-only, forced-RLS, hashed and audit-bound.
  The integrity verifier replays originals into every normalized record and locator,
  checks receipt bodies and confirms their audit references. Internal consistency
  is not an external timestamp, authenticity certificate or independent corroboration.

## Reproduction and validation

Use a separately configured evaluation database. Preserve originals and take a
backup before migration; normal API startup never migrates. Execute the seven-item
plan in `scripts/data_plans/ukraine_public_office.json` using `app.seed_external`
or the guarded local-corpus runner. `scripts.probe_nazk` records availability only.
`scripts.upgrade_source_corpus` refuses the installed pilot or a non-loopback DB
and makes a full PostgreSQL backup before its explicit migration.

Local acceptance: full real-PostgreSQL tests, migration rehearsals from v2/v5/v6,
schema/role/RLS, name search, XML attacks, duplicates, privacy/original denial,
availability tampering and exact transport retry. `live-ukraine` CI fetches the
seven real archives into a fresh PostgreSQL DB, verifies replay/search and records
NAZK availability separately. A green archive check does **not** mean NAZK data
were ingested. Only hashes/counts/scope are uploaded as CI artifacts.

The separate corpus now contains **124,561 snapshot records / 193 original-backed
batches**, including the earlier 67,673 financial/market/property records. Its
193 originals, 124,561 records, 12 availability receipts and 205 audit events
passed internal verification; no external anchoring is claimed. A local backup
preceded the v6→v7 migration and preserved all 186 prior originals.

External legal/security review, storage encryption/KMS, operational retention,
real reviewers and production acceptance remain mandatory outstanding work.
