"""``c5e8a1f4b2d9`` adds ``va_bundle_pending_coding`` (bundle spec 5.5,
bead digitva-gb8w.2).

Builds a throwaway database at the previous head, upgrades, checks the
table, its key and indexes and the status check, refuses a downgrade while a
row is pending, then downgrades and checks it is gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_bundle_pending_coding.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig
from tests.migrations.test_add_bundle_ingests import (
    _IDS,
    _INGEST,
    _SEED,
    _admin_execute,
    _server_url,
)

DB_NAME = "minerva_test_bundle_pending_mig"
PREVIOUS_HEAD = "a7d3e9b2c4f6"
REVISION = "c5e8a1f4b2d9"
TABLE = "va_bundle_pending_coding"
_PENDING = (
    "INSERT INTO va_bundle_pending_coding (client_id, bundle_ids, project_id, va_sid, actor_user_id,"
    " content_sha256, result, status, created_at) VALUES ('00000000-0000-4000-8000-0000000000dd',"
    " ARRAY[CAST(:bundle AS uuid)], 'MIG01', 'mig-sid', :user, repeat('0', 64), '{}', :status, now())"
)


class PendingCodingConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(DB_NAME).render_as_string(hide_password=False)


def _drop_database():
    _admin_execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{DB_NAME}"',
    )


class BundlePendingCodingMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_and_downgrade_removes(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(PendingCodingConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                self.assertIn(TABLE, inspector.get_table_names())
                self.assertEqual(inspector.get_pk_constraint(TABLE)["constrained_columns"], ["client_id"])
                self.assertTrue({"ix_va_bundle_pending_coding_status_created", "ix_va_bundle_pending_coding_va_sid"}
                                <= {i["name"] for i in inspector.get_indexes(TABLE)})
                for statement in (*_SEED, _INGEST):
                    db.session.execute(sa.text(statement), _IDS)
                db.session.commit()
                # A submission row needs a whole form tree; its foreign key is
                # not what this test is about, so it is off for these inserts.
                db.session.execute(sa.text("SET LOCAL session_replication_role = replica"))
                with self.assertRaises(sa.exc.IntegrityError):
                    with db.session.begin_nested():
                        db.session.execute(sa.text(_PENDING), {**_IDS, "status": "held"})
                db.session.execute(sa.text(_PENDING), {**_IDS, "status": "pending"})
                db.session.commit()
                db.session.remove()
                # flask_migrate turns the migration's RuntimeError into SystemExit.
                with self.assertRaises(SystemExit):
                    alembic_downgrade(revision=PREVIOUS_HEAD)
                db.session.remove()
                db.session.execute(sa.text(f"UPDATE {TABLE} SET status = 'applied'"))
                db.session.commit()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertNotIn(TABLE, sa.inspect(db.engine).get_table_names())
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()
