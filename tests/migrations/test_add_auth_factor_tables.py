"""Migration coverage for the auth factor tables (digitva-sn1.1.2)."""

import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DATABASE = "minerva_test_auth_factor_tables"
PARENT = "b8e2d4f6a1c3"
REVISION = "c1d5e9a2f7b4"
NEW_TABLES = (
    "auth_webauthn_credentials",
    "auth_totp",
    "auth_recovery_codes",
    "auth_security_events",
)


def _url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class AuthFactorTablesMigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _url(DATABASE).render_as_string(hide_password=False)


def _admin(*statements):
    engine = sa.create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            for statement in statements:
                connection.execute(sa.text(statement))
    finally:
        engine.dispose()


def _drop_database():
    _admin(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{DATABASE}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{DATABASE}"',
    )


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def _columns(db, table):
    return {
        name: (data_type, nullable)
        for name, data_type, nullable in db.session.execute(
            sa.text(
                "SELECT column_name, data_type, is_nullable FROM "
                "information_schema.columns WHERE table_name = :table"
            ),
            {"table": table},
        ).all()
    }


class AuthFactorTablesMigrationTest(unittest.TestCase):
    def test_upgrade_adds_tables_and_column_and_downgrade_reverts(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin(f'CREATE DATABASE "{DATABASE}"')
        try:
            app = create_app_without_celery_takeover(AuthFactorTablesMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PARENT)
                tables = _table_names(db.engine)
                self.assertFalse(set(NEW_TABLES) & tables)
                self.assertNotIn("auth_session_version", _columns(db, "va_users"))
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                tables = _table_names(db.engine)
                for table in NEW_TABLES:
                    self.assertIn(table, tables)
                self.assertEqual(
                    _columns(db, "va_users")["auth_session_version"],
                    ("integer", "NO"),
                )
                credential_columns = _columns(db, "auth_webauthn_credentials")
                self.assertEqual(credential_columns["credential_id"][0], "bytea")
                self.assertEqual(credential_columns["sign_count"], ("bigint", "NO"))
                self.assertEqual(credential_columns["user_id"], ("uuid", "NO"))
                db.session.remove()

                alembic_downgrade(revision=PARENT)
                tables = _table_names(db.engine)
                self.assertFalse(set(NEW_TABLES) & tables)
                self.assertNotIn("auth_session_version", _columns(db, "va_users"))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
