# Operations and recovery

## Supported deployment

Docker Compose is suitable for isolated development and an operator-controlled pilot.
Bind address is `127.0.0.1:8000`; the database is not published. Configure HTTPS,
identity provider, firewall, alerting, and a dedicated production host before public access.

## Initialization

- Fill `.env` with two distinct random passwords (24+ characters, preferably 32 random bytes).
  Compose reads single-quoted values literally, including `$`. Passwords with URL
  reserved characters are assembled into a database URL safely by the application.
- `docker compose up --build -d`, then query `/readyz`.
- Use `docker compose run --rm api python -m app.seed_worldbank --country PRT --indicator SP.POP.TOTL --start 2022 --end 2024` to fetch **real** records at runtime.
- Confirm `/v1/public/observations` returns data with a source URL and digest.

The schema initialization shell executes only for **new PostgreSQL data volumes**.
Do not delete existing volumes to apply updates. Production requires migration tooling,
backup-before-migration and rollback rehearsal.

The bootstrap uses a single transaction and rejects example, short or identical
passwords. If first initialization fails, PostgreSQL may retain its initialized
data directory without the schema. Keep that volume for diagnosis and select a
**new Compose project/volume**, or repair it under administrator control.
`/readyz` verifies schema v2, project binding, restricted runtime role and forced RLS.
It returns 503 for the original schema; no automatic data migration occurs.

OIDC access tokens require the configured `iss`, `aud`, unexpired `exp`, nonempty
stable `sub`, configured UUID in `project_id`, and a JSON list in `roles` containing
`ingestor`, `analyst` or `reviewer` as applicable. Issuer and JWKS URLs require HTTPS.
Configure and validate these mappings at your real identity provider; no issuer,
MFA setup or development authentication bypass is bundled.

## Backup and restore

This starter does not include automated immutable backups. Example for a controlled
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
and audit gaps. A dedicated observability stack is not yet provisioned.
