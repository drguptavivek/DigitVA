"""``c7a3f9e1b5d2`` flips only the web_intake_mode server default to 'direct'.

digitva-7amd.25. The suite builds its schema with ``create_all()``, so this
builds a throwaway database at the previous head, inserts projects with an
explicit mode and one relying on the old default, upgrades, and checks that no
row changed while a new insert now gets 'direct'; downgrade restores 'off'.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_web_intake_mode_default_direct.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DB_NAME = "minerva_test_intake_mode_default"

PREVIOUS_HEAD = "b4e7c2a9d6f3"
REVISION = "c7a3f9e1b5d2"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class ModeDefaultConfig(TestConfig):
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


class WebIntakeModeDefaultTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def _migrate(self, db, step, revision):
        # Alembic's env drops the pooled connections; start from a clean one.
        db.session.remove()
        step(revision=revision)
        db.session.remove()
        db.engine.dispose()

    def _insert(self, db, project_id, mode=None):
        columns = "project_id, project_name, project_nickname, project_status, "
        values = ":p, :p, :p, 'active', "
        if mode is not None:
            columns += "web_intake_mode, "
            values += ":m, "
        db.session.execute(
            sa.text(
                f"INSERT INTO va_project_master ({columns}project_registered_at, "
                f"project_updated_at) VALUES ({values}now(), now())"
            ),
            {"p": project_id, "m": mode},
        )
        db.session.commit()

    def _modes(self, db):
        return dict(
            db.session.execute(
                sa.text("SELECT project_id, web_intake_mode FROM va_project_master")
            ).all()
        )

    def _column_default(self, db):
        return db.session.execute(
            sa.text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'va_project_master' "
                "AND column_name = 'web_intake_mode'"
            )
        ).scalar_one()

    def test_upgrade_changes_only_the_default_and_downgrade_restores_it(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(ModeDefaultConfig)
            with app.app_context():
                self._migrate(db, alembic_upgrade, PREVIOUS_HEAD)
                self.assertIn("'off'", self._column_default(db))
                self._insert(db, "MDOLD1")  # relies on the old default: off
                self._insert(db, "MDBTH1", "both")
                before = self._modes(db)
                self.assertEqual(before, {"MDOLD1": "off", "MDBTH1": "both"})

                self._migrate(db, alembic_upgrade, REVISION)
                self.assertIn("'direct'", self._column_default(db))
                self.assertEqual(self._modes(db), before)  # rows untouched
                self._insert(db, "MDNEW1")
                self.assertEqual(self._modes(db)["MDNEW1"], "direct")

                self._migrate(db, alembic_downgrade, PREVIOUS_HEAD)
                self.assertIn("'off'", self._column_default(db))
                self.assertEqual(self._modes(db)["MDNEW1"], "direct")  # rows untouched
                self._insert(db, "MDOLD2")
                self.assertEqual(self._modes(db)["MDOLD2"], "off")
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
