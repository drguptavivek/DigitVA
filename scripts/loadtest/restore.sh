#!/bin/bash
# Runs on the app host after a load test. REPLACES the database with the
# pre-test backup (single transaction: a failed restore rolls back), then
# migrates, purges the Celery queue and restarts. Staging only, owner's go.
# usage: restore.sh <backup key, e.g. db-backups/minerva/pg_dump_minerva_<ts>.dump>
KEY="${1:?usage: restore.sh <backup key>}"
U=$(docker inspect minerva_app --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^DATABASE_URL=' | cut -d= -f2-)
IMG=$(docker inspect minerva_app --format '{{.Config.Image}}')
docker exec minerva_app uv run --no-sync flask backups db-download "$KEY" /tmp/lt_restore.dump | tail -1 && docker cp minerva_app:/tmp/lt_restore.dump /tmp/lt_restore.dump && docker exec minerva_app rm -f /tmp/lt_restore.dump || exit 1
docker stop minerva_celery_beat minerva_celery_worker minerva_app >/dev/null && echo stopped
docker run --rm --volumes-from minerva_app --network digitva_default --entrypoint "" \
  -e DATABASE_URL="$U" -v /tmp/lt_restore.dump:/r.dump:ro "$IMG" \
  sh -c 'pg_restore -l /r.dump | grep -v " EXTENSION " > /tmp/l && grep -c EXTENSION /tmp/l; pg_restore -L /tmp/l --clean --if-exists --no-owner --no-privileges --single-transaction --exit-on-error -d "$DATABASE_URL" /r.dump' \
  && echo RESTORE_OK || echo RESTORE_FAILED_ROLLED_BACK
docker start minerva_app >/dev/null; sleep 15
docker exec minerva_app uv run --no-sync flask db upgrade 2>&1 | tail -1
docker exec minerva_app uv run --no-sync celery -A make_celery:celery_app purge -f 2>&1 | tail -1
docker start minerva_celery_worker minerva_celery_beat >/dev/null && echo started
docker exec -i minerva_app uv run --no-sync python - <<'PY' 2>&1 | tail -2
from app import create_app, db
import sqlalchemy as sa
with create_app().app_context():
    q=lambda s: db.session.execute(sa.text(s)).scalar()
    print("users", q("select count(*) from va_users"), "lt", q("select count(*) from va_users where email like 'lt+%'"), "rev", q("select version_num from alembic_version"))
PY
docker ps --format '{{.Names}} {{.Status}}' | grep minerva
rm -f /tmp/lt_restore.dump
