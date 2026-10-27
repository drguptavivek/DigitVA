"""``b4f8d2e6a1c3`` adds ``va_project_master.web_intake_equity_enabled``.

Builds a throwaway database from the migration chain, upgrades to the
revision, checks the column is NOT NULL with a ``false`` server default (a
bare insert gets ``false``), then downgrades one step and checks it is gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_web_intake_equity_enabled.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_equity_mig"
REVISION = "b4f8d2e6a1c3"
COLUMN = "web_intake_equity_enabled"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class EquityMigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(MIGRATION_DB_NAME).render_as_string(hide_password=False)


def _admin_execute(*statements):
    engine = sa.create_engine(_server_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for statement in statements:
                conn.execute(sa.text(statement))
    finally:
        engine.dispose()


def _drop_database():
    _admin_execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{MIGRATION_DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"',
    )


def _columns(db):
    return {c["name"]: c for c in sa.inspect(db.engine).get_columns("va_project_master")}


class EquityEnabledMigrationTest(unittest.TestCase):
    def test_upgrade_adds_a_false_default_column_and_downgrade_drops_it(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(EquityMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=REVISION)
                column = _columns(db)[COLUMN]
                self.assertFalse(column["nullable"])
                with db.engine.begin() as conn:
                    conn.execute(sa.text(
                        "INSERT INTO va_project_master (project_id, project_name, project_nickname,"
                        " project_status, project_registered_at, project_updated_at)"
                        " VALUES ('EQMIG1', 'Equity migration', 'EqMig', 'active', now(), now())"
                    ))
                    value = conn.execute(sa.text(
                        f"SELECT {COLUMN} FROM va_project_master WHERE project_id = 'EQMIG1'"
                    )).scalar_one()
                self.assertIs(value, False)
                db.session.remove()

                alembic_downgrade(revision="-1")
                self.assertNotIn(COLUMN, _columns(db))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
