"""``q7c2n5x9d4b8`` adds ``mas_ui_string_override.source`` (digitva-cqw9)."""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DB = "minerva_test_uis_src_mig"
REVISION = "q7c2n5x9d4b8"


def _url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class Cfg(TestConfig):
    SQLALCHEMY_DATABASE_URI = _url(DB).render_as_string(hide_password=False)


def _admin(*statements):
    engine = sa.create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for s in statements:
                conn.execute(sa.text(s))
    finally:
        engine.dispose()


def _drop():
    _admin(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{DB}' "
        "AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{DB}"',
    )


class SourceMigrationTest(unittest.TestCase):
    def test_existing_rows_become_edited_and_downgrade_guards_machine_rows(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop()
        _admin(f'CREATE DATABASE "{DB}"')
        try:
            app = create_app_without_celery_takeover(Cfg)
            with app.app_context():
                alembic_upgrade(revision="m4v8r2t6q1w9")
                db.session.execute(sa.text(
                    "INSERT INTO mas_ui_string_override (locale_code, string_key, text) "
                    "VALUES ('hi', 'a', 'x')"))
                db.session.commit()
                alembic_upgrade(revision=REVISION)
                self.assertEqual(
                    db.session.execute(sa.text("SELECT source FROM mas_ui_string_override")).scalar_one(),
                    "edited")
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(
                        "INSERT INTO mas_ui_string_override (locale_code, string_key, text, source) "
                        "VALUES ('hi', 'b', 'x', 'bogus')"))
                db.session.rollback()

                db.session.execute(sa.text(
                    "INSERT INTO mas_ui_string_override (locale_code, string_key, text, source) "
                    "VALUES ('hi', 'm', 'x', 'machine')"))
                db.session.commit()
                with self.assertRaises(SystemExit):  # flask_migrate exits on the guard
                    alembic_downgrade(revision="m4v8r2t6q1w9")
                db.session.remove()
                db.session.execute(sa.text("DELETE FROM mas_ui_string_override WHERE source = 'machine'"))
                db.session.commit()
                alembic_downgrade(revision="m4v8r2t6q1w9")
                cols = {c["name"] for c in sa.inspect(db.engine).get_columns("mas_ui_string_override")}
                self.assertNotIn("source", cols)
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop()


if __name__ == "__main__":
    unittest.main()
