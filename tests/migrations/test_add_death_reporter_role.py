"""``f2j6n9r4u1x7`` adds the death_reporter role (digitva-t6q).

Builds a throwaway database at the previous head, seeds grid rows and one
unit, upgrades, and checks: ``can_report_deaths`` is set for ANM at the
subcentre level and ASHA at the village level and nowhere else (ANM at the
village level, CHO at the subcentre level stay false); a ``death_reporter``
grant is accepted at org_unit scope and refused at project scope; the
registered_by index exists. Then checks the downgrade refuses while such a
grant exists, removes it, downgrades, and checks the column, the index and
the role's CHECK branch are gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_death_reporter_role.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_reporter_mig"

PREVIOUS_HEAD = "e9h3k6p2s8v4"
REVISION = "f2j6n9r4u1x7"
INDEX = "ix_va_death_register_registered_by"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class ReporterMigrationConfig(TestConfig):
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
    ":u, 'death_reporter', :scope, :p, :unit, 'active', now(), now())"
)
FLAGS_SQL = (
    "SELECT l.level_code, c.cadre_code, lc.can_report_deaths FROM map_org_level_cadre lc "
    "JOIN mas_org_level l ON l.org_level_id = lc.org_level_id "
    "JOIN mas_cadre c ON c.cadre_id = lc.cadre_id"
)


class DeathReporterMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_flag_defaults_unit_only_role_index_and_guarded_downgrade(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(ReporterMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                ids = self._seed(db)
                unit_grant = {**ids, "scope": "org_unit", "p": None}
                project_grant = {**ids, "scope": "project", "p": "RPM01", "unit": None}

                alembic_upgrade(revision=REVISION)
                flags = {
                    (level, cadre): flag
                    for level, cadre, flag in db.session.execute(sa.text(FLAGS_SQL)).all()
                }
                self.assertEqual(
                    flags,
                    {
                        ("subcentre", "ANM"): True,
                        ("subcentre", "CHO"): False,
                        ("village", "ASHA"): True,
                        ("village", "ANM"): False,
                    },
                )
                self.assertIn(INDEX, {i["name"] for i in sa.inspect(db.engine).get_indexes("va_death_register")})
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
                self.assertIn("can_report_deaths", columns)
                db.session.execute(sa.text("DELETE FROM va_user_access_grants WHERE role = 'death_reporter'"))
                db.session.commit()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                columns = {c["name"] for c in sa.inspect(db.engine).get_columns("map_org_level_cadre")}
                self.assertIn("can_supervise_interviews", columns)
                self.assertNotIn("can_report_deaths", columns)
                self.assertNotIn(INDEX, {i["name"] for i in sa.inspect(db.engine).get_indexes("va_death_register")})
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
            "VALUES ('RPM01', 'RPM01', 'RPM01', 'active', now(), now())"
        ))
        levels = {}
        for depth, (code, name) in enumerate((("subcentre", "SC-AAM"), ("village", "Village")), start=1):
            levels[code] = db.session.execute(sa.text(
                "INSERT INTO mas_org_level (org_level_id, project_id, level_code, level_name, depth, "
                "created_at, updated_at) VALUES (gen_random_uuid(), 'RPM01', :c, :n, :d, now(), now()) "
                "RETURNING org_level_id"
            ), {"c": code, "n": name, "d": depth}).scalar_one()
        cadres = {}
        for code in ("ANM", "CHO", "ASHA"):
            cadres[code] = db.session.execute(sa.text(
                "INSERT INTO mas_cadre (cadre_id, project_id, cadre_code, cadre_name, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'RPM01', :c, :c, now(), now()) RETURNING cadre_id"
            ), {"c": code}).scalar_one()
        for level, cadre in (("subcentre", "ANM"), ("subcentre", "CHO"), ("village", "ASHA"), ("village", "ANM")):
            db.session.execute(sa.text(
                "INSERT INTO map_org_level_cadre (level_cadre_id, org_level_id, cadre_id, can_fill_va_form, "
                "can_code_va_form, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :l, :c, "
                "true, false, true, now(), now())"
            ), {"l": levels[level], "c": cadres[cadre]})
        unit_id = db.session.execute(sa.text(
            "INSERT INTO mas_org_unit (org_unit_id, project_id, org_level_id, unit_code, unit_name, path, "
            "created_at, updated_at) VALUES (gen_random_uuid(), 'RPM01', :l, 'S1', 'SC One', 'S1', "
            "now(), now()) RETURNING org_unit_id"
        ), {"l": levels["subcentre"]}).scalar_one()
        user_id = db.session.execute(sa.text(
            "INSERT INTO va_users (user_id, name, email, password, vacode_language, "
            "permission, landing_page, pw_reset_t_and_c, email_verified, user_status, "
            "vacode_formcount, user_created_at, user_updated_at) VALUES (gen_random_uuid(), "
            "'Rep Seed', 'rep.seed@test.local', 'x', ARRAY['english'], '{}'::jsonb, "
            "'coder', true, true, 'active', 0, now(), now()) RETURNING user_id"
        )).scalar_one()
        db.session.commit()
        return {"u": user_id, "unit": unit_id}
