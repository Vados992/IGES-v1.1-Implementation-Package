# Public banking, market and property sources

Scope agreed with the owner: US, EU and UK; **public data first**. No customer
bank/broker accounts, private transfers, balances, order entry or account consent
are connected. Existing World Bank/USAspending adapters remain intact.

## Executable catalogue

The catalogue has 20 dataset profiles across 10 additional providers. Each profile
constructs fixed HTTPS endpoints and validates typed/date/code parameters; callers
cannot submit URLs, SQL/SoQL/SPARQL, headers or secrets. Source response bytes and
canonical request hashes are retained alongside normalized records and locators.
All imported records remain UNASSESSED. No automated identity merge or conclusion.

| Provider / profiles | Actual data | Coverage and semantics |
| --- | --- | --- |
| [FDIC](https://api.fdic.gov/banks/docs): institutions, financials, failures | Institution directory; quarterly financials; failure/assistance history | US; ASSET/DEP/NETINC/COST retain USD-thousands units; COST is estimated resolution cost; inspect RESTYPE; not customer transfers |
| [ECB](https://data.ecb.europa.eu/help/api/data-examples): FX, deposit rate, mortgage volume/rate | Monthly euro reference exchange rates, change-date policy rates, MFI housing-loan aggregates | FX currency-per-EUR; mortgage units/multipliers and source attributes preserved; no daily forward fill, executable quote or individual mortgage offer |
| [Bank of England](https://www.bankofengland.co.uk/boeapps/database/help.asp): IUDBEDR | Official published Bank Rate | UK, daily percent; missing dates are not zero |
| [US Treasury](https://fiscaldata.treasury.gov/api-documentation/): Debt to the Penny | Public debt stocks by date | USD stocks, not cash transfers or individual bank accounts |
| [CFTC](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm): six COT profiles | TFF, legacy and disaggregated reports; futures-only and combined futures/options | Aggregate positions by trader category/market/week; no named broker/customer holdings; combined option positions are futures-equivalent; shared lineage |
| [Eurostat](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-introduction): quarterly HPI | Country-level total-purchase index | 2015=100; source-missing cells remain null with a separate missing-observation count; no property titles or sale amounts |
| [NYC DOF ACRIS](https://data.cityofnewyork.us/City-Government/ACRIS-Real-Property-Master/bnx9-e6tj): document master | Recorded property document metadata and stated amounts | NYC; amount can legitimately be zero or not a sale price. No party names or address table is requested; no current-ownership inference |
| [HM Land Registry](https://landregistry.data.gov.uk/app/root/doc/ppd): Price Paid | Actual transaction URI, price/date/type in a selected postcode | England/Wales only, index-based bounded postcode queries. No party names/full address requested. Not current title ownership or all UK sales; OGL attribution |
| [GLEIF](https://www.gleif.org/en/lei-data/gleif-api/): LEI | Legal names, jurisdiction/country, LEI registration/status | Filtered legal-entity reference records, not bank/broker permission or beneficial-ownership proof; no automatic name matching |
| [Alpaca](https://docs.alpaca.markets/docs/market-data): IEX daily bars | Actual public-market OHLCV/trade count/VWAP | IEX venue feed only, not consolidated volume or client trades. Two capture paths below; private research access and provider redistribution review required |

## Runtime and provenance

- Schema v6 adds append-only project-RLS `source_batches`/`source_records`; old
  original/audit histories are retained. Explicit v2/v3/v4/v5 → v6 migrations;
  normal startup does not migrate. Back up and rehearse before changing a working DB.
- Existing 2,000,000-byte source-evidence limit is preserved. Default page is 100;
  CFTC/GLEIF max 200; other paged APIs max 1000. Per-run bounds: 100 pages/50,000
  unique returned keys. ECB/BoE/Eurostat queries are single bounded period responses.
- A source page is atomic. Matching request+raw hash deduplicates. A changed raw
  response remains a separate vintage. Batch metadata hash is bound into the
  existing audit chain. The verifier reconstructs each request and normalized row
  from original bytes, checks units/locators/record hashes and missing/extra rows.
- CLI preserves successful pages on later failure. `FAILED`, `PARTIAL_FAILURE`,
  `BOUNDED`, `QUERY_EXHAUSTED` and `CONNECTOR_SLICE_ONLY` are explicit receipt states.
  Query exhaustion covers only that query/provider vintage, not an entire registry.
  Provider-index/golden-copy changes or duplicate keys during paging stop the run.
- NYC bulk validation exposed repeated document IDs. Adapter v2 uses Socrata's
  authoritative `:id` row key and stable tie ordering. Adapter v1 replay remains
  supported so earlier originals/receipts are preserved. Row counts and document
  counts differ; revised snapshots are never summed as new transactions.
- JSON numeric lexemes use Decimal and strings at the boundary. Null remains null;
  source-stated zero remains zero. Unit multipliers and distinct currency/obligation/
  position/index meanings are never silently converted or pooled.

## Alpaca access boundary

The connected app can capture `get_stock_bars` output. Preserve the **exact text
envelope** from that tool and import it with `--connector`; the parser verifies
tool, request symbols/dates/feed/timeframe/limit, record counts, timestamps and OHLC.
The stored transport is MCP_TOOL. It is connector-normalized data, not original
Alpaca HTTP bytes; adjustment metadata is explicitly unspecified. A tool packet's
hash does not authenticate its broker origin independently or prove completeness.
Import only trusted captured receipts and retain the operator's acquisition record.

The direct runtime adapter uses only `https://data.alpaca.markets/v2/stocks/bars`.
Set `IGES_ALPACA_DATA_KEY` and `IGES_ALPACA_DATA_SECRET` privately for that path;
never put them in query strings, receipts, Git or chat. No trading/account endpoint
is implemented. Without those credentials HTTP ingestion returns 503 explicitly.
No credential is extracted from the connected app or silently shared with the repo.
Current direct adapter supports a bounded first page, feed=iex, adjustment=raw;
a nonempty next-page token is reported as has_more rather than claiming coverage.

## Operator usage

```sh
python -m app.seed_external --dataset fdic_institutions --pages 20 --limit 500 --receipt work/fdic.json
python -m app.seed_external --dataset fdic_financials --param report_date=2026-06-30 --pages 20 --limit 500
python -m app.seed_external --dataset hmlr_ppd --param 'postcode=EC1V 3AP' --pages 3 --limit 100
python -m app.seed_external --dataset alpaca_stock_bars --param symbols=JPM,BAC,GS,MS,SCHW,BLK \
  --param start=2024-01-02 --param end=2024-01-10 --limit 100 --connector work/captured-alpaca-envelope.json
python -m app.verify_integrity
```

Commands use the operator's configured **target database**; do not point them at
a working installation without an approved backup/import plan. The reviewed
`scripts/data_plans/public_finance_property.json` records reproducible bounded
historical windows, not an automatic schedule or an exhaustive download promise.
`scripts/source_corpus.py` can create a separate clean source-only database inside
this task's guarded native test cluster. Test fixtures remain in another database;
no fake cases/reviews/approvals are inserted into the source corpus.

## API and analyst workflow

All `/v1/sources/*` endpoints require current signed OIDC/MFA and an eligible
project research role. Reads are project-wide public-source research access, not
case-membership access. Original downloads require ingestor/analyst/editor/reviewer/
counsel and are audited attachments. Ingestion needs ingestor and Idempotency-Key;
same intent replays the receipt and a changed payload conflicts. Pagination has
bounded limits and cursors. RFC 9457 failures never expose provider bodies or keys.

In `/workspace`, open **Financial and property datasets**, select a profile and
parameters, fetch a real page or browse saved batches. No credentials are entered
into that form. The metadata explains units, coverage and missing access. Select
an authorized case before **Admit original**. The API creates a source and unchanged
PENDING original, invalidates old content approvals and requires the existing real
scanner/extraction pipeline before evidence or original download. The analyst then
selects exact quotations/locators; normal independent/legal/privacy/reply gates apply.

The public-only gateway blocks `/v1/sources*`. New source originals/records are not
exposed as public exports or public dashboard rows, and `verify_integrity --export-dir`
continues exporting only the original World Bank/USAspending public snapshots.
If a reviewed case is published later, counsel must explicitly assess the entire
manifest for personal data, copyright, data terms and licences. Public accessibility
alone does not grant unrestricted redistribution or establish GDPR compliance.

## Verification and remaining scope

Local real-PostgreSQL suite: 152 tests at the initial source implementation,
including request binding, missing values, SSRF/query injection, redirect/media
denial, roles, idempotency, source-to-case admission, pending original denial,
append-only grants and raw-to-record tampering detection. Actual source probes
cover all 19 credential-free profiles. CI additionally re-runs those live queries
in its own fresh database and publishes only hash/count receipts. Inspect the
current commit's checks; local success is not a green-CI claim.

Closed account APIs, Open Banking consent, paid datasets, FINRA/FCA registered API
access, land-title/beneficial-owner restrictions, complete MLS listings and cadastral
coverage are not provided by these adapters. No inaccessible data is fabricated.
Production, confidential-source and hostile multi-tenant operation remain NO-GO;
external security/legal/privacy assessment, encrypted recovery and audit anchors
remain operator acceptance gates. FR-09/FR-12/FR-14 gaps in the evidence MVP remain.
