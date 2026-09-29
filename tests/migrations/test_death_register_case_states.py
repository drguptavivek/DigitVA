"""``c4e8a2f6b9d3`` makes the death register entry the case (digitva-vzk.4).

The suite builds its schema with ``create_all()`` and never runs the backfill,
so this test builds a throwaway database at the previous head, seeds one death
per old status (one with a draft), upgrades, and checks the status mapping,
the ``started_by_user_id`` backfill and the new CHECKs. It then adds a direct
start with no identity, checks the downgrade refuses while that row exists,
removes it, downgrades, and checks the old statuses and columns are back.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_death_register_case_states.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
CASE_DB_NAME = "minerva_test_case_states"

PREVIOUS_HEAD = "a7c3e9f1b5d2"
REVISION = "c4e8a2f6b9d3"
OLD_STATUSES = ("registered", "va_in_progress", "va_submitted", "cancelled")
EXPECTED = {
    "registered": "registered",
    "va_in_progress": "in_progress",
    "va_submitted": "submitted",
    "cancelled": "cancelled",
}


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class CaseStatesConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(CASE_DB_NAME).render_as_string(hide_password=False)


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
        f"WHERE datname = '{CASE_DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{CASE_DB_NAME}"',
    )


class DeathRegisterCaseStatesMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_backfill_checks_and_guarded_downgrade(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{CASE_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(CaseStatesConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                user_id = self._seed(db)

                alembic_upgrade(revision=REVISION)
                self.assertIn("map_case_transitions", sa.inspect(db.engine).get_table_names())
                rows = db.session.execute(
                    sa.text("SELECT unique_id, status, source, started_by_user_id FROM va_death_register")
                ).all()
                self.assertEqual(len(rows), len(OLD_STATUSES))
                by_old = {r.unique_id: r for r in rows}
                for old in OLD_STATUSES:
                    self.assertEqual(by_old[old].status, EXPECTED[old], old)
                    self.assertEqual(by_old[old].source, "register")
                # The in-progress case had a draft: its author started it.
                self.assertEqual(str(by_old["va_in_progress"].started_by_user_id), str(user_id))
                self.assertIsNone(by_old["registered"].started_by_user_id)

                for bad in (
                    "UPDATE va_death_register SET status = 'va_submitted' WHERE unique_id = 'registered'",
                    "UPDATE va_death_register SET source = 'odk' WHERE unique_id = 'registered'",
                    "UPDATE va_death_register SET deceased_name = NULL WHERE unique_id = 'registered'",
                ):
                    with self.assertRaises(sa.exc.IntegrityError, msg=bad):
                        db.session.execute(sa.text(bad))
                    db.session.rollback()

                # A direct start without identity is legal only in draft_identity.
                db.session.execute(
                    sa.text(
                        "INSERT INTO va_death_register (death_id, project_id, site_id, death_number, "
                        "unique_id, status, source, registered_by, started_by_user_id, created_at, "
                        "updated_at) VALUES (gen_random_uuid(), 'CSP01', 'CS01', 99, 'direct', "
                        "'draft_identity', 'direct', :u, :u, now(), now())"
                    ),
                    {"u": user_id},
                )
                db.session.commit()
                db.session.remove()

                # flask_migrate logs the migration's RuntimeError and exits 1.
                with self.assertRaises(SystemExit):
                    alembic_downgrade(revision=PREVIOUS_HEAD)
                db.session.remove()
                self.assertIn(
                    "draft_identity",
                    db.session.execute(sa.text("SELECT status FROM va_death_register")).scalars().all(),
                )
                db.session.execute(sa.text("DELETE FROM va_death_register WHERE unique_id = 'direct'"))
                db.session.commit()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                statuses = dict(
                    db.session.execute(sa.text("SELECT unique_id, status FROM va_death_register")).all()
                )
                self.assertEqual(statuses, {old: old for old in OLD_STATUSES})
                columns = {c["name"] for c in sa.inspect(db.engine).get_columns("va_death_register")}
                self.assertIn("status", columns)
                self.assertNotIn("source", columns)
                self.assertNotIn("started_by_user_id", columns)
                self.assertNotIn("map_case_transitions", sa.inspect(db.engine).get_table_names())
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()

    def _seed(self, db):
        params = {"p": "CSP01", "s": "CS01"}
        db.session.execute(
            sa.text(
                "INSERT INTO va_project_master (project_id, project_name, project_nickname, "
                "project_status, project_registered_at, project_updated_at) "
                "VALUES (:p, :p, :p, 'active', now(), now())"
            ),
            params,
        )
        db.session.execute(
            sa.text(
                "INSERT INTO va_site_master (site_id, site_name, site_abbr, site_status, "
                "site_registered_at, site_updated_at) VALUES (:s, :s, :s, 'active', now(), now())"
            ),
            params,
        )
        # The legacy project and site tables va_forms still references.
        db.session.execute(
            sa.text(
                "INSERT INTO va_research_projects (project_id, project_name, project_nickname, "
                "project_status, project_registered_at, project_updated_at) "
                "VALUES (:p, :p, :p, 'active', now(), now())"
            ),
            params,
        )
        db.session.execute(
            sa.text(
                "INSERT INTO va_sites (site_id, project_id, site_name, site_abbr, site_status, "
                "site_registered_at, site_updated_at) VALUES (:s, :p, :s, :s, 'active', now(), now())"
            ),
            params,
        )
        user_id = db.session.execute(
            sa.text(
                "INSERT INTO va_users (user_id, name, email, password, vacode_language, "
                "permission, landing_page, pw_reset_t_and_c, email_verified, user_status, "
                "vacode_formcount, user_created_at, user_updated_at) VALUES (gen_random_uuid(), "
                "'Case Seed', 'case.seed@test.local', 'x', ARRAY['english'], '{}'::jsonb, "
                "'coder', true, true, 'active', 0, now(), now()) RETURNING user_id"
            )
        ).scalar_one()
        for number, old in enumerate(OLD_STATUSES, start=1):
            db.session.execute(
                sa.text(
                    "INSERT INTO va_death_register (death_id, project_id, site_id, death_number, "
                    "unique_id, deceased_name, deceased_sex, date_of_death, status, registered_by, "
                    "created_at, updated_at) VALUES (gen_random_uuid(), :p, :s, :n, :old, 'Seed Name', "
                    "'female', current_date - 3, :old, :u, now(), now())"
                ),
                {**params, "n": number, "old": old, "u": user_id},
            )
        db.session.execute(
            sa.text(
                "INSERT INTO va_forms (form_id, project_id, site_id, odk_form_id, odk_project_id, "
                "form_type, form_smartvahiv, form_smartvamalaria, form_smartvahce, form_smartvafreetext, "
                "form_smartvacountry, form_status, form_registered_at, form_updated_at) VALUES "
                "('CSP01CS0101', :p, :s, 'WEB', '0', 'WHO VA 2022', 'False', 'False', 'True', "
                "'True', 'IND', 'active', now(), now())"
            ),
            params,
        )
        db.session.execute(
            sa.text(
                "INSERT INTO va_web_intake_drafts (draft_id, project_id, site_id, death_id, form_id, "
                "user_id, unique_id, meta, prefill, status, created_at, updated_at) "
                "SELECT gen_random_uuid(), :p, :s, death_id, 'CSP01CS0101', :u, unique_id, "
                "'{}'::jsonb, '{}'::jsonb, 'draft', now(), now() "
                "FROM va_death_register WHERE unique_id = 'va_in_progress'"
            ),
            {**params, "u": user_id},
        )
        db.session.commit()
        return user_id


if __name__ == "__main__":
    unittest.main()
