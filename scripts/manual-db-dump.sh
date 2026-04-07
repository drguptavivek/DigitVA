#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
OUT_DIR="${1:-$HOME/dailybackups}"
DB_SERVICE="minerva_db_service"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env not found at $ENV_FILE"
  exit 1
fi

# Load POSTGRES_* vars from .env for dump command.
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${POSTGRES_USER:?POSTGRES_USER is missing in .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is missing in .env}"
: "${POSTGRES_DB:?POSTGRES_DB is missing in .env}"

mkdir -p "$OUT_DIR"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="pg_dump_${POSTGRES_DB}_${TS}.dump"
CONTAINER_TMP="/tmp/${DUMP_FILE}"
LOCAL_PATH="${OUT_DIR%/}/${DUMP_FILE}"

cd "$ROOT_DIR"

echo "==> Creating dump in container: $CONTAINER_TMP"
docker compose exec -T "$DB_SERVICE" sh -lc \
  "PGPASSWORD='$POSTGRES_PASSWORD' pg_dump -U '$POSTGRES_USER' -d '$POSTGRES_DB' -Fc -f '$CONTAINER_TMP'"

echo "==> Copying dump to host: $LOCAL_PATH"
docker compose cp "$DB_SERVICE:$CONTAINER_TMP" "$LOCAL_PATH"

echo "==> Cleaning container temp file"
docker compose exec -T "$DB_SERVICE" rm -f "$CONTAINER_TMP"

echo "Done"
ls -lh "$LOCAL_PATH"
