"""``b4e8c2a6d0f3`` adds ``mas_training_sessions.session_type`` (with its check
and the slots rule tied to it) and ``map_training_participants.graduated_at``.

Builds a throwaway database at the previous head, upgrades (a legacy row keeps
its 20 slots and NULL type; the checks refuse a bad type and the zero-slot
rule), refuses the downgrade while a typed session exists, downgrades once it
is gone and upgrades again. Foreign keys are skipped for the inserted rows
(``session_replication_role = replica``); CHECK constraints still apply.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_training_session_types_migration.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_training_types_mig"
PREVIOUS_HEAD = "a9d3e6b1c4f8"
REVISION = "b4e8c2a6d0f3"

INSERT = (
    "INSERT INTO mas_training_sessions (training_session_id, project_id, session_code, name, created_at, "
    "created_by, org_unit_id, status, coder_slots{type_col}) VALUES (gen_random_uuid(), 'TRN01', :code, 'x', "
    "now(), gen_random_uuid(), gen_random_uuid(), 'active', :slots{type_val})"
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class TrainingTypesMigrationConfig(TestConfig):
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


def _insert(db, code, slots, session_type=None, *, typed=True):
    db.session.execute(sa.text("SET session_replication_role = replica"))
    sql = INSERT.format(type_col=", session_type" if typed else "", type_val=", :type" if typed else "")
    params = {"code": code, "slots": slots, **({"type": session_type} if typed else {})}
    db.session.execute(sa.text(sql), params)


def _columns(db, table):
    return set(db.session.scalars(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table}))


class TrainingSessionTypesMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_checks_refused_downgrade_and_round_trip(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(TrainingTypesMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                _insert(db, "S001", 20, typed=False)
                db.session.commit()
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertIn("graduated_at", _columns(db, "map_training_participants"))
                self.assertEqual(db.session.execute(sa.text(
                    "SELECT coder_slots, session_type FROM mas_training_sessions WHERE session_code = 'S001'"
                )).one(), (20, None))
                for code, slots, session_type in (("S090", 1, "interviewer"), ("S091", 0, "coder"),
                                                  ("S092", 0, None), ("S093", 1, "reviewer"),
                                                  ("S094", 101, "coder")):
                    with self.assertRaises(sa.exc.IntegrityError, msg=(slots, session_type)):
                        _insert(db, code, slots, session_type)
                    db.session.rollback()
                _insert(db, "S002", 0, "interviewer")
                _insert(db, "S003", 5, "self_coding")
                db.session.commit()
                db.session.remove()

                with self.assertRaises(SystemExit):  # flask_migrate wraps the RuntimeError
                    alembic_downgrade(revision=PREVIOUS_HEAD)
                db.session.remove()
                self.assertIn("session_type", _columns(db, "mas_training_sessions"))
                db.session.execute(sa.text("DELETE FROM mas_training_sessions WHERE session_type IS NOT NULL"))
                db.session.commit()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertNotIn("session_type", _columns(db, "mas_training_sessions"))
                self.assertNotIn("graduated_at", _columns(db, "map_training_participants"))
                with self.assertRaises(sa.exc.IntegrityError):  # the old 1..100 check is back
                    _insert(db, "S095", 0, typed=False)
                db.session.rollback()
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertIn("session_type", _columns(db, "mas_training_sessions"))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
