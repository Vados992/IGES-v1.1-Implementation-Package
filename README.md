# IGES v1.1 — Implementation Package (controlled pilot)

Independent Geopolitical Evidence System. Evidence-centric research into public international financing and political claims. **No model-produced assessment is a finding of political control or wrongdoing.**

## Current state

This repository contains an **executable, single-project controlled pilot**, not a certified public investigation platform. Initial real-data integration: World Bank Indicators API v2. Records are retained with raw response bytes, SHA-256 digests, API retrieval URLs, timestamps, and precise observation locators. No real records are fabricated or bundled.

Capabilities:
- PostgreSQL with row-level security (RLS), immutable evidence and financial event tables, ledger constraints, and an auditable change trail.
- Explicit provenance states; real source data remain *unreviewed* until independent verification.
- Public read-only economic observation API (no political findings), configurable OIDC-protected administrative API.
- Deterministic financial aggregate semantics and two-person separation for claim review.
- Optional command-line ingestion using the real World Bank API.
- Docker Compose, unit/security tests, CI workflow, security and operations guides.

## Local startup

Requires Docker Compose v2. **Do not expose port 8000 publicly without TLS, an identity provider, production monitoring and legal review.**

```sh
cp .env.example .env
# Replace BOTH password placeholders with distinct strong passwords (24+ characters).
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/v1/public/observations
```

First run initializes a PostgreSQL database with a separate non-superuser `iges_runtime` role. Existing database volumes are not automatically reinitialized after configuration changes.

This audit introduces **schema version 2**. `/readyz` rejects the original unversioned
pilot schema. Preserve any existing volume and take an offline backup; do not run
`down -v` against working data. An in-place migration of a populated v1 pilot is
not supplied or certified. Use a separate Compose project and a fresh volume for
evaluation, and retain the old deployment for a reviewed data migration.
This branch includes all commits from `implementation/pilot-core-2026-10-20` and
targets `main`, which initially contained only this project's title.

## Fetch actual source records

```sh
docker compose run --rm api python -m app.seed_worldbank \
  --country PRT --indicator SP.POP.TOTL --start 2022 --end 2024
curl "http://127.0.0.1:8000/v1/public/observations?country=PRT&indicator=SP.POP.TOTL"
```

The command makes a **live** HTTPS request to the official World Bank V2 API and stores the original response and its hash. Network access is required at runtime. The retrieved data are marked `UNASSESSED`; they are facts *attributed to the source*, not independently verified truth. Data may have revisions and missing values.

Other allowlisted indicators: `NY.GDP.MKTP.CD` (GDP current US$) and `GC.DOD.TOTL.GD.ZS` (central government debt % GDP, where available). Indicator absence is reported rather than filled in.

## API

- `GET /healthz`, `GET /readyz`
- `GET /v1/public/observations?country=PRT&indicator=SP.POP.TOTL&limit=50`
- `GET /v1/public/observations/{id}/provenance`
- `POST /v1/admin/ingest/worldbank` (OIDC role `ingestor`)
- `POST /v1/admin/financial/events` (OIDC role `analyst`)
- `POST /v1/admin/claims` (OIDC role `analyst`)
- `POST /v1/admin/claims/{id}/reviews` (OIDC role `reviewer`)
- Interactive OpenAPI docs: `/docs`.

Admin APIs fail closed if issuer, audience or JWKS URL are not configured. There is **no development bypass** or hard-coded bearer token. Machine-origin ingestion via CLI is for trusted shell operators only.

## Test

```sh
python -m pip install -r requirements-dev.txt
pytest -q
ruff check app tests scripts
```

See `docs/SECURITY.md` and `docs/OPERATIONS.md` for limits, access architecture, threat scenarios, backup/recovery and outstanding production gates.

Without `IGES_TEST_ADMIN_URL`, PostgreSQL integration tests are explicitly skipped;
the CI Compose job executes them against a disposable real database. Unit fixtures
are artificial test inputs and are never shipped as source observations. Runtime
images install only `requirements.txt`; test and audit tools are separate.

Verify stored hashes and the audit sequence with:

```sh
docker compose exec -T api python -m app.verify_integrity
```

For a bounded live source check without database writes:
`python -m scripts.live_worldbank`. It saves raw bytes and a timestamped receipt
under ignored `work/live-worldbank/`, and exits unsuccessfully on upstream failure.
The manual GitHub Actions run additionally imports real data into its disposable
database; ordinary PR checks use explicit test fixtures and no upstream dependency.

**Not completed:** third-party security audit, GDPR/DPIA review, confidential-source vault, independent external timestamp anchoring, full causal-inference engine, bank-data integration, universal entity resolution, provider-backed infrastructure, benchmarked RPO/RTO, independent public accusation publication, production runbooks and incident drills. Those are deliberate NO-GO gates, not assumed protections.

Data source: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation
