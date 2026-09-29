"""``e5b2c8d4a1f7`` adds visit dates, contact attempts, a second phone and the
structured address (digitva-vzk.9).

The suite builds its schema with ``create_all()``, so this test builds a
throwaway database at the previous head, seeds one case, upgrades, checks the
new columns, index, table and outcome CHECK, then downgrades and checks they
are gone and the case is intact.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_case_visits_contact_attempts.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
VISITS_DB_NAME = "minerva_test_case_visits_mig"

PREVIOUS_HEAD = "d7f3b1a9c5e2"
REVISION = "e5b2c8d4a1f7"
NEW_COLUMNS = {
    "next_visit_at", "last_contact_at", "informant_phone_2",
    "address_house_street", "address_village_ward", "address_landmark",
}


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class VisitsConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(VISITS_DB_NAME).render_as_string(hide_password=False)


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
        f"WHERE datname = '{VISITS_DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{VISITS_DB_NAME}"',
    )


class CaseVisitsMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_and_downgrade_removes(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{VISITS_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(VisitsConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                user_id = self._seed(db)

                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                columns = {c["name"] for c in inspector.get_columns("va_death_register")}
                self.assertTrue(NEW_COLUMNS <= columns)
                self.assertIn(
                    "ix_va_death_register_next_visit",
                    {i["name"] for i in inspector.get_indexes("va_death_register")},
                )
                self.assertIn("map_case_contact_attempts", inspector.get_table_names())
                row = db.session.execute(
                    sa.text("SELECT status, next_visit_at, informant_phone_2 FROM va_death_register")
                ).one()
                self.assertEqual(tuple(row), ("registered", None, None))

                insert = sa.text(
                    "INSERT INTO map_case_contact_attempts (attempt_id, death_id, attempted_at, "
                    "outcome, by_user_id, created_at) SELECT gen_random_uuid(), death_id, now(), "
                    ":outcome, :u, now() FROM va_death_register"
                )
                db.session.execute(insert, {"outcome": "no_answer", "u": user_id})
                db.session.commit()
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(insert, {"outcome": "left_a_note", "u": user_id})
                db.session.rollback()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                inspector = sa.inspect(db.engine)
                columns = {c["name"] for c in inspector.get_columns("va_death_register")}
                self.assertFalse(NEW_COLUMNS & columns)
                self.assertNotIn("map_case_contact_attempts", inspector.get_table_names())
                self.assertEqual(
                    db.session.execute(sa.text("SELECT unique_id FROM va_death_register")).scalars().all(),
                    ["V1"],
                )
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()

    def _seed(self, db):
        params = {"p": "CVP01", "s": "CV01"}
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
        user_id = db.session.execute(
            sa.text(
                "INSERT INTO va_users (user_id, name, email, password, vacode_language, "
                "permission, landing_page, pw_reset_t_and_c, email_verified, user_status, "
                "vacode_formcount, user_created_at, user_updated_at) VALUES (gen_random_uuid(), "
                "'Visit Seed', 'visit.seed@test.local', 'x', ARRAY['english'], '{}'::jsonb, "
                "'coder', true, true, 'active', 0, now(), now()) RETURNING user_id"
            )
        ).scalar_one()
        db.session.execute(
            sa.text(
                "INSERT INTO va_death_register (death_id, project_id, site_id, death_number, "
                "unique_id, deceased_name, deceased_sex, date_of_death, status, source, "
                "registered_by, created_at, updated_at) VALUES (gen_random_uuid(), :p, :s, 1, 'V1', "
                "'Seed Name', 'female', current_date - 3, 'registered', 'register', :u, now(), now())"
            ),
            {**params, "u": user_id},
        )
        db.session.commit()
        return user_id


if __name__ == "__main__":
    unittest.main()
