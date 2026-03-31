#!/bin/bash
set -euo pipefail

echo "Waiting for Celery beat database dependencies..."

until psql "$DATABASE_URL" -tAc "SELECT 1" >/dev/null 2>&1; do
  echo "Database not ready for Celery beat, retrying in 2 seconds..."
  sleep 2
done

until psql "$DATABASE_URL" -tAc \
  "SELECT
     to_regclass('public.celery_intervalschedule') IS NOT NULL
     AND to_regclass('public.celery_periodictask') IS NOT NULL
     AND to_regclass('public.celery_periodictaskchanged') IS NOT NULL" | grep -q '^t$'; do
  echo "Celery beat tables not ready, retrying in 2 seconds..."
  sleep 2
done

echo "Celery beat database dependencies are ready."

exec uv run celery -A make_celery:celery_app beat \
  --loglevel=info \
  -S sqlalchemy_celery_beat.schedulers:DatabaseScheduler
