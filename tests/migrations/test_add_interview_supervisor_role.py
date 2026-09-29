"""``d7f3b1a9c5e2`` adds the interview_supervisor role (digitva-vzk.5).

Builds a throwaway database at the previous head, seeds one level x cadre row
and one unit, upgrades, and checks: the new flag defaults to false on the
existing row; an ``interview_supervisor`` grant is accepted at org_unit scope
and refused at project scope. Then checks the downgrade refuses while such a
grant exists, removes it, downgrades, and checks the column and the role's
CHECK branch are gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_interview_supervisor_role.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_supervisor_mig"

PREVIOUS_HEAD = "c4e8a2f6b9d3"
REVISION = "d7f3b1a9c5e2"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class SupervisorMigrationConfig(TestConfig):
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


GRANT_SQL = (
    "INSERT INTO va_user_access_grants (grant_id, user_id, role, scope_type, project_id, "
    "org_unit_id, grant_status, grant_created_at, grant_updated_at) VALUES (gen_random_uuid(), "
    ":u, 'interview_supervisor', :scope, :p, :unit, 'active', now(), now())"
)


class InterviewSupervisorMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_flag_default_unit_only_role_and_guarded_downgrade(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(SupervisorMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                ids = self._seed(db)
                unit_grant = {**ids, "scope": "org_unit", "p": None}
                project_grant = {**ids, "scope": "project", "p": "SMG01", "unit": None}

                alembic_upgrade(revision=REVISION)
                self.assertIs(
                    db.session.execute(
                        sa.text("SELECT can_supervise_interviews FROM map_org_level_cadre")
                    ).scalar_one(),
                    False,
                )
                db.session.execute(sa.text(GRANT_SQL), unit_grant)
                db.session.commit()
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(GRANT_SQL), project_grant)
                db.session.rollback()
                db.session.remove()

                # flask_migrate logs the migration's RuntimeError and exits 1.
                with self.assertRaises(SystemExit):
                    alembic_downgrade(revision=PREVIOUS_HEAD)
                db.session.remove()
                columns = {c["name"] for c in sa.inspect(db.engine).get_columns("map_org_level_cadre")}
                self.assertIn("can_supervise_interviews", columns)
                db.session.execute(
                    sa.text("DELETE FROM va_user_access_grants WHERE role = 'interview_supervisor'")
                )
                db.session.commit()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                columns = {c["name"] for c in sa.inspect(db.engine).get_columns("map_org_level_cadre")}
                self.assertIn("can_code_va_form", columns)
                self.assertNotIn("can_supervise_interviews", columns)
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(GRANT_SQL), unit_grant)
                db.session.rollback()
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()

    def _seed(self, db):
        db.session.execute(sa.text(
            "INSERT INTO va_project_master (project_id, project_name, project_nickname, "
            "project_status, project_registered_at, project_updated_at) "
            "VALUES ('SMG01', 'SMG01', 'SMG01', 'active', now(), now())"
        ))
        level_id = db.session.execute(sa.text(
            "INSERT INTO mas_org_level (org_level_id, project_id, level_code, level_name, depth, "
            "created_at, updated_at) VALUES (gen_random_uuid(), 'SMG01', 'phc', 'PHC', 1, now(), now()) "
            "RETURNING org_level_id"
        )).scalar_one()
        cadre_id = db.session.execute(sa.text(
            "INSERT INTO mas_cadre (cadre_id, project_id, cadre_code, cadre_name, created_at, updated_at) "
            "VALUES (gen_random_uuid(), 'SMG01', 'MO', 'Medical Officer', now(), now()) RETURNING cadre_id"
        )).scalar_one()
        db.session.execute(sa.text(
            "INSERT INTO map_org_level_cadre (level_cadre_id, org_level_id, cadre_id, can_fill_va_form, "
            "can_code_va_form, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :l, :c, "
            "false, true, true, now(), now())"
        ), {"l": level_id, "c": cadre_id})
        unit_id = db.session.execute(sa.text(
            "INSERT INTO mas_org_unit (org_unit_id, project_id, org_level_id, unit_code, unit_name, path, "
            "created_at, updated_at) VALUES (gen_random_uuid(), 'SMG01', :l, 'P1', 'PHC One', 'P1', "
            "now(), now()) RETURNING org_unit_id"
        ), {"l": level_id}).scalar_one()
        user_id = db.session.execute(sa.text(
            "INSERT INTO va_users (user_id, name, email, password, vacode_language, "
            "permission, landing_page, pw_reset_t_and_c, email_verified, user_status, "
            "vacode_formcount, user_created_at, user_updated_at) VALUES (gen_random_uuid(), "
            "'Sup Seed', 'sup.seed@test.local', 'x', ARRAY['english'], '{}'::jsonb, "
            "'coder', true, true, 'active', 0, now(), now()) RETURNING user_id"
        )).scalar_one()
        db.session.commit()
        return {"u": user_id, "unit": unit_id}
