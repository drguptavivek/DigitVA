"""``d7e3a1c9b5f2`` adds ``map_mentor_institute_user.is_admin`` (default false).

Builds a throwaway database at the previous head with one institute member,
upgrades, checks the existing row reads false and the column is NOT NULL, then
downgrades and checks the column is gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_mentor_institute_admin_flag.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_mentor_admin_mig"

PREVIOUS_HEAD = "c4a9e7d2b6f1"
REVISION = "d7e3a1c9b5f2"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class MentorAdminMigrationConfig(TestConfig):
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
    return {c["name"]: c for c in sa.inspect(db.engine).get_columns("map_mentor_institute_user")}


class MentorAdminFlagMigrationTest(unittest.TestCase):
    def test_flag_defaults_false_and_downgrade_drops_it(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(MentorAdminMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self.assertNotIn("is_admin", _columns(db))
                user_id = db.session.execute(sa.text(
                    "INSERT INTO va_users (user_id, name, email, password, vacode_language, "
                    "permission, landing_page, pw_reset_t_and_c, email_verified, user_status, "
                    "vacode_formcount, user_created_at, user_updated_at) VALUES "
                    "(gen_random_uuid(), 'Seed', 'mentor.admin.seed@test.local', 'x', "
                    "ARRAY['english'], '{}'::jsonb, 'coder', true, true, 'active', 0, now(), now()) "
                    "RETURNING user_id"
                )).scalar_one()
                institute_id = db.session.execute(sa.text(
                    "INSERT INTO mas_mentor_institute (institute_id, institute_code, "
                    "institute_name, is_active, created_at) VALUES (gen_random_uuid(), 'MA1', "
                    "'One', true, now()) RETURNING institute_id"
                )).scalar_one()
                db.session.execute(sa.text(
                    "INSERT INTO map_mentor_institute_user (institute_id, user_id, is_active, "
                    "created_at) VALUES (:i, :u, true, now())"
                ), {"i": institute_id, "u": user_id})
                db.session.commit()

                alembic_upgrade(revision=REVISION)
                self.assertFalse(_columns(db)["is_admin"]["nullable"])
                flag = db.session.execute(sa.text(
                    "SELECT is_admin FROM map_mentor_institute_user")).scalar_one()
                self.assertIs(flag, False)
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertNotIn("is_admin", _columns(db))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
