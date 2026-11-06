"""``921a78710fbf`` adds ``mas_ui_locale`` and seeds Hindi published (digitva-s028).

Builds a throwaway database from the migration chain, upgrades to the revision,
checks the table, its check constraint and the seed row, then downgrades one
step and checks the table is gone. Steps back with ``-1`` so re-chaining the
revision onto another parent does not touch this test.
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_uilocale_mig"
REVISION = "921a78710fbf"
TABLE = "mas_ui_locale"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class UiLocaleMigrationConfig(TestConfig):
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


class UiLocaleMigrationTest(unittest.TestCase):
    def test_upgrade_creates_the_table_seeds_hindi_and_downgrade_drops_it(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(UiLocaleMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                self.assertIn(TABLE, inspector.get_table_names())
                columns = {c["name"] for c in inspector.get_columns(TABLE)}
                self.assertEqual(columns, {
                    "locale_code", "native_name", "bcp47_tag", "direction",
                    "is_published", "updated_by", "updated_at",
                })
                checks = {c["name"] for c in inspector.get_check_constraints(TABLE)}
                self.assertEqual(checks, {"ck_mas_ui_locale_direction"})
                rows = db.session.execute(sa.text(
                    "SELECT locale_code, bcp47_tag, direction, is_published FROM mas_ui_locale"
                )).all()
                self.assertEqual([tuple(r) for r in rows], [("hi", "hi-IN", "ltr", True)])
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(
                        "INSERT INTO mas_ui_locale (locale_code, native_name, bcp47_tag, direction) "
                        "VALUES ('ur', 'x', 'ur', 'up')"
                    ))
                db.session.rollback()
                db.session.remove()

                alembic_downgrade(revision="-1")
                self.assertNotIn(TABLE, sa.inspect(db.engine).get_table_names())
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
