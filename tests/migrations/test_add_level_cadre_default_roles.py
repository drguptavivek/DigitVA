"""``g3k7o1s5w9a2`` adds map_org_level_cadre.default_roles (digitva-vjt).

Builds a throwaway database at the previous head, seeds one grid row,
upgrades, and checks: the column exists, is a not-null array and every
existing row starts empty (no data step); a unit-scope role list is stored, a
role that is not a unit-scope role (``admin``) is refused by the CHECK. Then
downgrades and checks the column is gone and the row survives.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_level_cadre_default_roles.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_default_roles_mig"

PREVIOUS_HEAD = "f2j6n9r4u1x7"
REVISION = "g3k7o1s5w9a2"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class DefaultRolesMigrationConfig(TestConfig):
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


class LevelCadreDefaultRolesMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_column_starts_empty_is_checked_and_downgrade_drops_it(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(DefaultRolesMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                level_cadre_id = self._seed_row(db)

                alembic_upgrade(revision=REVISION)
                columns = {c["name"]: c for c in sa.inspect(db.engine).get_columns("map_org_level_cadre")}
                self.assertIn("default_roles", columns)
                self.assertFalse(columns["default_roles"]["nullable"])
                self.assertEqual(self._roles(db, level_cadre_id), [])

                db.session.execute(
                    sa.text("UPDATE map_org_level_cadre SET default_roles = ARRAY['site_pi', 'coder'] "
                            "WHERE level_cadre_id = :i"), {"i": level_cadre_id})
                db.session.commit()
                self.assertEqual(self._roles(db, level_cadre_id), ["site_pi", "coder"])
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(
                        sa.text("UPDATE map_org_level_cadre SET default_roles = ARRAY['admin'] "
                                "WHERE level_cadre_id = :i"), {"i": level_cadre_id})
                db.session.rollback()
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(
                        sa.text("UPDATE map_org_level_cadre SET default_roles = NULL "
                                "WHERE level_cadre_id = :i"), {"i": level_cadre_id})
                db.session.rollback()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                columns = {c["name"] for c in sa.inspect(db.engine).get_columns("map_org_level_cadre")}
                self.assertNotIn("default_roles", columns)
                self.assertIn("can_report_deaths", columns)
                self.assertEqual(
                    db.session.execute(sa.text("SELECT count(*) FROM map_org_level_cadre")).scalar_one(), 1)
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()

    def _roles(self, db, level_cadre_id):
        return db.session.execute(
            sa.text("SELECT default_roles FROM map_org_level_cadre WHERE level_cadre_id = :i"),
            {"i": level_cadre_id}).scalar_one()

    def _seed_row(self, db):
        db.session.execute(sa.text(
            "INSERT INTO va_project_master (project_id, project_name, project_nickname, "
            "project_status, project_registered_at, project_updated_at) "
            "VALUES ('DRM01', 'DRM01', 'DRM01', 'active', now(), now())"
        ))
        level = db.session.execute(sa.text(
            "INSERT INTO mas_org_level (org_level_id, project_id, level_code, level_name, depth, "
            "created_at, updated_at) VALUES (gen_random_uuid(), 'DRM01', 'phc', 'PHC', 1, now(), now()) "
            "RETURNING org_level_id")).scalar_one()
        cadre = db.session.execute(sa.text(
            "INSERT INTO mas_cadre (cadre_id, project_id, cadre_code, cadre_name, created_at, updated_at) "
            "VALUES (gen_random_uuid(), 'DRM01', 'MO', 'MO', now(), now()) RETURNING cadre_id")).scalar_one()
        level_cadre_id = db.session.execute(sa.text(
            "INSERT INTO map_org_level_cadre (level_cadre_id, org_level_id, cadre_id, can_fill_va_form, "
            "can_code_va_form, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :l, :c, "
            "false, true, true, now(), now()) RETURNING level_cadre_id"), {"l": level, "c": cadre}).scalar_one()
        db.session.commit()
        return level_cadre_id
