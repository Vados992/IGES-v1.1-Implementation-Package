# Operations and recovery — evidence MVP, schema v7

## Supported deployment

Docker Compose is suitable for isolated development and an operator-controlled pilot.
Bind address is `127.0.0.1:8000`; the database is not published. Configure HTTPS,
identity provider, firewall, alerting, and a dedicated production host before public access.

## Initialization

- Fill `.env` with two distinct random passwords (24+ characters, preferably 32 random bytes).
  Compose reads single-quoted values literally, including `$`. Passwords with URL
  reserved characters are assembled into a database URL safely by the application.
- `docker compose --profile intake up --build --wait`, then query `/readyz`.
  The intake profile supplies the actual scanner and OCR worker; API-only startup
  accepts originals into PENDING but does not scan/extract them.
- Use `docker compose run --rm api python -m app.seed_worldbank --country PRT --indicator SP.POP.TOTL --start 2022 --end 2024` to fetch **real** records at runtime.
- Confirm `/v1/public/observations` returns data with a source URL and digest.

The schema initialization shell executes only for **new PostgreSQL data volumes**.
Do not delete existing volumes to apply updates. Verify a backup first, inspect
`python -m app.migrate` with a privately supplied `IGES_MIGRATION_DATABASE_URL`,
then explicitly run `python -m app.migrate --apply` using administration credentials.
Only v2 through v6 to v7 is supported; unsupported old schemas stop for separate review.
Upgrades are transactional, advisory-locked and repeat-safe. Normal app startup
never migrates. Do not perform a destructive downgrade; restore a verified backup
to a new recovery database if an approved recovery is necessary.

The bootstrap uses a single transaction and rejects example, short or identical
passwords. If first initialization fails, PostgreSQL may retain its initialized
data directory without the schema. Keep that volume for diagnosis and select a
**new Compose project/volume**, or repair it under administrator control.
`/readyz` verifies schema v7, project binding, restricted runtime role, forced RLS
and protected-table append-only grants. It returns 503 for old/missing schemas.

OIDC access tokens require the configured `iss`, `aud`, unexpired `exp`, nonempty
stable `sub`, configured UUID in `project_id`, and a JSON list in `roles` containing
the route's required role. Issuer and JWKS URLs require HTTPS. Signed MFA and
recent auth_time are required by default. Configure actual users, issuer/mappers
and the browser client's exact HTTPS origin/redirect; see [workspace](WORKSPACE.md).
Fresh Windows setup and isolated CI supply Keycloak profiles; an existing operator
realm is not automatically changed. No normal API development-auth bypass exists.

## Processing and publication

Inspect PENDING/READY/FAILED/QUARANTINED in the case document list or pages endpoint.
Actual ClamAV must pass before extraction; preserve the original and processing
receipt when a parser/scanner fails. Update signatures, inspect the failure without
logging private content, then use the authenticated document retry endpoint if
appropriate. Do not edit a processing row, mark malware READY or disable scanning.
Use the isolated Linux worker for untrusted input; native Windows child processing
has fewer OS restrictions. Supported originals are limited to 8 MiB.

Run `docker compose exec -T api python -m app.verify_integrity` after migrations,
restores and controlled imports. A nonzero exit or integrity incident requires
preserving snapshots/receipts and investigation. Never rewrite a digest or audit
entry to make verification pass. Internal chain consistency is not an external
anchor; production requires a separately retained signed/timestamped checkpoint.

Publication is disabled by default. An operator can enable
`IGES_ENABLE_PUBLICATION=true` only for an approved controlled environment; current
independent review, legal/privacy and reply gates still apply. New content invalidates
substantive approvals. Do not reuse fixture approvals or claim an IdP test user is
an independent reviewer. The optional public-source gateway blocks private work
and publication routes; broader hosting requires a separate reviewed deployment.

## Backup and restore

This MVP does not include automated immutable backups. Example for a controlled
environment (keep dumps offline, encrypted, with verified access controls):

```sh
docker compose exec -T db pg_dump -U postgres -d iges -Fc -f /tmp/iges.dump
docker compose cp db:/tmp/iges.dump ./iges.dump
```

Restore to a newly created, isolated recovery database using `pg_restore` with
appropriate PostgreSQL administration credentials. Re-check RLS policies,
checksums, row counts and public API before deciding to fail over.

Use `docker compose cp` for binary dumps, especially from Windows PowerShell, to
avoid shell redirection changing binary bytes. Provision the `iges_runtime` role
with the intended secret on a new PostgreSQL cluster before restoring: `pg_dump`
contains database objects, not cluster roles/passwords. Revoke public CONNECT/TEMP
and grant runtime CONNECT on the restored database. Configure `IGES_DB_NAME` for
an isolated restored database and run `python -m app.verify_integrity`.
CI rehearses dump/restore on one disposable cluster; it does not demonstrate
offsite recovery, backup encryption, PITR or measured RPO/RTO.

For **production GO** build independent offsite encrypted backups + WAL archiving /
PITR, automate restore verification, test RPO <= 1 hour and RTO <= 4 hours.
Neither figure has yet been measured.

## Incident runbook (minimum)

1. Isolate the public API and freeze privileged writes.
2. Preserve logs, data snapshots, and source digests under chain-of-custody.
3. Rotate OIDC/client and database credentials if indicated.
4. Restore into isolated environment from independently verified backup.
5. Verify the audit chain, compare external anchors and validate all source references.
6. Release via documented dual approval; publish corrections where needed.

## Monitoring

Alert on: upstream data errors, repeated invalid tokens, DB readiness failures,
duplicate-idempotency conflicts, unexpected asset growth, anomalous review volume,
worker failures/quarantines, signature age and audit gaps. Request logs retain
generated request IDs/method/status/duration without paths/queries/body/token data.
A dedicated centralized observability stack and distributed rate limit are not
provisioned. The bounded CI read-load probe is not a full capacity/SLO acceptance.

See [FR status](FR_STATUS.md) and [production gates](PRODUCTION_GATES.md).

The [finance/property source catalogue](FINANCE_PROPERTY_SOURCES.md) documents
bounded ingestion, corpus receipts, paging failures, private research access and
market credentials. Source imports use project-level ingestor permission; admission
to a case additionally requires case membership. Preserve partial source pages;
resume with reviewed query/page parameters instead of deleting or replacing them.
HTTP-client INFO URL logging is suppressed; use request hashes and trace IDs.
