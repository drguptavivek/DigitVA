"""``c3a7e1f9d4b2`` adds ``map_org_level_cadre.allowed_roles`` (digitva-4650).

Builds a throwaway database at the previous head with one grid row per
combination of the five flags, plus default roles and unit grants, upgrades and
checks the backfill: flags, defaults and live grant roles of that cadre at that
level, mentor members' borrowed-cadre grants left out unless a worker record
backs them, and no grant touched. Then downgrades (four flags recomputed from
allowed_roles, can_edit_interviews left as it was) and upgrades again.
"""
import itertools
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_allowed_roles_mig"

PREVIOUS_HEAD = "1f037b4717e4"
REVISION = "c3a7e1f9d4b2"

FLAGS = ("can_fill_va_form", "can_code_va_form", "can_supervise_interviews",
         "can_report_deaths", "can_edit_interviews")
ROLE_BY_FLAG = {
    "can_fill_va_form": "interviewer",
    "can_code_va_form": "coder",
    "can_supervise_interviews": "interview_supervisor",
    "can_report_deaths": "death_reporter",
}
ORDER = ("site_pi", "collaborator", "collaborator_pii", "coder", "coding_tester",
         "reviewer", "data_manager", "interviewer", "interview_supervisor", "death_reporter")


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class AllowedRolesMigrationConfig(TestConfig):
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


def _one(db, sql, **params):
    return db.session.execute(sa.text(sql), params).scalar_one()


