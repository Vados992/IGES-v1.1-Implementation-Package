# IGES — controlled evidence-workflow MVP

An executable, single-project research workspace with actual World Bank and
USAspending adapters. Source-attributed records and human-reviewed conclusions
have different states. No source observations or substantive human approvals are
fabricated or bundled. This repository is **not production-certified**.

## What runs

- FastAPI/OpenAPI, PostgreSQL 16, forced project RLS and append-only runtime grants.
- Cases with revision history, scoped claims, falsifiable hypotheses, source
  catalogue, unchanged originals, page text, exact quotations, entities and
  evidenced relationships. Manual identity aliases can be undone without deletion.
- Assigned independent reviews, conflict declarations, irreversible withdrawal,
  revision-bound legal/privacy veto and right-of-reply gates.
- Immutable versioned publication manifests, corrections/retractions, public
  reader, reproducible JSON/CSV and SHA-256 verification.
- RU/EN analyst workspace, browser Authorization Code + PKCE, signed OIDC/MFA
  validation, per-case membership and revocation. Administrators cannot publish
  or change evidence merely by having an administrator role.
- Separate ClamAV/Tesseract/Poppler worker. Failed, pending and quarantined files
  cannot supply evidence or be downloaded through the original endpoint.
- Content seals tied to the existing verifiable audit chain; transactional
  idempotency receipts, optimistic revision checks and RFC 9457 errors.

Exact acceptance evidence and remaining limits: [FR-01–FR-16 status](docs/FR_STATUS.md).
Architecture choices: [MVP ADR](docs/ADR_EVIDENCE_MVP.md).
Operator/reviewer workflow: [workspace guide](docs/WORKSPACE.md).

## Isolated startup

Use a new Compose project for evaluation; preserve all existing volumes.

```sh
cp .env.example .env
# Configure two distinct random passwords (24+ characters) and a project UUID.
# Configure your actual OIDC issuer/audience/JWKS and the public iges-web client.
docker compose -p iges-evidence-eval --profile intake up --build --wait
```

The API binds to `127.0.0.1:8000`; PostgreSQL and ClamAV have no published ports.
`/workspace` is the analyst UI; `/docs` and [saved OpenAPI](docs/openapi.json)
describe the API. Privileged requests fail closed without a configured IdP and
signed MFA claims. Browser SSO needs an approved HTTPS origin/redirect URI at
the IdP. Publication defaults to **disabled** (`IGES_ENABLE_PUBLICATION=false`).
Enabling that operator switch never bypasses current-revision human gates.

For the existing native installation and personal enrollment boundary, see
[Windows pilot](docs/WINDOWS_LOCAL_PILOT.md). Do not copy private state to a new
checkout. Its working database, accounts, certificates and keys are not changed
by this branch. Windows OCR needs separately installed trusted tools/scanner;
the Compose intake profile provides the tested processing environment.

## Upgrade existing data

Fresh bootstrap applies schema **v5** in one transaction. Normal application
startup does not migrate. After a verified backup, an administrator can inspect
and explicitly apply the transactional v2/v3/v4 → v5 migrations:

```sh
# Set IGES_MIGRATION_DATABASE_URL privately with administration credentials.
python -m app.migrate
python -m app.migrate --apply
# Run with the restricted runtime configuration after migration:
python -m app.verify_integrity
```

Original bytes, existing financial records, identities/project bindings and audit
history are preserved. Unversioned/v1 installations require a separately reviewed
migration. Never delete a working volume to upgrade. See [operations](docs/OPERATIONS.md).

## Actual official data

```sh
docker compose -p iges-evidence-eval run --rm api python -m app.seed_worldbank \
  --country PRT --indicator SP.POP.TOTL --start 2022 --end 2024
docker compose -p iges-evidence-eval run --rm api python -m app.seed_usaspending \
  --fiscal-year 2025 --limit 5
docker compose -p iges-evidence-eval exec -T api python -m app.verify_integrity
```

These commands require actual upstream access and fail visibly without it. They
store exact responses, request digests and locators. Missing monetary/statistical
values stay null. Award amounts never become assumed cash payments. Imports are
bounded pages, not exhaustive datasets; all source records remain `UNASSESSED`.

## Verification

```sh
python -m pip install -r requirements-dev.txt
ruff check app tests scripts
pytest -q
bandit -r app
pip-audit -r requirements.txt
```

Without `IGES_TEST_ADMIN_URL`, integration tests explicitly skip. CI executes real
PostgreSQL integration/migration/restore tests, live World Bank/USAspending imports,
actual RFC Editor PDF + image OCR + EICAR quarantine, and actual isolated Keycloak
password/OTP/PKCE checks for desktop and web clients. Test identities and approval
fixtures exist only in disposable test environments. The guarded UI harness is
not part of application authentication or the container's runtime entry point.

The optional public-data gateway blocks the workspace, private case routes,
authentication configuration and publication routes. Its default scope remains
public-source observations/awards only; see [public pilot deployment](docs/PUBLIC_PILOT_DEPLOYMENT.md).

External legal/privacy review, independent security assessment, protected hosting,
encrypted storage/backups and key custody, external audit anchors, measured recovery,
real reviewer enrollment and operational pilot acceptance remain explicit
[NO-GO gates](docs/PRODUCTION_GATES.md).
