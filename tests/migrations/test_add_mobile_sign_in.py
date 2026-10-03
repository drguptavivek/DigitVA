"""``f3a8c1d6e2b9`` adds mobile sign-in (digitva-l7c2).

Builds a throwaway database at the previous head with users whose free-text
phone is a unique valid number (formatted), a number two accounts share
(written two ways), a 9-digit number and no number. Upgrades and checks: only
the unique valid number is backfilled into ``mobile_login``, ``phone`` is
untouched, a mobile-only account can be added and an account with neither is
refused. The downgrade refuses while a mobile-only account exists, then
succeeds once it is gone and restores NOT NULL on ``email``.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_mobile_sign_in.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_mobile_signin_mig"

PREVIOUS_HEAD = "e2b7c4d9a1f3"
REVISION = "f3a8c1d6e2b9"

USER_SQL = (
    "INSERT INTO va_users (user_id, name, email, password, vacode_language, permission, "
    "landing_page, pw_reset_t_and_c, email_verified, user_status, vacode_formcount, "
    "user_created_at, user_updated_at, phone) VALUES (gen_random_uuid(), 'Seed', :e, 'x', "
    "ARRAY['english'], '{}'::jsonb, 'coder', true, true, 'active', 0, now(), now(), :p) "
    "RETURNING user_id"
)
MOBILE_ONLY_SQL = (
    "INSERT INTO va_users (user_id, name, email, password, vacode_language, permission, "
    "landing_page, pw_reset_t_and_c, email_verified, user_status, vacode_formcount, "
    "user_created_at, user_updated_at, phone, mobile_login) VALUES (gen_random_uuid(), "
    "'Mobile', NULL, 'x', ARRAY['english'], '{}'::jsonb, 'coder', true, false, 'active', 0, "
    "now(), now(), :m, :m) RETURNING user_id"
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class MobileSignInMigrationConfig(TestConfig):
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


class AddMobileSignInMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_backfill_only_unique_valid_numbers_and_guarded_downgrade(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(MobileSignInMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                seeds = {
                    "unique": "+91 98765-43210",
                    "shared_a": "9123456780",
                    "shared_b": "0 91234 56780",
                    "short": "912345678",
                    "none": None,
                }
                ids = {
                    key: db.session.execute(
                        sa.text(USER_SQL), {"e": f"{key}@mig.test", "p": phone}
                    ).scalar_one()
                    for key, phone in seeds.items()
                }
                db.session.commit()
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                rows = {
                    row.user_id: (row.phone, row.mobile_login)
                    for row in db.session.execute(sa.text(
                        "SELECT user_id, phone, mobile_login FROM va_users"
                    ))
                }
                self.assertEqual(rows[ids["unique"]], ("+91 98765-43210", "9876543210"))
                for key in ("shared_a", "shared_b", "short", "none"):
                    with self.subTest(key=key):
                        self.assertEqual(rows[ids[key]], (seeds[key], None))

                mobile_only = db.session.execute(
                    sa.text(MOBILE_ONLY_SQL), {"m": "9000000001"}
                ).scalar_one()
                db.session.commit()
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(
                        "UPDATE va_users SET mobile_login = NULL WHERE user_id = :u"
                    ), {"u": mobile_only})
                db.session.rollback()
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(MOBILE_ONLY_SQL), {"m": "9876543210"})
                db.session.rollback()
                db.session.remove()

                # Flask-Migrate reports the migration's RuntimeError as exit 1.
                with self.assertRaises(SystemExit):
                    alembic_downgrade(revision=PREVIOUS_HEAD)
                db.session.remove()
                db.session.execute(sa.text("DELETE FROM va_users WHERE user_id = :u"),
                                   {"u": mobile_only})
                db.session.commit()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                nullable = db.session.execute(sa.text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'va_users' AND column_name = 'email'"
                )).scalar_one()
                self.assertEqual(nullable, "NO")
                self.assertEqual(
                    db.session.execute(sa.text(
                        "SELECT phone FROM va_users WHERE user_id = :u"), {"u": ids["unique"]}
                    ).scalar_one(),
                    "+91 98765-43210",
                )
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
