"""``c8e4a2f6b1d3`` adds va_project_master.recode_window_minutes.

digitva-yeg3.2. Builds a throwaway database at the previous head, seeds TRN01
and an ordinary project, upgrades, and checks TRN01 landed on 60 and the other
on the 1440 default, that the CHECK refuses 0 and 10081, then downgrades and
asserts the column is gone.
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
MIGRATION_DB_NAME = "minerva_test_recode_window"

PREVIOUS_HEAD = "e3b7d1a9c4f2"
REVISION = "c8e4a2f6b1d3"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class MigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(MIGRATION_DB_NAME).render_as_string(
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
        f"WHERE datname = '{MIGRATION_DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"',
    )


class AddProjectRecodeWindowTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_sets_trn01_and_downgrade_drops(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(MigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                for project_id in ("TRN01", "RWDEF1"):
                    db.session.execute(
                        sa.text(
                            "INSERT INTO va_project_master (project_id, project_name, "
                            "project_nickname, project_status, project_registered_at, "
                            "project_updated_at) VALUES (:p, :p, :p, 'active', now(), now())"
                        ),
                        {"p": project_id},
                    )
                db.session.commit()

                alembic_upgrade(revision=REVISION)
                windows = dict(
                    db.session.execute(
                        sa.text(
                            "SELECT project_id, recode_window_minutes FROM va_project_master"
                        )
                    ).all()
                )
                self.assertEqual(windows, {"TRN01": 60, "RWDEF1": 1440})
                for bad in (0, 10081):
                    with self.assertRaises(sa.exc.IntegrityError):
                        db.session.execute(
                            sa.text(
                                "UPDATE va_project_master SET recode_window_minutes = :m "
                                "WHERE project_id = 'RWDEF1'"
                            ),
                            {"m": bad},
                        )
                    db.session.rollback()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                columns = {
                    column["name"]
                    for column in sa.inspect(db.engine).get_columns("va_project_master")
                }
                self.assertIn("project_id", columns)
                self.assertNotIn("recode_window_minutes", columns)
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
