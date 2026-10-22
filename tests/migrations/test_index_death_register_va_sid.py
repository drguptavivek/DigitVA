"""``e2b7d4a9c6f1`` indexes ``va_death_register(va_sid)`` for the
area card's case-to-submission join (bead digitva-qfh8).

Builds a throwaway database at the previous head, upgrades, checks the index,
then downgrades and checks it is gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_index_death_register_va_sid.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
DB_NAME = "minerva_test_dr_va_sid_idx_mig"

PREVIOUS_HEAD = "c5e8a1f4b2d9"
REVISION = "e2b7d4a9c6f1"
INDEX = "ix_va_death_register_va_sid"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class DeathRegisterVaSidIndexConfig(TestConfig):
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


class DeathRegisterVaSidIndexMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_and_downgrade_removes(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        def indexdef():
            return db.session.execute(
                sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": INDEX}
            ).scalar()

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(DeathRegisterVaSidIndexConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self.assertIsNone(indexdef())
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertIn("va_death_register", indexdef())
                self.assertIn("(va_sid)", indexdef())
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertIsNone(indexdef())
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()
