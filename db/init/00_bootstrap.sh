#!/bin/sh
set -eu
: "${IGES_DB_PASSWORD:?IGES_DB_PASSWORD must be set}"
: "${IGES_PUBLIC_PROJECT_ID:?IGES_PUBLIC_PROJECT_ID must be set}"
if [ "${#IGES_DB_PASSWORD}" -lt 24 ] || [ "${#POSTGRES_PASSWORD}" -lt 24 ] ||
   [ "$IGES_DB_PASSWORD" = "$POSTGRES_PASSWORD" ]; then
  echo 'Use distinct database passwords of at least 24 characters' >&2
  exit 1
fi
case "$IGES_DB_PASSWORD:$POSTGRES_PASSWORD" in
  *REPLACE_WITH*) echo 'Replace example passwords before initialization' >&2; exit 1 ;;
esac
psql --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
  --single-transaction \
  --set=ON_ERROR_STOP=1 \
  --set=runtime_password="${IGES_DB_PASSWORD}" \
  --set=project_id="${IGES_PUBLIC_PROJECT_ID}" \
  --file /docker-entrypoint-initdb.d/01_schema.template \
  --file /iges-migrations/003_award_provenance.sql \
  --file /iges-migrations/004_evidence_workflow.sql \
  --file /iges-migrations/005_workspace_revisions.sql \
  --file /iges-migrations/006_external_sources.sql
