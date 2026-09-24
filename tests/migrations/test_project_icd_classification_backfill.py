"""``33dea3ea3303`` moves per-form ICD classifications up to the project.

digitva-dus.2. The suite builds its schema with ``create_all()`` and never runs
the backfill, so this test builds a throwaway database at the parent revision,
seeds projects whose ODK forms agree on icd10, agree on icd11, disagree, and
have no forms, upgrades, and checks where each landed. It checks the CHECK
rejects another value, then downgrades and asserts the column is gone and a
fixed project setting was copied back onto its forms.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_project_icd_classification_backfill.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
BACKFILL_DB_NAME = "minerva_test_icd_classification"

PARENT_REVISION = "e7b2c9d4a1f3"
REVISION = "33dea3ea3303"

ALL_ICD10 = "ICDA10"
ALL_ICD11 = "ICDA11"
MIXED = "ICDMIX"
NO_FORMS = "ICDNON"
SITE = "IC01"


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


class ProjectIcdClassificationBackfillTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_backfill_and_downgrade(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{BACKFILL_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(BackfillConfig)
            with app.app_context():
                alembic_upgrade(revision=PARENT_REVISION)
                self._seed(db)

                # The upgrade also logs each project moved off icd10 at WARNING;
                # env.py's fileConfig replaces logging handlers mid-run, so
                # assertLogs cannot observe it -- see the run's output.
                alembic_upgrade(revision=REVISION)
                settings = dict(
                    db.session.execute(
                        sa.text("SELECT project_id, icd_classification FROM va_project_master")
                    ).all()
                )
                self.assertEqual(
                    settings,
                    {
                        ALL_ICD10: "icd10",
                        ALL_ICD11: "icd11",
                        MIXED: "selectable",
                        NO_FORMS: "icd10",
                    },
                )
                # The per-form rows are left exactly as they were.
                self.assertEqual(self._form_values(db, MIXED), ["icd10", "icd11"])

                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(
                        sa.text(
                            "UPDATE va_project_master SET icd_classification = 'icd9' "
                            "WHERE project_id = :p"
                        ),
                        {"p": ALL_ICD10},
                    )
                db.session.rollback()

                # A setting changed after the upgrade survives a rollback.
                db.session.execute(
                    sa.text(
                        "UPDATE va_project_master SET icd_classification = 'icd11' "
                        "WHERE project_id = :p"
                    ),
                    {"p": ALL_ICD10},
                )
                db.session.commit()
                db.session.remove()

                alembic_downgrade(revision=PARENT_REVISION)
                columns = {
                    column["name"]
                    for column in sa.inspect(db.engine).get_columns("va_project_master")
                }
                self.assertIn("project_id", columns)
                self.assertNotIn("icd_classification", columns)
                self.assertEqual(self._form_values(db, ALL_ICD10), ["icd11", "icd11"])
                self.assertEqual(self._form_values(db, MIXED), ["icd10", "icd11"])
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()

    @staticmethod
    def _form_values(db, project_id):
        return sorted(
            db.session.execute(
                sa.text(
                    "SELECT icd_classification FROM map_project_site_odk "
                    "WHERE project_id = :p"
                ),
                {"p": project_id},
            ).scalars()
        )

    def _seed(self, db):
        for project_id in (ALL_ICD10, ALL_ICD11, MIXED, NO_FORMS):
            db.session.execute(
                sa.text(
                    "INSERT INTO va_project_master (project_id, project_name, "
                    "project_nickname, project_status, project_registered_at, "
                    "project_updated_at) VALUES (:p, :p, :p, 'active', now(), now())"
                ),
                {"p": project_id},
            )
        db.session.execute(
            sa.text(
                "INSERT INTO va_site_master (site_id, site_name, site_abbr, site_status, "
                "site_registered_at, site_updated_at) "
                "VALUES (:s, :s, :s, 'active', now(), now())"
            ),
            {"s": SITE},
        )
        forms = (
            (ALL_ICD10, "F1", "icd10"),
            (ALL_ICD10, "F2", "icd10"),
            (ALL_ICD11, "F3", "icd11"),
            (MIXED, "F4", "icd10"),
            (MIXED, "F5", "icd11"),
        )
        for project_id, odk_form_id, classification in forms:
            db.session.execute(
                sa.text(
                    "INSERT INTO map_project_site_odk (id, project_id, site_id, "
                    "odk_project_id, odk_form_id, icd_classification, created_at, "
                    "updated_at) VALUES (gen_random_uuid(), :p, :s, 1, :f, :c, now(), now())"
                ),
                {"p": project_id, "s": SITE, "f": odk_form_id, "c": classification},
            )
        db.session.commit()


if __name__ == "__main__":
    unittest.main()
