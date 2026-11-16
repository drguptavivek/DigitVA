"""``d8a2f4c6e1b3`` adds ``map_project_members`` (digitva-plgm).

Builds a throwaway database at the previous head, upgrades (table, unique
(project_id, user_id), user index), downgrades (table gone) and upgrades
again. Foreign keys are skipped for the inserted rows
(``session_replication_role = replica``); unique constraints still apply.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_map_project_members.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_project_members_mig"
PREVIOUS_HEAD = "c7f1d3a5e9b2"
REVISION = "d8a2f4c6e1b3"

INSERT = (
    "INSERT INTO map_project_members (project_member_id, project_id, user_id, added_by_user_id, added_at) "
    "VALUES (gen_random_uuid(), 'MEM001', '00000000-0000-0000-0000-000000000001', "
    "'00000000-0000-0000-0000-000000000002', now())"
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class ProjectMembersMigrationConfig(TestConfig):
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
    return db.session.scalar(sa.text("SELECT to_regclass('map_project_members') IS NOT NULL"))


class ProjectMembersMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_unique_downgrade_round_trip(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(ProjectMembersMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self.assertFalse(_has_table(db))
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertTrue(_has_table(db))
                self.assertIn("ix_map_project_members_user_id", set(db.session.scalars(sa.text(
                    "SELECT indexname FROM pg_indexes WHERE tablename = 'map_project_members'"))))
                db.session.execute(sa.text("SET session_replication_role = replica"))
                db.session.execute(sa.text(INSERT))
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(INSERT))
                db.session.rollback()
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
