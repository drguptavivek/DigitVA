#!/bin/sh
set -eu

exec gunicorn \
  --workers 1 \
  --worker-class gthread \
  --threads 6 \
  --bind :5001 \
  --timeout 30 \
  --no-control-socket \
  --access-logfile - \
  --access-logformat '%({x-forwarded-for}i)s %(m)s %(U)s %(s)s %(L)s' \
  --error-logfile - \
  public_doris_app:app
