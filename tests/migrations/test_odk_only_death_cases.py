"""``k8p4r2w6y3f1`` lets ODK-only cases exist (digitva-l8y3).

Builds a throwaway database at the previous head, upgrades, checks the source
CHECK, the partial unique index and the service account, then downgrades and
checks the old CHECK is back and the index is gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_odk_only_death_cases.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
DB_NAME = "minerva_test_odk_mig"

PREVIOUS_HEAD = "j7n3q9w5y2e8"
REVISION = "k8p4r2w6y3f1"
INDEX = "uq_va_death_register_odk_va_sid"
ACCOUNT_ID = "a906d0c7-cff9-43bf-ab59-cabaf703535a"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class OdkCasesConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(DB_NAME).render_as_string(hide_password=False)


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
        f"WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{DB_NAME}"',
    )


class OdkCasesMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_source_index_and_account_and_downgrade_removes_them(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        def scalar(sql, **params):
            return db.session.execute(sa.text(sql), params).scalar()

        def check_source():
            return scalar(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_va_death_register_source'"
            )

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(OdkCasesConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self.assertNotIn("odk", check_source())
                self.assertIsNone(scalar("SELECT 1 FROM va_users WHERE user_id = :id", id=ACCOUNT_ID))
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertIn("'odk'", check_source())
                self.assertIsNotNone(scalar(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = :n", n=INDEX
                ))
                self.assertIn("UNIQUE", scalar(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = :n", n=INDEX
                ))
                self.assertEqual(scalar(
                    "SELECT user_status::text FROM va_users WHERE user_id = :id", id=ACCOUNT_ID
                ), "deactive")
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertNotIn("odk", check_source())
                self.assertIsNone(scalar(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = :n", n=INDEX
                ))
                db.session.remove()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