class AllowedRolesMigrationTest(unittest.TestCase):
    def test_backfill_and_round_trip(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(AllowedRolesMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                seed = self._seed(db)
                grants_before = self._grants(db)

                alembic_upgrade(revision=REVISION)
                allowed = self._allowed(db)
                for combo, row_id in seed["combos"].items():
                    expected = [r for r in ORDER if r in {
                        ROLE_BY_FLAG[f] for f, on in zip(FLAGS[:4], combo, strict=False) if on
                    }]
                    self.assertEqual(allowed[row_id], expected, combo)
                # Defaults and the non-mentor grant (coding_tester) feed it;
                # the mentor's borrowed-cadre reviewer does not; the mentor's
                # worker-backed collaborator does.
                self.assertEqual(
                    allowed[seed["rich"]],
                    ["site_pi", "collaborator", "coding_tester", "data_manager"],
                )
                # The staff grant without a cadre and the mentor's borrowed
                # MO reviewer at the block (no worker there) feed nothing.
                self.assertEqual(allowed[seed["other_level"]], [])
                self.assertEqual(self._grants(db), grants_before)
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(
                        "UPDATE map_org_level_cadre SET allowed_roles = ARRAY['admin']::varchar[]"))
                db.session.rollback()

                # Downgrade: four flags from allowed_roles; can_edit_interviews untouched.
                db.session.execute(sa.text(
                    "UPDATE map_org_level_cadre SET allowed_roles = "
                    "ARRAY['coder','interview_supervisor']::varchar[] WHERE level_cadre_id = :r"
                ), {"r": seed["rich"]})
                edit_only = seed["combos"][(False, False, True, False)]  # can_edit ticked
                db.session.execute(sa.text(
                    "UPDATE map_org_level_cadre SET allowed_roles = ARRAY['coder']::varchar[] "
                    "WHERE level_cadre_id = :r"), {"r": edit_only})
                db.session.commit()
                db.session.remove()
                alembic_downgrade(revision=PREVIOUS_HEAD)
                flags = db.session.execute(sa.text(
                    f"SELECT {', '.join(FLAGS)} FROM map_org_level_cadre WHERE level_cadre_id = :r"
                ), {"r": seed["rich"]}).one()
                self.assertEqual(tuple(flags), (False, True, True, False, False))
                flags = db.session.execute(sa.text(
                    f"SELECT {', '.join(FLAGS)} FROM map_org_level_cadre WHERE level_cadre_id = :r"
                ), {"r": edit_only}).one()
                self.assertEqual(tuple(flags), (False, True, False, False, True))
                full = seed["combos"][(True, True, True, True)]
                flags = db.session.execute(sa.text(
                    f"SELECT {', '.join(FLAGS)} FROM map_org_level_cadre WHERE level_cadre_id = :r"
                ), {"r": full}).one()
                self.assertEqual(tuple(flags), (True, True, True, True, True))
                self.assertIsNone(db.session.scalar(sa.text(
                    "SELECT 1 FROM information_schema.columns WHERE table_name = "
                    "'map_org_level_cadre' AND column_name = 'allowed_roles'")))
                self.assertEqual(self._grants(db), grants_before)
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                # Re-backfilled: the recomputed flags plus defaults and grants again.
                self.assertEqual(self._allowed(db)[seed["rich"]], [
                    "site_pi", "collaborator", "coder", "coding_tester", "data_manager",
                    "interview_supervisor",
                ])
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()

    def _allowed(self, db):
        return dict(db.session.execute(sa.text(
            "SELECT level_cadre_id, allowed_roles FROM map_org_level_cadre")).all())

    def _grants(self, db):
        return sorted(db.session.execute(sa.text(
            "SELECT grant_id, role::text, cadre_id, grant_status::text FROM va_user_access_grants"
        )).all())

    def _seed(self, db):
        db.session.execute(sa.text(
            "INSERT INTO va_project_master (project_id, project_name, project_nickname, "
            "project_status, project_registered_at, project_updated_at) "
            "VALUES ('ALR01', 'ALR01', 'ALR01', 'active', now(), now())"
        ))

        def level(code, depth):
            return _one(db, "INSERT INTO mas_org_level (org_level_id, project_id, level_code, "
                        "level_name, depth, created_at, updated_at) VALUES (gen_random_uuid(), "
                        "'ALR01', :c, :c, :d, now(), now()) RETURNING org_level_id", c=code, d=depth)

        def unit(level_id, code, path):
            return _one(db, "INSERT INTO mas_org_unit (org_unit_id, project_id, org_level_id, "
                        "unit_code, unit_name, path, created_at, updated_at) VALUES "
                        "(gen_random_uuid(), 'ALR01', :l, :c, :c, CAST(:p AS ltree), now(), now()) "
                        "RETURNING org_unit_id", l=level_id, c=code, p=path)

        def cadre(code):
            return _one(db, "INSERT INTO mas_cadre (cadre_id, project_id, cadre_code, cadre_name, "
                        "created_at, updated_at) VALUES (gen_random_uuid(), 'ALR01', :c, :c, "
                        "now(), now()) RETURNING cadre_id", c=code)

        def grid(level_id, cadre_id, flags=(False,) * 5, defaults=()):
            cols = dict(zip(FLAGS, flags, strict=True))
            return _one(db, "INSERT INTO map_org_level_cadre (level_cadre_id, org_level_id, cadre_id, "
                        f"{', '.join(FLAGS)}, default_roles, is_active, created_at, updated_at) "
                        "VALUES (gen_random_uuid(), :l, :c, "
                        f"{', '.join(':' + f for f in FLAGS)}, CAST(:dr AS varchar[]), true, now(), now()) "
                        "RETURNING level_cadre_id", l=level_id, c=cadre_id,
                        dr="{" + ",".join(defaults) + "}", **cols)

        def user(email):
            return _one(db, "INSERT INTO va_users (user_id, name, email, password, vacode_language, "
                        "permission, landing_page, pw_reset_t_and_c, email_verified, user_status, "
                        "vacode_formcount, user_created_at, user_updated_at) VALUES "
                        "(gen_random_uuid(), 'Seed', :e, 'x', ARRAY['english'], '{}'::jsonb, "
                        "'coder', true, true, 'active', 0, now(), now()) RETURNING user_id", e=email)

        def grant(user_id, role, unit_id, cadre_id, status="active"):
            db.session.execute(sa.text(
                "INSERT INTO va_user_access_grants (grant_id, user_id, role, scope_type, org_unit_id, "
                "cadre_id, grant_status, grant_created_at, grant_updated_at) VALUES "
                "(gen_random_uuid(), :u, :r, 'org_unit', :unit, :c, :s, now(), now())"
            ), {"u": user_id, "r": role, "unit": unit_id, "c": cadre_id, "s": status})

        district, block = level("district", 1), level("block", 2)
        d01 = unit(district, "D01", "D01")
        b01 = unit(block, "B01", "D01.B01")
        combos = {}
        for i, combo in enumerate(itertools.product((False, True), repeat=4)):
            # can_edit_interviews only ever set with supervise (old rule).
            combos[combo] = grid(district, cadre(f"C{i:02d}"), (*combo, combo[2]))
        mo = cadre("MO")
        rich = grid(district, mo, defaults=("site_pi", "data_manager"))
        other_level = grid(block, mo)

        staff, mentor = user("staff@alr.test"), user("mentor@alr.test")
        grant(staff, "coding_tester", d01, mo)
        grant(staff, "interviewer", d01, mo, status="deactive")   # inactive: ignored
        grant(staff, "reviewer", b01, None)                         # no cadre: ignored
        grant(mentor, "reviewer", b01, mo)                          # borrowed: ignored
        grant(mentor, "collaborator", d01, mo)                      # worker-backed: counts
        institute = _one(db, "INSERT INTO mas_mentor_institute (institute_id, institute_code, "
                         "institute_name, is_active, created_at) VALUES (gen_random_uuid(), "
                         "'MI01', 'MI', true, now()) RETURNING institute_id")
        db.session.execute(sa.text(
            "INSERT INTO map_mentor_institute_user (institute_id, user_id, is_active, created_at) "
            "VALUES (:i, :u, true, now())"), {"i": institute, "u": mentor})
        db.session.execute(sa.text(
            "INSERT INTO mas_org_unit_worker (worker_id, project_id, org_unit_id, cadre_id, "
            "worker_code, worker_name, user_id, is_active, created_at, updated_at) VALUES "
            "(gen_random_uuid(), 'ALR01', :unit, :c, 'W1', 'Mentor', :u, true, now(), now())"
        ), {"unit": d01, "c": mo, "u": mentor})
        db.session.commit()
        return {"combos": combos, "rich": rich, "other_level": other_level}


if __name__ == "__main__":
    unittest.main()
