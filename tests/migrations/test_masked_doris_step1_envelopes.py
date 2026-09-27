"""Migration coverage for the masked DORIS Step 1 envelope columns
(digitva-0n3 phase 2)."""

import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DATABASE = "minerva_test_masked_doris_step1"
PARENT = "a3f7c1d8e5b2"
REVISION = "b8e2d4f6a1c3"
TABLES = ("va_initial_assessments", "va_reviewer_initial_assessments")
COLUMNS = {
    "doris_certificate",
    "doris_result",
    "codedit_result",
    "cod_entry_mode_snapshot",
}


def _url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class MaskedDorisStep1MigrationConfig(TestConfig):
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


class MaskedDorisStep1EnvelopesMigrationTest(unittest.TestCase):
    def test_upgrade_adds_nullable_jsonb_and_downgrade_drops_them(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin(f'CREATE DATABASE "{DATABASE}"')
        try:
            app = create_app_without_celery_takeover(MaskedDorisStep1MigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PARENT)
                for table in TABLES:
                    self.assertIn("va_immediate_cod", _columns(db, table))
                    self.assertFalse(COLUMNS & set(_columns(db, table)))
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                for table in TABLES:
                    columns = _columns(db, table)
                    for column in COLUMNS:
                        self.assertEqual(columns[column], ("jsonb", "YES"), (table, column))
                db.session.remove()

                alembic_downgrade(revision=PARENT)
                for table in TABLES:
                    columns = _columns(db, table)
                    self.assertIn("va_immediate_cod", columns)
                    self.assertFalse(COLUMNS & set(columns))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
