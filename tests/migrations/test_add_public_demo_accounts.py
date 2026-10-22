"""``b4d6f8a2c9e1`` adds public-demo accounts (digitva-77v5.2).

Builds a throwaway database at the previous head with an email account and a
mobile-only account. Upgrades and checks: both keep their rows and are not
public-demo; a username-only account can be added; usernames are unique; an
account with no email, mobile or username is still refused. The downgrade
refuses while a username-only account exists, then succeeds once it is gone
and restores the narrow check (a username-only row is refused again).

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_public_demo_accounts.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_public_demo_mig"

PREVIOUS_HEAD = "a3c5e7f9b2d4"
REVISION = "b4d6f8a2c9e1"

_COLUMNS = (
    "INSERT INTO va_users (user_id, name, email, password, vacode_language, permission, "
    "landing_page, pw_reset_t_and_c, email_verified, user_status, vacode_formcount, "
    "user_created_at, user_updated_at, mobile_login{extra}) VALUES (gen_random_uuid(), 'Seed', "
    ":e, 'x', ARRAY['english'], '{{}}'::jsonb, 'coder', true, true, 'active', 0, now(), now(), "
    ":m{values}) RETURNING user_id"
)
USER_SQL = _COLUMNS.format(extra="", values="")
USERNAME_SQL = _COLUMNS.format(extra=", username, is_public_demo", values=", :u, true")


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class PublicDemoMigrationConfig(TestConfig):
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


class AddPublicDemoAccountsMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_widened_check_unique_username_and_guarded_downgrade(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(PublicDemoMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                email_user = db.session.execute(
                    sa.text(USER_SQL), {"e": "kept@mig.test", "m": None}
                ).scalar_one()
                mobile_user = db.session.execute(
                    sa.text(USER_SQL), {"e": None, "m": "9000000002"}
                ).scalar_one()
                db.session.commit()
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                rows = {
                    row.user_id: (row.email, row.mobile_login, row.username, row.is_public_demo)
                    for row in db.session.execute(sa.text(
                        "SELECT user_id, email, mobile_login, username, is_public_demo FROM va_users"
                    ))
                }
                self.assertEqual(rows[email_user], ("kept@mig.test", None, None, False))
                self.assertEqual(rows[mobile_user], (None, "9000000002", None, False))

                demo = db.session.execute(
                    sa.text(USERNAME_SQL), {"e": None, "m": None, "u": "demo.one"}
                ).scalar_one()
                db.session.commit()
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(USERNAME_SQL), {"e": None, "m": None, "u": "demo.one"})
                db.session.rollback()
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(USER_SQL), {"e": None, "m": None})
                db.session.rollback()
                db.session.remove()

                # Flask-Migrate reports the migration's RuntimeError as exit 1.
                with self.assertRaises(SystemExit):
                    alembic_downgrade(revision=PREVIOUS_HEAD)
                db.session.remove()
                db.session.execute(sa.text("DELETE FROM va_users WHERE user_id = :u"), {"u": demo})
                db.session.commit()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                columns = set(db.session.scalars(sa.text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'va_users'"
                )))
                self.assertIn("mobile_login", columns)
                self.assertNotIn("username", columns)
                self.assertNotIn("is_public_demo", columns)
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(USER_SQL), {"e": None, "m": None})
                db.session.rollback()
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
