#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
DB_SERVICE="minerva_db_service"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/manual-db-restore.sh <dump_file> [--yes]

Examples:
  ./scripts/manual-db-restore.sh ~/dailybackups/pg_dump_minerva_20260407T220000Z.dump
  ./scripts/manual-db-restore.sh ./dailybackups/pg_dump_minerva_20260407T220000Z.dump --yes

Notes:
  - Reads POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB from .env
  - This operation is destructive: it drops and recreates POSTGRES_DB
  - Stop app-side containers before continuing, then restart them and run migrations after restore
EOF
}

print_stop_commands() {
  cat <<'EOF'
Stop application containers before restore:
  docker compose stop minerva_app_service minerva_celery_worker minerva_celery_beat
EOF
}

print_resume_commands() {
  cat <<'EOF'
Start containers again after restore:
  docker compose up -d minerva_app_service minerva_celery_worker minerva_celery_beat

Apply migrations after restore:
  docker compose exec minerva_app_service uv run flask db upgrade
EOF
}

print_odk_pepper_notice() {
  cat <<'EOF'
ODK credential note:
  Restored ODK connection usernames/passwords remain encrypted from the source instance.
  If this environment uses a different ODK_CREDENTIAL_PEPPER than the source,
  ODK connection tests and sync will fail with "Credential decryption failed."

If the pepper differs, either:
  1. update this environment to use the original ODK_CREDENTIAL_PEPPER, or
  2. re-enter each ODK connection username/password in Admin so they are
     re-encrypted with this environment's pepper.
EOF
}

print_sequence_fix_commands() {
  local fixes="$1"
  cat <<EOF
Sequence alignment commands to run if you want to fix them now:
$fixes
EOF
}

confirm_containers_stopped() {
  echo
  print_stop_commands
  echo
  read -r -p "Press Enter after those containers are stopped to continue with the restore..."
}

check_active_connections() {
  docker compose exec -T "$DB_SERVICE" sh -lc \
    "PGPASSWORD='$POSTGRES_PASSWORD' psql -U '$POSTGRES_USER' -d postgres -Atc \
    \"SELECT count(*) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB';\""
}

check_sequence_alignment() {
  docker compose exec -T "$DB_SERVICE" sh -lc \
    "PGPASSWORD='$POSTGRES_PASSWORD' psql -U '$POSTGRES_USER' -d '$POSTGRES_DB' -At <<'SQL'
WITH sequence_map AS (
    SELECT
        ns.nspname AS table_schema,
        tbl.relname AS table_name,
        attr.attname AS column_name,
        seq_ns.nspname AS sequence_schema,
        seq.relname AS sequence_name,
        pg_get_serial_sequence(
            format('%I.%I', ns.nspname, tbl.relname),
            attr.attname
        ) AS sequence_fqname
    FROM pg_class tbl
    JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
    JOIN pg_attribute attr
      ON attr.attrelid = tbl.oid
     AND attr.attnum > 0
     AND NOT attr.attisdropped
    JOIN pg_depend dep
      ON dep.refobjid = tbl.oid
     AND dep.refobjsubid = attr.attnum
    JOIN pg_class seq
      ON seq.oid = dep.objid
     AND seq.relkind = 'S'
    JOIN pg_namespace seq_ns ON seq_ns.oid = seq.relnamespace
    WHERE tbl.relkind IN ('r', 'p')
      AND dep.classid = 'pg_class'::regclass
      AND dep.refclassid = 'pg_class'::regclass
      AND dep.deptype IN ('a', 'i')
      AND attr.atttypid IN (
          'smallint'::regtype,
          'integer'::regtype,
          'bigint'::regtype
      )
),
sequence_checks AS (
    SELECT
        format('%I.%I', table_schema, table_name) AS table_fqname,
        column_name,
        format('%I.%I', sequence_schema, sequence_name) AS sequence_fqname,
        COALESCE(
            (
                xpath(
                    '/row/max/text()',
                    query_to_xml(
                        format(
                            'SELECT max(%I) AS max FROM %I.%I',
                            column_name,
                            table_schema,
                            table_name
                        ),
                        false,
                        true,
                        ''
                    )
                )
            )[1]::text::bigint,
            0
        ) AS max_id,
        (
            SELECT last_value
            FROM pg_sequences
            WHERE schemaname = sequence_map.sequence_schema
              AND sequencename = sequence_map.sequence_name
        ) AS sequence_last_value
    FROM sequence_map
)
SELECT string_agg(
    format(
        'docker compose exec %s psql -U %s -d %s -c %L',
        '$DB_SERVICE',
        '$POSTGRES_USER',
        '$POSTGRES_DB',
        format(
            'SELECT setval(%L, %s, true);',
            sequence_fqname,
            GREATEST(max_id, 1)
        )
    ),
    E'\n'
)
FROM sequence_checks
WHERE sequence_last_value < max_id;
SQL"
}

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  usage
  exit 1
