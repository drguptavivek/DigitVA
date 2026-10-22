"""``f3a9c6d2e1b7`` adds ``va_users.user_number`` and the station onboarding
tables (beads digitva-gb8w.4, digitva-gb8w.8).

Builds a throwaway database at the previous head with two users, upgrades,
checks every existing user got a distinct ``user_number`` and a new user
gets the next one, the tables and the index exist, then downgrades and
checks they are gone; a downgrade with an issued config is refused.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_station_onboarding.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DB_NAME = "minerva_test_station_onboarding_mig"
PREVIOUS_HEAD = "e8c4f2a7b913"
REVISION = "f3a9c6d2e1b7"
TABLES = {"auth_station_custodians", "auth_station_roster", "auth_station_configs"}
_USER_SQL = (
    "INSERT INTO va_users (user_id, name, email, vacode_language, timezone, vacode_formcount, permission,"
    " password, landing_page, pw_reset_t_and_c, email_verified, user_status, user_created_at, user_updated_at,"
    " auth_session_version)"
    " VALUES (:id, :name, :email, '{}', 'Asia/Kolkata', 0, '{}', 'x', 'home', false, true, 'active', now(), now(), 0)"
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class StationOnboardingConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(DB_NAME).render_as_string(hide_password=False)


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
        f"WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{DB_NAME}"',
    )


class StationOnboardingMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_and_downgrade_removes(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(StationOnboardingConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                for n in (1, 2):
                    db.session.execute(sa.text(_USER_SQL), {
                        "id": f"00000000-0000-4000-8000-00000000000{n}", "name": f"User {n}",
                        "email": f"user{n}@mig.test"})
                db.session.commit()

                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                self.assertTrue(TABLES <= set(inspector.get_table_names()))
                numbers = db.session.execute(sa.text("SELECT user_number FROM va_users ORDER BY user_number")).scalars().all()
                users = db.session.execute(sa.text("SELECT count(*) FROM va_users")).scalar()
                self.assertGreaterEqual(users, 2)  # ours, and any user an earlier migration seeds
                self.assertEqual(len(numbers), users)
                self.assertEqual(len(set(numbers)), users)
                db.session.execute(sa.text(_USER_SQL), {
                    "id": "00000000-0000-4000-8000-000000000003", "name": "User 3", "email": "user3@mig.test"})
                newest = db.session.execute(sa.text(
                    "SELECT user_number FROM va_users WHERE email = 'user3@mig.test'")).scalar()
                self.assertGreater(newest, max(numbers))
                db.session.commit()
                uniques = [u["column_names"] for u in inspector.get_unique_constraints("auth_station_roster")]
                self.assertIn(["device_id", "user_id"], uniques)
                self.assertIn("ix_auth_station_configs_device_issued",
                              {i["name"] for i in inspector.get_indexes("auth_station_configs")})

                db.session.execute(sa.text(
                    "INSERT INTO va_project_master (project_id, project_code, project_name, project_nickname,"
                    " project_status, project_registered_at, project_updated_at)"
                    " VALUES ('MIG01', 'MIG01', 'Migration', 'MIG01', 'active', now(), now())"))
                db.session.execute(sa.text(
                    "INSERT INTO auth_devices (device_id, project_id, name, platform, secret_hash, enrolled_at,"
                    " revoked_compromised) VALUES ('00000000-0000-4000-8000-0000000000aa', 'MIG01', 'Station',"
                    " 'desktop', repeat('a', 64), now(), false)"))
                db.session.execute(sa.text(
                    "INSERT INTO auth_station_configs (config_id, device_id, issued_at, expires_at, issued_by,"
                    " signed_text, text_sha256) VALUES ('00000000-0000-4000-8000-0000000000bb',"
                    " '00000000-0000-4000-8000-0000000000aa', now(), now(),"
                    " '00000000-0000-4000-8000-000000000001', 'x', repeat('0', 64))"))
                db.session.commit()
                db.session.remove()
                # flask_migrate turns the migration's RuntimeError into SystemExit.
                with self.assertRaises(SystemExit):
                    alembic_downgrade(revision=PREVIOUS_HEAD)
                db.session.remove()
                self.assertIn("auth_station_configs", sa.inspect(db.engine).get_table_names())
                db.session.execute(sa.text("DELETE FROM auth_station_configs"))
                db.session.commit()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                inspector = sa.inspect(db.engine)
                self.assertIn("auth_devices", inspector.get_table_names())
                self.assertFalse(TABLES & set(inspector.get_table_names()))
                self.assertNotIn("user_number", {c["name"] for c in inspector.get_columns("va_users")})
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()
