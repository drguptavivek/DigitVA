"""``c4a9e7d2b6f1`` adds mentoring institutes and drops site_pi at unit scope.

Builds a throwaway database at the previous head with one legacy org_unit
site_pi grant and one unit coder grant, upgrades, and checks: the legacy row is
kept but deactive with a note, the coder grant is untouched, the new tables
exist, and the stricter CHECK refuses a new org_unit site_pi grant. Then
downgrades and checks the tables are gone and the old CHECK accepts it again.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_mentor_institutes_and_site_pi_scope.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_mentor_mig"

PREVIOUS_HEAD = "b8d2e5f1a7c3"
REVISION = "c4a9e7d2b6f1"

GRANT_SQL = (
    "INSERT INTO va_user_access_grants (grant_id, user_id, role, scope_type, org_unit_id, "
    "grant_status, grant_created_at, grant_updated_at) VALUES (gen_random_uuid(), :u, :role, "
    "'org_unit', :unit, 'active', now(), now())"
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class MentorMigrationConfig(TestConfig):
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


class MentorInstitutesMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_legacy_site_pi_unit_grant_is_kept_deactive_and_new_ones_refused(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(MentorMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                ids = self._seed(db)

                alembic_upgrade(revision=REVISION)
                rows = dict(
                    db.session.execute(
                        sa.text("SELECT role, grant_status || '|' || coalesce(notes, '') "
                                "FROM va_user_access_grants")
                    ).all()
                )
                self.assertTrue(rows["site_pi"].startswith("deactive|"), rows)
                self.assertIn("c4a9e7d2b6f1", rows["site_pi"])
                self.assertEqual(rows["coder"], "active|")
                tables = set(sa.inspect(db.engine).get_table_names())
                self.assertTrue(
                    {"mas_mentor_institute", "map_mentor_institute_org_unit",
                     "map_mentor_institute_user"} <= tables
                )
                # A different user, so only the CHECK (not the unique index) can refuse.
                new_site_pi = {"u": ids["other"], "unit": ids["unit"], "role": "site_pi"}
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(GRANT_SQL), new_site_pi)
                db.session.rollback()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                tables = set(sa.inspect(db.engine).get_table_names())
                self.assertFalse({t for t in tables if "mentor_institute" in t})
                # The old CHECK accepts it again.
                db.session.execute(sa.text(GRANT_SQL), new_site_pi)
                db.session.commit()
                db.session.rollback()
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()

    def _seed(self, db):
        db.session.execute(sa.text(
            "INSERT INTO va_project_master (project_id, project_name, project_nickname, "
            "project_status, project_registered_at, project_updated_at) "
            "VALUES ('MMG01', 'MMG01', 'MMG01', 'active', now(), now())"
        ))
        level_id = db.session.execute(sa.text(
            "INSERT INTO mas_org_level (org_level_id, project_id, level_code, level_name, depth, "
            "created_at, updated_at) VALUES (gen_random_uuid(), 'MMG01', 'district', 'District', 1, "
            "now(), now()) RETURNING org_level_id"
        )).scalar_one()
        unit_id = db.session.execute(sa.text(
            "INSERT INTO mas_org_unit (org_unit_id, project_id, org_level_id, unit_code, unit_name, "
            "path, created_at, updated_at) VALUES (gen_random_uuid(), 'MMG01', :l, 'D01', 'D One', "
            "'D01', now(), now()) RETURNING org_unit_id"
        ), {"l": level_id}).scalar_one()
        user_ids = [
            db.session.execute(sa.text(
                "INSERT INTO va_users (user_id, name, email, password, vacode_language, "
                "permission, landing_page, pw_reset_t_and_c, email_verified, user_status, "
                "vacode_formcount, user_created_at, user_updated_at) VALUES (gen_random_uuid(), "
                "'Mentor Seed', :e, 'x', ARRAY['english'], '{}'::jsonb, "
                "'coder', true, true, 'active', 0, now(), now()) RETURNING user_id"
            ), {"e": email}).scalar_one()
            for email in ("mentor.seed@test.local", "mentor.other@test.local")
        ]
        ids = {"u": user_ids[0], "other": user_ids[1], "unit": unit_id}
        for role in ("site_pi", "coder"):
            db.session.execute(
                sa.text(GRANT_SQL), {"u": ids["u"], "unit": unit_id, "role": role}
            )
        db.session.commit()
        return ids


if __name__ == "__main__":
    unittest.main()
