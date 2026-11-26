"""``e7a4c2f9b1d3`` adds ``va_project_master.social_autopsy_collect_enabled``
(digitva-rglh).

Builds a throwaway database at the previous head with one project whose coder
Social Autopsy switch is on and one where it is off, upgrades (Collect equals
the coder switch on both, NOT NULL with a true default), downgrades (the
column is gone, the projects stay) and upgrades again.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_social_autopsy_collect_enabled.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_sa_collect_mig"

PREVIOUS_HEAD = "b5e2c8d4a9f7"
REVISION = "e7a4c2f9b1d3"

PROJECT_SQL = (
    "INSERT INTO va_project_master (project_id, project_name, project_nickname, project_status, "
    "project_registered_at, project_updated_at, social_autopsy_enabled) "
    "VALUES (:project_id, :project_id, :project_id, 'active', now(), now(), :coder)"
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class SocialAutopsyCollectMigrationConfig(TestConfig):
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
    return set(db.session.scalars(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'va_project_master'"
    )))


class AddSocialAutopsyCollectMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_backfills_collect_from_the_coder_switch_and_downgrade_drops_it(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(SocialAutopsyCollectMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                db.session.execute(sa.text(PROJECT_SQL), {"project_id": "MIGSA1", "coder": True})
                db.session.execute(sa.text(PROJECT_SQL), {"project_id": "MIGSA0", "coder": False})
                db.session.commit()
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                rows = dict(db.session.execute(sa.text(
                    "SELECT project_id, social_autopsy_collect_enabled FROM va_project_master "
                    "WHERE project_id IN ('MIGSA1', 'MIGSA0')"
                )).all())
                self.assertEqual(rows, {"MIGSA1": True, "MIGSA0": False})
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(
                        "UPDATE va_project_master SET social_autopsy_collect_enabled = NULL"
                    ))
                db.session.rollback()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertIn("social_autopsy_enabled", _columns(db))
                self.assertNotIn("social_autopsy_collect_enabled", _columns(db))
                self.assertEqual(db.session.scalar(sa.text(
                    "SELECT count(*) FROM va_project_master WHERE project_id IN ('MIGSA1', 'MIGSA0')"
                )), 2)
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertIn("social_autopsy_collect_enabled", _columns(db))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
