"""``e3b7d1a9c4f2`` adds the three training-session tables.

The suite builds its schema with ``create_all()`` and never runs the migration,
so this builds a throwaway database at the previous head, upgrades, checks the
tables, indexes and constraints with real rows, and checks the downgrade drops
them but refuses while a session exists (sessions are retained records).

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_migrate_training_sessions.py -q
"""
import unittest
import uuid

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DB_NAME = "minerva_test_training_sessions"
PREVIOUS_HEAD = "a7c3e9f1d5b2"
REVISION = "e3b7d1a9c4f2"
TABLES = ("mas_training_sessions", "map_training_cases", "map_training_participants")


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class MigrationConfig(TestConfig):
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


class TrainingSessionsMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_constraints_and_guarded_downgrade(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(MigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self.assertFalse(set(TABLES) & set(sa.inspect(db.engine).get_table_names()))

                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                self.assertTrue(set(TABLES) <= set(inspector.get_table_names()))
                names = {i["name"] for t in TABLES for i in inspector.get_indexes(t)}
                self.assertTrue({
                    "ix_map_training_cases_session_slot",
                    "ix_map_training_participants_session_role",
                    "uq_map_training_participants_session_slot",
                    "ix_mas_training_sessions_project_created",
                } <= names)

                # Seed at head: later migrations add project columns the
                # models already map (e.g. recode_window_minutes).
                alembic_upgrade(revision="heads")
                session_id, user_id = self._seed(db)
                self._constraints(db, session_id, user_id)

                with self.assertRaises((RuntimeError, SystemExit)):  # flask-migrate may exit
                    alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertTrue(set(TABLES) <= set(sa.inspect(db.engine).get_table_names()))

                db.session.rollback()
                db.session.execute(sa.text("DELETE FROM map_training_participants"))
                db.session.execute(sa.text("DELETE FROM mas_training_sessions"))
                db.session.commit()
                db.session.remove()
                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertFalse(set(TABLES) & set(sa.inspect(db.engine).get_table_names()))
                db.engine.dispose()
        finally:
            _drop_database()

    def _seed(self, db):
        # The schema is the head's (the test upgrades to head before seeding),
        # so the models write to it as they do in the app.
        from app.models import MasOrgLevel, MasOrgUnit, VaProjectMaster

        user = self._user(db, "a@b.c")
        db.session.add(VaProjectMaster(
            project_id="TRN01", project_code="TRN01", project_name="t", project_nickname="t"))
        db.session.flush()
        level = MasOrgLevel(project_id="TRN01", level_code="phc", level_name="PHC", depth=1)
        db.session.add(level)
        db.session.flush()
        unit = MasOrgUnit(
            project_id="TRN01", org_level_id=level.org_level_id, unit_code="S001", unit_name="S001", path="S001")
        db.session.add(unit)
        db.session.flush()
        session_id = uuid.uuid4()
        db.session.execute(
            sa.text(
                "INSERT INTO mas_training_sessions (training_session_id, project_id, session_code, name, "
                "created_at, created_by, org_unit_id) VALUES (:s, 'TRN01', 'S001', 'n', now(), :u, :o)"),
            {"s": session_id, "u": user.user_id, "o": unit.org_unit_id},
        )
        db.session.commit()
        return session_id, user.user_id

    def _user(self, db, email):
        from app.models import VaUsers

        user = VaUsers(
            name="n", email=email, vacode_language=["english"], permission={}, landing_page="coder",
            email_verified=True, pw_reset_t_and_c=True)
        user.set_password("Passw0rd-test-1")
        db.session.add(user)
        db.session.flush()
        return user

    def _constraints(self, db, session_id, user_id):
        def participant(role, slot, user=None):
            return db.session.execute(
                sa.text(
                    "INSERT INTO map_training_participants (participant_id, training_session_id, user_id, role, "
                    "coder_slot, grant_ids, added_at, added_by) VALUES (:p, :s, :u, :r, :c, '{}', now(), :u)"
                ),
                {"p": uuid.uuid4(), "s": session_id, "u": user or user_id, "r": role, "c": slot},
            )

        participant("coder", 1)
        db.session.commit()
        other = self._user(db, "d@e.f").user_id
        db.session.commit()
        for role, slot, user in (
            ("coder", 1, other),          # slot already taken in the session
            ("coder", 21, other),         # slot out of range
            ("coder", None, other),       # a coder needs a slot
            ("interviewer", 3, other),    # only a coder has a slot
            ("admin", None, other),       # unknown role
            ("coder", 2, user_id),        # same user, same role twice
        ):
            with self.assertRaises(sa.exc.IntegrityError, msg=f"{role} {slot}"):
                participant(role, slot, user)
            db.session.rollback()
        participant("interviewer", None, other)
        db.session.commit()
