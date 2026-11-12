#!/bin/bash
set -euo pipefail

# Wait for DB and run migrations
echo "Waiting for database to be ready..."
# An image older than the database fails with "Can't locate revision": that is
# permanent, so stop instead of looping (rollback runbook: release-process.md).
until out=$(flask db upgrade 2>&1); do
  echo "$out"
  if grep -q "Can't locate revision" <<<"$out"; then
    echo "FATAL: the database is at a migration this image does not contain; retrying cannot help. Deploy an image that has it, or restore the pre-deploy backup." >&2
    exit 1
  fi
  echo "DB not ready, retrying in 5 secs..."
  sleep 5
done
echo "$out"

# Bootstrap missing documented questionnaire translations before serving traffic.
# This command is intentionally outside the migration loop: a missing or
# corrupt workbook must fail startup visibly rather than retry forever.
echo "Bootstrapping missing questionnaire translation sources..."
flask instrument-translations import-missing-sources

# GUNICORN_WORKERS (default 1); threads, TLS and the rest come through
# GUNICORN_CMD_ARGS, which gunicorn reads itself. --preload imports the app
# once in the master so the workers share those pages copy-on-write; each
# worker drops the inherited DB pool after fork (app/__init__.py).
exec gunicorn -c gunicorn_app.conf.py --preload -w "${GUNICORN_WORKERS:-1}" -b :5000 --access-logfile - --error-logfile - run:app
