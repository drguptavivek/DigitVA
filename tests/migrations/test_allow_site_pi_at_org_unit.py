"""``e2b7c4d9a1f3`` allows site_pi at org_unit scope (the In-charge).

Builds a throwaway database at the previous head with one project_site
site_pi grant and one legacy deactive org_unit site_pi grant (what
c4a9e7d2b6f1 left behind), upgrades, and checks: both rows are untouched and a
new active org_unit site_pi grant is accepted. Then downgrades and checks: the
new grant is kept but deactive with a note naming this revision, the
project_site grant is still active, and the tight CHECK refuses a new
org_unit site_pi grant again.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_allow_site_pi_at_org_unit.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_incharge_mig"

PREVIOUS_HEAD = "d7e3a1c9b5f2"
REVISION = "e2b7c4d9a1f3"

UNIT_GRANT_SQL = (
    "INSERT INTO va_user_access_grants (grant_id, user_id, role, scope_type, org_unit_id, "
    "grant_status, notes, grant_created_at, grant_updated_at) VALUES (:g, :u, 'site_pi', "
    "'org_unit', :unit, :status, :notes, now(), now())"
)
STATE_SQL = (
    "SELECT grant_status || '|' || coalesce(notes, '') FROM va_user_access_grants "
    "WHERE grant_id = :g"
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class InChargeMigrationConfig(TestConfig):
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


class AllowSitePiAtOrgUnitMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_round_trip_keeps_pair_rows_and_deactivates_in_charge_grants(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(InChargeMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                ids = self._seed(db)

                def state(grant_id):
                    return db.session.execute(sa.text(STATE_SQL), {"g": grant_id}).scalar_one()

                # Before: the tight CHECK refuses an active unit site_pi grant.
                incharge = {"g": ids["incharge"], "u": ids["other"], "unit": ids["unit"],
                            "status": "active", "notes": None}
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(UNIT_GRANT_SQL), incharge)
                db.session.rollback()

                alembic_upgrade(revision=REVISION)
                self.assertEqual(state(ids["pair"]), "active|")
                self.assertEqual(state(ids["legacy"]), "deactive|legacy note")
                db.session.execute(sa.text(UNIT_GRANT_SQL), incharge)
                db.session.commit()
                self.assertEqual(state(ids["incharge"]), "active|")
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertEqual(state(ids["pair"]), "active|")
                self.assertEqual(state(ids["legacy"]), "deactive|legacy note")
                kept = state(ids["incharge"])
                self.assertTrue(kept.startswith("deactive|"), kept)
                self.assertIn(REVISION, kept)
                # The tight CHECK is back for new rows.
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(UNIT_GRANT_SQL), {
                        **incharge, "g": ids["fresh"], "u": ids["third"],
                    })
                db.session.rollback()
                db.session.remove()

                # And up again: the deactive rows pass the loosened CHECK.
                alembic_upgrade(revision=REVISION)
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()

    def _seed(self, db):
        db.session.execute(sa.text(
            "INSERT INTO va_project_master (project_id, project_name, project_nickname, "
            "project_status, project_registered_at, project_updated_at) "
            "VALUES ('ICM01', 'ICM01', 'ICM01', 'active', now(), now())"
        ))
        db.session.execute(sa.text(
            "INSERT INTO va_site_master (site_id, site_name, site_abbr, site_status, "
            "site_registered_at, site_updated_at) "
            "VALUES ('ICS1', 'ICS1', 'ICS1', 'active', now(), now())"
        ))
        project_site_id = db.session.execute(sa.text(
            "INSERT INTO va_project_sites (project_site_id, project_id, site_id, "
            "project_site_status, project_site_registered_at, project_site_updated_at) "
            "VALUES (gen_random_uuid(), 'ICM01', 'ICS1', 'active', now(), now()) "
            "RETURNING project_site_id"
        )).scalar_one()
        level_id = db.session.execute(sa.text(
            "INSERT INTO mas_org_level (org_level_id, project_id, level_code, level_name, depth, "
            "created_at, updated_at) VALUES (gen_random_uuid(), 'ICM01', 'district', 'District', 1, "
            "now(), now()) RETURNING org_level_id"
        )).scalar_one()
        unit_id = db.session.execute(sa.text(
            "INSERT INTO mas_org_unit (org_unit_id, project_id, org_level_id, unit_code, unit_name, "
            "path, created_at, updated_at) VALUES (gen_random_uuid(), 'ICM01', :l, 'D01', 'D One', "
            "'D01', now(), now()) RETURNING org_unit_id"
        ), {"l": level_id}).scalar_one()
        user_ids = [
            db.session.execute(sa.text(
                "INSERT INTO va_users (user_id, name, email, password, vacode_language, "
                "permission, landing_page, pw_reset_t_and_c, email_verified, user_status, "
                "vacode_formcount, user_created_at, user_updated_at) VALUES (gen_random_uuid(), "
                "'In-charge Seed', :e, 'x', ARRAY['english'], '{}'::jsonb, "
                "'coder', true, true, 'active', 0, now(), now()) RETURNING user_id"
            ), {"e": email}).scalar_one()
            for email in ("incharge.seed@test.local", "incharge.other@test.local",
                          "incharge.third@test.local")
        ]
        new_id = "SELECT gen_random_uuid()"
        ids = {
            "u": user_ids[0], "other": user_ids[1], "third": user_ids[2], "unit": unit_id,
            "pair": db.session.execute(sa.text(new_id)).scalar_one(),
            "legacy": db.session.execute(sa.text(new_id)).scalar_one(),
            "incharge": db.session.execute(sa.text(new_id)).scalar_one(),
            "fresh": db.session.execute(sa.text(new_id)).scalar_one(),
        }
        db.session.execute(sa.text(
            "INSERT INTO va_user_access_grants (grant_id, user_id, role, scope_type, "
            "project_site_id, grant_status, grant_created_at, grant_updated_at) VALUES "
            "(:g, :u, 'site_pi', 'project_site', :ps, 'active', now(), now())"
        ), {"g": ids["pair"], "u": ids["u"], "ps": project_site_id})
        # c4a9e7d2b6f1 left its legacy unit rows deactive under a NOT VALID CHECK;
        # rebuild that state by hand: drop the CHECK, insert, restore it NOT VALID.
        check = db.session.execute(sa.text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_va_user_access_grants_role_scope'"
        )).scalar_one()
        db.session.execute(sa.text(
            "ALTER TABLE va_user_access_grants DROP CONSTRAINT ck_va_user_access_grants_role_scope"
        ))
        db.session.execute(sa.text(UNIT_GRANT_SQL), {
            "g": ids["legacy"], "u": ids["u"], "unit": unit_id,
            "status": "deactive", "notes": "legacy note",
        })
        db.session.execute(sa.text(
            "ALTER TABLE va_user_access_grants ADD CONSTRAINT "
            f"ck_va_user_access_grants_role_scope {check} NOT VALID"
        ))
        db.session.commit()
        return ids


if __name__ == "__main__":
    unittest.main()
