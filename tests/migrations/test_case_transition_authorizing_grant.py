"""``a8d4f1c7e3b9`` names the grant and cadre a supervisor action relied on in
``map_case_transitions`` (digitva-vzk.8, decision 15).

The suite builds its schema with ``create_all()``, so this test builds a
throwaway database at the previous head, seeds one case and its audit row,
upgrades, checks the two nullable columns and their foreign keys, then
downgrades and checks they are gone and the audit row is intact.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_case_transition_authorizing_grant.py -q
"""
import unittest
import uuid

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
GRANT_DB_NAME = "minerva_test_case_grant_mig"

PREVIOUS_HEAD = "f2a6d9c3e8b1"
REVISION = "a8d4f1c7e3b9"
NEW_COLUMNS = {"authorizing_grant_id", "authorizing_cadre_id"}


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class GrantConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(GRANT_DB_NAME).render_as_string(hide_password=False)


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
        f"WHERE datname = '{GRANT_DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{GRANT_DB_NAME}"',
    )


class CaseTransitionGrantMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_and_downgrade_removes(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{GRANT_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(GrantConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self._seed(db)

                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                columns = {c["name"]: c for c in inspector.get_columns("map_case_transitions")}
                self.assertTrue(NEW_COLUMNS <= set(columns))
                self.assertTrue(all(columns[name]["nullable"] for name in NEW_COLUMNS))
                self.assertEqual(
                    {fk["referred_table"] for fk in inspector.get_foreign_keys("map_case_transitions")
                     if fk["constrained_columns"][0] in NEW_COLUMNS},
                    {"va_user_access_grants", "mas_cadre"},
                )
                row = db.session.execute(
                    sa.text("SELECT action, authorizing_grant_id, authorizing_cadre_id FROM map_case_transitions")
                ).one()
                self.assertEqual(tuple(row), ("created", None, None))
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(
                        sa.text("UPDATE map_case_transitions SET authorizing_grant_id = :g"),
                        {"g": uuid.uuid4()},
                    )
                db.session.rollback()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                columns = {c["name"] for c in sa.inspect(db.engine).get_columns("map_case_transitions")}
                self.assertIn("action", columns)
                self.assertFalse(NEW_COLUMNS & columns)
                self.assertEqual(
                    db.session.execute(sa.text("SELECT action FROM map_case_transitions")).scalars().all(),
                    ["created"],
                )
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()

    def _seed(self, db):
        params = {"p": "CGP01", "s": "CG01"}
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
                "'Grant Seed', 'grant.seed@test.local', 'x', ARRAY['english'], '{}'::jsonb, "
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
        db.session.execute(
            sa.text(
                "INSERT INTO map_case_transitions (transition_id, death_id, action, to_state, "
                "actor_user_id, created_at) SELECT gen_random_uuid(), death_id, 'created', "
                "'registered', :u, now() FROM va_death_register"
            ),
            {"u": user_id},
        )
        db.session.commit()
        return user_id



if __name__ == "__main__":
    unittest.main()
