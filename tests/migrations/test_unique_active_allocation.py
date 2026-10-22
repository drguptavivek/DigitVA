"""``a7c3e9f1d5b2`` deduplicates active allocations, then indexes them
unique per (user, kind) (bead digitva-igq7).

Builds a throwaway database at the previous head, seeds duplicate active
allocations, upgrades, checks the newest per (user, kind) stays active, the
rest are deactive with one audit row each, and the index refuses a second
active row; then downgrades and checks the index is gone.

Foreign-key triggers are off in the scratch database (session_replication_role
replica) so allocations can be seeded without users and submissions; unique
indexes are not triggers and still apply.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_unique_active_allocation.py -q
"""
import unittest
import uuid
from datetime import datetime, timedelta

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
DB_NAME = "minerva_test_unique_active_alloc_mig"

PREVIOUS_HEAD = "e2b7d4a9c6f1"
REVISION = "a7c3e9f1d5b2"
INDEX = "uq_va_allocations_active_to_for"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class UniqueActiveAllocationConfig(TestConfig):
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


class UniqueActiveAllocationMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_dedupes_and_indexes_downgrade_drops_index(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        def run(sql, **params):
            return db.session.execute(sa.text(sql), params)

        def indexdef():
            return run("SELECT indexdef FROM pg_indexes WHERE indexname = :n", n=INDEX).scalar()

        coder, reviewer = uuid.uuid4(), uuid.uuid4()
        now = datetime(2026, 10, 1, 12, 0)
        # (id, sid, user, kind, status, created)
        rows = {
            "old": (uuid.uuid4(), "s-old", coder, "coding", "active", now - timedelta(hours=2)),
            "mid": (uuid.uuid4(), "s-mid", coder, "coding", "active", now - timedelta(hours=1)),
            "new": (uuid.uuid4(), "s-new", coder, "coding", "active", now),
            "rev": (uuid.uuid4(), "s-rev", coder, "reviewing", "active", now - timedelta(hours=3)),
            "gone": (uuid.uuid4(), "s-gone", coder, "coding", "deactive", now + timedelta(hours=1)),
            "solo": (uuid.uuid4(), "s-solo", reviewer, "reviewing", "active", now),
        }

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(UniqueActiveAllocationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self.assertIsNone(indexdef())
                db.session.remove()
                db.engine.dispose()
                _admin_execute(
                    f'ALTER DATABASE "{DB_NAME}" SET session_replication_role = replica'
                )

                for alloc_id, sid, user, kind, status, created in rows.values():
                    run(
                        "INSERT INTO va_allocations (va_allocation_id, va_sid, va_allocated_to,"
                        " va_allocation_for, va_allocation_status, va_allocation_createdat,"
                        " va_allocation_updatedat) VALUES (:i, :s, :u, :k, :st, :c, :c)",
                        i=alloc_id, s=sid, u=user, k=kind, st=status, c=created,
                    )
                db.session.commit()
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertIn("UNIQUE", indexdef())
                self.assertIn("(va_allocated_to, va_allocation_for)", indexdef())
                self.assertIn("'active'", indexdef())

                status = dict(run(
                    "SELECT va_allocation_id, va_allocation_status::text FROM va_allocations"
                ).all())
                expected = {
                    "old": "deactive", "mid": "deactive", "new": "active",
                    "rev": "active", "gone": "deactive", "solo": "active",
                }
                for key, want in expected.items():
                    self.assertEqual(status[rows[key][0]], want, key)

                audits = run(
                    "SELECT va_audit_entityid, va_sid, va_audit_byrole, va_audit_operation"
                    " FROM va_submissions_auditlog"
                    " WHERE va_audit_action = 'va_allocation_deactivated_duplicate_active'"
                ).all()
                self.assertEqual(
                    sorted((a.va_audit_entityid, a.va_sid) for a in audits),
                    sorted((rows[k][0], rows[k][1]) for k in ("old", "mid")),
                )
                self.assertEqual({(a.va_audit_byrole, a.va_audit_operation) for a in audits},
                                 {("vasystem", "d")})

                with self.assertRaises(sa.exc.IntegrityError):
                    run(
                        "INSERT INTO va_allocations (va_allocation_id, va_sid, va_allocated_to,"
                        " va_allocation_for, va_allocation_status, va_allocation_createdat,"
                        " va_allocation_updatedat) VALUES (:i, 's-x', :u, 'coding', 'active',"
                        " :c, :c)",
                        i=uuid.uuid4(), u=coder, c=now,
                    )
                db.session.rollback()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertIsNone(indexdef())
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()
