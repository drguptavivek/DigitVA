"""``b4e7c2a9d6f3`` adds ``auth_account_deletion_requests`` (digitva-et16).

Builds a throwaway database at the previous head with an account, upgrades
(one pending request per account, enforced by the partial unique index; a
handled one does not count), downgrades (the table is gone, the account
stays) and upgrades again.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_auth_account_deletion_requests.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_account_deletion_requests_mig"

PREVIOUS_HEAD = "d8e2a6c4f1b7"
REVISION = "b4e7c2a9d6f3"

USER_SQL = (
    "INSERT INTO va_users (user_id, name, password, vacode_language, permission, "
    "landing_page, pw_reset_t_and_c, email_verified, user_status, vacode_formcount, "
    "user_created_at, user_updated_at, email) VALUES (gen_random_uuid(), 'Seed', "
    "'x', ARRAY['english'], '{}'::jsonb, 'coder', true, true, 'active', 0, now(), now(), "
    "'seed.mig@example.org') RETURNING user_id"
)
REQUEST_SQL = (
    "INSERT INTO auth_account_deletion_requests (id, user_id, requested_via, requested_at, handled_at) "
    "VALUES (gen_random_uuid(), :u, 'app', now(), {handled})"
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class AccountDeletionRequestsMigrationConfig(TestConfig):
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


def _has_table(db):
    return db.session.scalar(sa.text("SELECT to_regclass('auth_account_deletion_requests') IS NOT NULL"))


class AddAccountDeletionRequestsMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_allows_one_pending_request_and_downgrade_drops_the_table(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(AccountDeletionRequestsMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                user_id = db.session.execute(sa.text(USER_SQL)).scalar_one()
                db.session.commit()
                self.assertFalse(_has_table(db))
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                db.session.execute(sa.text(REQUEST_SQL.format(handled="now()")), {"u": user_id})
                db.session.execute(sa.text(REQUEST_SQL.format(handled="NULL")), {"u": user_id})
                db.session.commit()
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(REQUEST_SQL.format(handled="NULL")), {"u": user_id})
                db.session.rollback()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertFalse(_has_table(db))
                self.assertEqual(db.session.scalar(sa.text("SELECT count(*) FROM va_users WHERE user_id = :u"),
                                                   {"u": user_id}), 1)
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertTrue(_has_table(db))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
