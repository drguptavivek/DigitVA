#!/bin/bash
set -euo pipefail

# Wait for DB and run migrations
echo "Waiting for database to be ready..."
until flask db upgrade; do
  echo "DB not ready, retrying in 5 secs..."
  sleep 5
done

# Bootstrap missing documented questionnaire translations before serving traffic.
# This command is intentionally outside the migration loop: a missing or
# corrupt workbook must fail startup visibly rather than retry forever.
echo "Bootstrapping missing questionnaire translation sources..."
flask instrument-translations import-missing-sources

# GUNICORN_WORKERS (default 1); threads, TLS and the rest come through
# GUNICORN_CMD_ARGS, which gunicorn reads itself.
exec gunicorn -w "${GUNICORN_WORKERS:-1}" -b :5000 --access-logfile - --error-logfile - run:app
