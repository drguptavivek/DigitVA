#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
DB_SERVICE="minerva_db_service"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/manual-db-restore.sh <dump_file> [--yes]
  ./scripts/manual-db-restore.sh --from-s3 <object_key> [--yes]

Examples:
  ./scripts/manual-db-restore.sh ~/dailybackups/pg_dump_minerva_20260407T220000Z.dump
  ./scripts/manual-db-restore.sh ./dailybackups/pg_dump_minerva_20260407T220000Z.dump --yes
  ./scripts/manual-db-restore.sh --from-s3 db-backups/minerva/pg_dump_minerva_20260407T220000Z.dump

Notes:
  - Reads POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB from .env
  - This operation is destructive: it drops and recreates POSTGRES_DB
  - Stop app-side containers before continuing, then restart them and run migrations after restore
  - --from-s3 downloads the dump with `flask backups db-download` first, which
    verifies its recorded sha256 and refuses a key DigitVA has no record of.
    List keys with `flask backups db-list`. The download needs
    minerva_app_service running; the rest of the restore is unchanged.
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

FROM_S3_KEY=""
DUMP_PATH=""
ASSUME_YES=""

if [ "${1:-}" = "--from-s3" ]; then
  if [ $# -lt 2 ] || [ $# -gt 3 ]; then
    usage
    exit 1
  fi
  FROM_S3_KEY="$2"
  ASSUME_YES="${3:-}"
else
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
  echo "WARNING: This will REPLACE database '$POSTGRES_DB' (the old one is kept renamed)."
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

if [ -n "$FROM_S3_KEY" ]; then
  # Downloaded before anything destructive happens, and while the app service is
  # still up: db-download verifies the recorded sha256 and exits non-zero on a
  # mismatch, so a corrupt object never reaches the drop/restore below.
  S3_TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/digitva-restore-XXXXXX")"
  trap 'rm -rf "$S3_TMP_DIR"' EXIT
  S3_BASE_NAME="$(basename "$FROM_S3_KEY")"
  DUMP_PATH="${S3_TMP_DIR%/}/${S3_BASE_NAME}"

  echo "==> Downloading dump from the object store: $FROM_S3_KEY"
  docker compose exec -T minerva_app_service \
    uv run flask backups db-download "$FROM_S3_KEY" "/tmp/${S3_BASE_NAME}"
  docker compose cp "minerva_app_service:/tmp/${S3_BASE_NAME}" "$DUMP_PATH"
  docker compose exec -T minerva_app_service rm -f "/tmp/${S3_BASE_NAME}"

  if [ ! -f "$DUMP_PATH" ]; then
    echo "ERROR: downloaded dump not found: $DUMP_PATH"
    exit 1
  fi
  BASE_NAME="$S3_BASE_NAME"
  CONTAINER_DUMP="/tmp/restore_${TS}_${BASE_NAME}"
fi

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

# Restore into a scratch database first, so a truncated or wrong dump fails
# here (--exit-on-error) with the live database untouched. Only then are the
# names swapped; the old database is kept renamed, never dropped by this script.
SCRATCH_DB="${POSTGRES_DB}_restore_${TS}"
OLD_DB="${POSTGRES_DB}_pre_restore_${TS}"
PSQL_ADMIN="PGPASSWORD='$POSTGRES_PASSWORD' psql -U '$POSTGRES_USER' -d postgres -v ON_ERROR_STOP=1"

echo "==> Restoring dump into scratch database: $SCRATCH_DB"
docker compose exec -T "$DB_SERVICE" sh -lc \
  "PGPASSWORD='$POSTGRES_PASSWORD' createdb -U '$POSTGRES_USER' '$SCRATCH_DB'"
if ! docker compose exec -T "$DB_SERVICE" sh -lc \
  "PGPASSWORD='$POSTGRES_PASSWORD' pg_restore -U '$POSTGRES_USER' -d '$SCRATCH_DB' --no-owner --no-privileges --exit-on-error '$CONTAINER_DUMP'"; then
  docker compose exec -T "$DB_SERVICE" sh -lc \
    "PGPASSWORD='$POSTGRES_PASSWORD' dropdb -U '$POSTGRES_USER' --if-exists '$SCRATCH_DB'; rm -f '$CONTAINER_DUMP'" || true
  echo "ERROR: the dump did not restore cleanly. '$POSTGRES_DB' was not touched."
  exit 1
fi

echo "==> Swapping: '$POSTGRES_DB' -> '$OLD_DB', '$SCRATCH_DB' -> '$POSTGRES_DB'"
# The rename fails while anything is connected, and the earlier connection check
# can be stale by now (a container restarting, a stray client). Stop new
# connections, terminate the rest, rename; reopen the old database afterwards.
if ! docker compose exec -T "$DB_SERVICE" sh -lc \
  "$PSQL_ADMIN \
    -c 'ALTER DATABASE \"$POSTGRES_DB\" ALLOW_CONNECTIONS false' \
    -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB' AND pid <> pg_backend_pid()\" \
    -c 'ALTER DATABASE \"$POSTGRES_DB\" RENAME TO \"$OLD_DB\"' \
    -c 'ALTER DATABASE \"$SCRATCH_DB\" RENAME TO \"$POSTGRES_DB\"' \
    -c 'ALTER DATABASE \"$OLD_DB\" ALLOW_CONNECTIONS true'"; then
  docker compose exec -T "$DB_SERVICE" sh -lc \
    "$PSQL_ADMIN -c 'ALTER DATABASE \"$POSTGRES_DB\" ALLOW_CONNECTIONS true'; \
     PGPASSWORD='$POSTGRES_PASSWORD' dropdb -U '$POSTGRES_USER' --if-exists '$SCRATCH_DB'; rm -f '$CONTAINER_DUMP'" || true
  echo "ERROR: the swap failed. '$POSTGRES_DB' is unchanged and the scratch database was dropped."
  exit 1
fi
echo "Previous database kept as '$OLD_DB'. Drop it once the restore is confirmed good:"
echo "  docker compose exec $DB_SERVICE dropdb -U $POSTGRES_USER $OLD_DB"

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
