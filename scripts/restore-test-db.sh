#!/bin/bash
# Restore test database, run migrations, and seed bootstrap data.
#
# Usage:
#   ./scripts/restore-test-db.sh
#
# Requires: docker compose stack to be up (at least minerva_db_service).

set -e

SQL_FILE="private/test_data.sql"
INITIAL_MIGRATION="a395774fa312"

if [ ! -f "$SQL_FILE" ]; then
  echo "ERROR: $SQL_FILE not found. Run from project root."
  exit 1
fi

echo "==> Resetting database schema..."
docker exec minerva_db psql -U minerva -d minerva \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

echo "==> Restoring test data..."
docker cp "$SQL_FILE" minerva_db:/tmp/test_data.sql
docker exec minerva_db psql -U minerva -d minerva -f /tmp/test_data.sql

# Read the alembic version that was restored from the SQL.
# If missing (SQL predates alembic tracking), stamp the initial migration
# so alembic knows which migrations to skip vs. apply.
RESTORED_VERSION=$(docker exec minerva_db psql -U minerva -d minerva -t -A \
  -c "SELECT version_num FROM alembic_version LIMIT 1;" 2>/dev/null || echo "")

if [ -z "$RESTORED_VERSION" ]; then
  echo "==> No alembic_version in SQL dump — stamping initial migration ($INITIAL_MIGRATION)..."
  docker compose exec minerva_app_service uv run flask db stamp "$INITIAL_MIGRATION"
else
  echo "==> Restored DB is at alembic version: $RESTORED_VERSION"
fi

echo "==> Running migrations..."
docker compose exec minerva_app_service uv run flask db upgrade

echo "==> Seeding bootstrap data..."
docker compose exec minerva_app_service uv run flask seed run

echo ""
echo "Done. Test DB is ready."
echo ""
echo "  Admin:  testadmin@digitva.com  /  Admin@123"
echo "  Coders: test.coder.{nc01,nc02,ka01,kl01,tr01}@gmail.com  /  Aiims@123"
