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
EOF
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

echo "Done"
echo "Restored: $DUMP_PATH -> $POSTGRES_DB"
