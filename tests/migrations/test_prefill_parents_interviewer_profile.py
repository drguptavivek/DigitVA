"""``c5e2b7a9d4f6`` adds parents' names to ``va_death_register`` and the
interviewer year of birth and sex to ``va_users`` (digitva-vzk.1, vzk.3).

The suite builds its schema with ``create_all()``, so this test builds a
throwaway database at the previous head, seeds a user and a case, upgrades,
checks the four nullable columns with the rows intact, then downgrades and
checks the columns are gone and the rows are still there.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_prefill_parents_interviewer_profile.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
PREFILL_DB_NAME = "minerva_test_prefill_mig"

PREVIOUS_HEAD = "a8d4f1c7e3b9"
REVISION = "c5e2b7a9d4f6"
NEW_COLUMNS = {
    "va_death_register": {"father_name", "mother_name"},
    "va_users": {"year_of_birth", "sex"},
}


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class PrefillConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(PREFILL_DB_NAME).render_as_string(hide_password=False)


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
        f"WHERE datname = '{PREFILL_DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{PREFILL_DB_NAME}"',
    )


class PrefillProfileMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_and_downgrade_removes(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{PREFILL_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(PrefillConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self._seed(db)

                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                for table, names in NEW_COLUMNS.items():
                    columns = {c["name"]: c for c in inspector.get_columns(table)}
                    self.assertTrue(names <= set(columns), table)
                    self.assertTrue(all(columns[name]["nullable"] for name in names), table)
                row = db.session.execute(
                    sa.text("SELECT deceased_name, father_name, mother_name FROM va_death_register")
                ).one()
                self.assertEqual(tuple(row), ("Seed Name", None, None))
                db.session.execute(sa.text("UPDATE va_users SET year_of_birth = 1980, sex = 'female' WHERE name = 'Prefill Seed'"))
                db.session.commit()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                inspector = sa.inspect(db.engine)
                for table, names in NEW_COLUMNS.items():
                    self.assertFalse(names & {c["name"] for c in inspector.get_columns(table)}, table)
                self.assertEqual(
                    db.session.execute(sa.text("SELECT deceased_name FROM va_death_register")).scalars().all(),
                    ["Seed Name"],
                )
                self.assertEqual(
                    db.session.execute(sa.text("SELECT name FROM va_users WHERE email = 'prefill.seed@test.local'")
                    ).scalars().all(),
                    ["Prefill Seed"],
                )
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()

    def _seed(self, db):
        params = {"p": "PFM01", "s": "PFM1"}
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
                "'Prefill Seed', 'prefill.seed@test.local', 'x', ARRAY['english'], '{}'::jsonb, "
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
