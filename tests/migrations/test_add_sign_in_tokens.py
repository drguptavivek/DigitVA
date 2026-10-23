"""``f3c8a1d5b7e2`` adds ``auth_sign_in_tokens`` and
``auth_devices.enrolled_via_sign_in_token`` (bead digitva-3g19).

Builds a throwaway database at the previous head, upgrades, checks the table,
the pending-per-user unique index and the new column, then downgrades and
checks they are gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_sign_in_tokens.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
DB_NAME = "minerva_test_sign_in_tokens_mig"

PREVIOUS_HEAD = "e7b2c4d8f1a3"
REVISION = "f3c8a1d5b7e2"
COLUMN = "enrolled_via_sign_in_token"
PENDING_INDEX = "ix_auth_sign_in_tokens_pending_user"
TABLE = "auth_sign_in_tokens"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class SignInTokensConfig(TestConfig):
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


class SignInTokensMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_and_downgrade_removes(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        def indexdef(name):
            return db.session.execute(
                sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": name}
            ).scalar()

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(SignInTokensConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                inspector = sa.inspect(db.engine)
                self.assertNotIn(TABLE, inspector.get_table_names())

                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                self.assertIn(TABLE, inspector.get_table_names())
                self.assertIn(COLUMN, {c["name"] for c in inspector.get_columns("auth_devices")})
                columns = {c["name"]: c for c in inspector.get_columns(TABLE)}
                self.assertFalse(columns["user_session_version"]["nullable"])
                self.assertIn("UNIQUE", indexdef(PENDING_INDEX))
                self.assertIn("redeemed_at IS NULL", indexdef(PENDING_INDEX))
                uniques = [u["column_names"] for u in inspector.get_unique_constraints(TABLE)]
                self.assertIn(["token_hash"], uniques)
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                inspector = sa.inspect(db.engine)
                self.assertNotIn(TABLE, inspector.get_table_names())
                self.assertNotIn(COLUMN, {c["name"] for c in inspector.get_columns("auth_devices")})
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()
