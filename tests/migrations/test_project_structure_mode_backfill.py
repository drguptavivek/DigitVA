"""``a4c7e2f9b1d6`` backfills project_structure_mode from existing org rows.

digitva-67n. The suite builds its schema with ``create_all()`` and never runs
the backfill, so this test builds a throwaway database at the previous head,
seeds projects with a level, with only a unit, and with neither, upgrades, and
checks the mode each landed on. It also checks the CHECK
rejects another value, then downgrades and asserts the column is gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_project_structure_mode_backfill.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
BACKFILL_DB_NAME = "minerva_test_structure_mode"

PREVIOUS_HEAD = "d5b71c3e9a84"
REVISION = "a4c7e2f9b1d6"

WITH_LEVEL = "SMLVL1"
WITH_UNIT_ONLY = "SMUNT1"
PLAIN = "SMSIT1"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class BackfillConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(BACKFILL_DB_NAME).render_as_string(
        hide_password=False
    )


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
        f"WHERE datname = '{BACKFILL_DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{BACKFILL_DB_NAME}"',
    )


class ProjectStructureModeBackfillTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_backfill_and_downgrade(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{BACKFILL_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(BackfillConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self._seed(db)

                alembic_upgrade(revision=REVISION)
                modes = dict(
                    db.session.execute(
                        sa.text(
                            "SELECT project_id, project_structure_mode FROM va_project_master"
                        )
                    ).all()
                )
                self.assertEqual(
                    modes,
                    {
                        WITH_LEVEL: "organization",
                        WITH_UNIT_ONLY: "organization",
                        PLAIN: "sites",
                    },
                )
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(
                        sa.text(
                            "UPDATE va_project_master SET project_structure_mode = 'bogus' "
                            "WHERE project_id = :p"
                        ),
                        {"p": PLAIN},
                    )
                db.session.rollback()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                columns = {
                    column["name"]
                    for column in sa.inspect(db.engine).get_columns("va_project_master")
                }
                self.assertIn("project_id", columns)
                self.assertNotIn("project_structure_mode", columns)
                db.engine.dispose()
        finally:
            _drop_database()

    def _seed(self, db):
        for project_id in (WITH_LEVEL, WITH_UNIT_ONLY, PLAIN):
            db.session.execute(
                sa.text(
                    "INSERT INTO va_project_master (project_id, project_name, "
                    "project_nickname, project_status, project_registered_at, "
                    "project_updated_at) VALUES (:p, :p, :p, 'active', now(), now())"
                ),
                {"p": project_id},
            )
        level_id = db.session.execute(
            sa.text(
                "INSERT INTO mas_org_level (org_level_id, project_id, level_code, "
                "level_name, depth, created_at, updated_at) VALUES "
                "(gen_random_uuid(), :p, 'district', 'District', 1, now(), now()) "
                "RETURNING org_level_id"
            ),
            {"p": WITH_LEVEL},
        ).scalar_one()
        # A unit row alone (its level belongs to another project) still marks
        # the project as organization: the backfill checks either table.
        db.session.execute(
            sa.text(
                "INSERT INTO mas_org_unit (org_unit_id, project_id, org_level_id, "
                "unit_code, unit_name, path, created_at, updated_at) VALUES "
                "(gen_random_uuid(), :p, :lvl, 'D01', 'District One', 'D01', now(), now())"
            ),
            {"p": WITH_UNIT_ONLY, "lvl": level_id},
        )
        db.session.commit()


if __name__ == "__main__":
    unittest.main()
