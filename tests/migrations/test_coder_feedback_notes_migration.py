"""``e3b7c9d1f5a2`` adds ``va_coder_feedback_notes``; downgrade drops it.

Builds a throwaway database at the previous head, upgrades, checks the table
and the body-length check, downgrades and upgrades again.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_coder_feedback_notes_migration.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_feedback_notes_mig"
PREVIOUS_HEAD = "d8a2f4c6e1b3"
REVISION = "e3b7c9d1f5a2"
INSERT = (
    "INSERT INTO va_coder_feedback_notes (note_id, va_sid, coder_user_id, author_user_id, "
    "author_basis, project_id, org_unit_id, body, created_at) VALUES (gen_random_uuid(), 's', "
    "gen_random_uuid(), gen_random_uuid(), 'admin', 'P1', gen_random_uuid(), :body, now())"
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class FeedbackNotesMigrationConfig(TestConfig):
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


def _has_table(db):
    return db.session.scalar(sa.text("SELECT to_regclass('va_coder_feedback_notes') IS NOT NULL"))


class FeedbackNotesMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_downgrade_round_trip(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(FeedbackNotesMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self.assertFalse(_has_table(db))
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertTrue(_has_table(db))
                db.session.execute(sa.text("SET session_replication_role = replica"))
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(INSERT), {"body": ""})
                db.session.rollback()
                db.session.execute(sa.text("SET session_replication_role = replica"))
                db.session.execute(sa.text(INSERT), {"body": "ok"})
                db.session.commit()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertFalse(_has_table(db))
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertTrue(_has_table(db))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
