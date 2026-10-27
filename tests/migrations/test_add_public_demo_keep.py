"""``d8e2a6c4f1b7`` adds ``va_users.public_demo_keep`` (digitva-xfxb).

Builds a throwaway database at the previous head with a public-demo account,
upgrades (the account is not kept, and the column is NOT NULL with a false
default), downgrades (the column is gone, the account stays) and upgrades
again.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_public_demo_keep.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_public_demo_keep_mig"

PREVIOUS_HEAD = "f3d9b5c7a2e4"
REVISION = "d8e2a6c4f1b7"

USER_SQL = (
    "INSERT INTO va_users (user_id, name, password, vacode_language, permission, "
    "landing_page, pw_reset_t_and_c, email_verified, user_status, vacode_formcount, "
    "user_created_at, user_updated_at, username, is_public_demo) VALUES (gen_random_uuid(), 'Seed', "
    "'x', ARRAY['english'], '{}'::jsonb, 'coder', true, true, 'active', 0, now(), now(), "
    "'demo.mig', true) RETURNING user_id"
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class PublicDemoKeepMigrationConfig(TestConfig):
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
    return set(db.session.scalars(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'va_users'"
    )))


class AddPublicDemoKeepMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_defaults_to_not_kept_and_downgrade_drops_the_column(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(PublicDemoKeepMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                user_id = db.session.execute(sa.text(USER_SQL)).scalar_one()
                db.session.commit()
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertFalse(db.session.scalar(
                    sa.text("SELECT public_demo_keep FROM va_users WHERE user_id = :u"), {"u": user_id}))
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text("UPDATE va_users SET public_demo_keep = NULL"))
                db.session.rollback()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertIn("is_public_demo", _columns(db))
                self.assertNotIn("public_demo_keep", _columns(db))
                self.assertEqual(db.session.scalar(sa.text("SELECT count(*) FROM va_users WHERE user_id = :u"),
                                                   {"u": user_id}), 1)
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertIn("public_demo_keep", _columns(db))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