fi

DUMP_PATH="$1"
ASSUME_YES="${2:-}"

if [ ! -f "$DUMP_PATH" ]; then
  echo "ERROR: dump file not found: $DUMP_PATH"
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env not found at $ENV_FILE"
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${POSTGRES_USER:?POSTGRES_USER is missing in .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is missing in .env}"
: "${POSTGRES_DB:?POSTGRES_DB is missing in .env}"

if [ "$ASSUME_YES" != "--yes" ]; then
  echo "WARNING: This will DROP and RECREATE database '$POSTGRES_DB'."
  read -r -p "Type YES to continue: " CONFIRM
  if [ "$CONFIRM" != "YES" ]; then
    echo "Aborted."
    exit 1
  fi
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BASE_NAME="$(basename "$DUMP_PATH")"
CONTAINER_DUMP="/tmp/restore_${TS}_${BASE_NAME}"

cd "$ROOT_DIR"

confirm_containers_stopped

ACTIVE_CONNECTIONS="$(check_active_connections)"
if [ "$ACTIVE_CONNECTIONS" != "0" ]; then
  echo
  echo "ERROR: database '$POSTGRES_DB' still has $ACTIVE_CONNECTIONS active connection(s)."
  print_stop_commands
  echo
  echo "Stop the remaining clients, then rerun this restore."
  exit 1
fi

echo "==> Copying dump into container: $CONTAINER_DUMP"
docker compose cp "$DUMP_PATH" "$DB_SERVICE:$CONTAINER_DUMP"

echo "==> Dropping and recreating database: $POSTGRES_DB"
docker compose exec -T "$DB_SERVICE" sh -lc \
  "PGPASSWORD='$POSTGRES_PASSWORD' dropdb -U '$POSTGRES_USER' --if-exists '$POSTGRES_DB' && \
   PGPASSWORD='$POSTGRES_PASSWORD' createdb -U '$POSTGRES_USER' '$POSTGRES_DB'"

echo "==> Restoring dump into database: $POSTGRES_DB"
docker compose exec -T "$DB_SERVICE" sh -lc \
  "PGPASSWORD='$POSTGRES_PASSWORD' pg_restore -U '$POSTGRES_USER' -d '$POSTGRES_DB' --no-owner --no-privileges '$CONTAINER_DUMP'"

echo "==> Cleaning container temp file"
docker compose exec -T "$DB_SERVICE" rm -f "$CONTAINER_DUMP"

echo "==> Checking sequence alignment"
SEQUENCE_FIXES="$(check_sequence_alignment)"
if [ -n "$SEQUENCE_FIXES" ]; then
  echo "WARNING: one or more sequences are behind table data."
  print_sequence_fix_commands "$SEQUENCE_FIXES"
else
  echo "Sequence check OK: no lagging sequences detected."
fi
echo "Restore verification OK."

echo "Done"
echo "Restored: $DUMP_PATH -> $POSTGRES_DB"
echo
print_odk_pepper_notice
echo
print_resume_commands
