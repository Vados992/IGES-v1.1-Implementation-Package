#!/bin/sh
set -eu
: "${IGES_DB_PASSWORD:?IGES_DB_PASSWORD must be set}"
: "${IGES_PUBLIC_PROJECT_ID:?IGES_PUBLIC_PROJECT_ID must be set}"
psql --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
  --set=ON_ERROR_STOP=1 \
  --set=runtime_password="${IGES_DB_PASSWORD}" \
  --set=project_id="${IGES_PUBLIC_PROJECT_ID}" \
  --file /docker-entrypoint-initdb.d/01_schema.sql
