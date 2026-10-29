"""``flask seed test-project`` builds TST001 once, and a rerun changes nothing.

Roster and grid: docs/current-state/test-project-tst001.md.
"""
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.commands.seed import _TST_USERS, TEST_PROJECT_ID, TEST_PROJECT_PASSWORD
from app.models import (
    MasCadre,
    MasOrgUnit,
    MasOrgUnitWorker,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import organization_service as org
from app.services.web_intake_readiness_service import assess_web_intake_readiness
from tests.base import BaseTestCase


class SeedTestProjectTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_form_type("WHO_2022_VA", "WHO VA 2022")
        db.session.commit()

    def _grants(self):
        """(email, role, unit_code or project_id, cadre_code) per active grant on TST001."""
        rows = db.session.execute(
            sa.select(
                VaUsers.email,
                VaUserAccessGrants.role,
                VaUserAccessGrants.scope_type,
                VaUserAccessGrants.project_id,
                MasOrgUnit.unit_code,
                MasCadre.cadre_code,
            )
            .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
            .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
            .outerjoin(MasCadre, MasCadre.cadre_id == VaUserAccessGrants.cadre_id)
            .where(
                VaUserAccessGrants.grant_status == VaStatuses.active,
                sa.or_(
                    VaUserAccessGrants.project_id == TEST_PROJECT_ID,
                    MasOrgUnit.project_id == TEST_PROJECT_ID,
                ),
            )
        ).all()
        return [
            (
                row.email,
                row.role.value,
                row.unit_code if row.scope_type == VaAccessScopeTypes.org_unit else row.project_id,
                row.cadre_code,
            )
            for row in rows
        ]

    def test_builds_a_ready_project_and_a_rerun_duplicates_nothing(self):
        runner = self.app.test_cli_runner()
        first = runner.invoke(args=["seed", "test-project"])
        self.assertEqual(first.exit_code, 0, first.output)
        after_first = self._grants()
        second = runner.invoke(args=["seed", "test-project"])
        self.assertEqual(second.exit_code, 0, second.output)
        after_second = self._grants()

        readiness = assess_web_intake_readiness(TEST_PROJECT_ID)
        self.assertTrue(readiness["ready"], readiness["checks"])

        expected = [("testadmin@digitva.com", "project_pi", TEST_PROJECT_ID, None)] + [
            (f"{local}@digitva.com", role, unit or TEST_PROJECT_ID, cadre)
            for local, _landing, unit, cadre, roles in _TST_USERS
            for role in roles
        ]
        self.assertEqual(sorted(after_first), sorted(expected))
        self.assertEqual(sorted(after_second), sorted(expected))

        grid = {
            (row["level_code"], row["cadre_code"]): (
                row["can_fill_va_form"],
                row["can_code_va_form"],
                row["can_supervise_interviews"],
                row["can_report_deaths"],
            )
            for row in org.list_level_cadres(TEST_PROJECT_ID)
        }
        # The template grid, village row included (its level is only deactivated).
        self.assertEqual(grid, org.DEFAULT_LEVEL_CADRE_TEMPLATE)
        levels = {
            lv.level_code: lv.is_active
            for lv in org.list_levels(TEST_PROJECT_ID, include_inactive=True)
        }
        self.assertEqual(
            levels,
            {"state": True, "district": True, "taluka": True, "chc": True, "phc": True,
             "subcentre": True, "village": False},
        )

        for local, unit_code in (("test.anm.sc01", "SC01"), ("test.mpw.sc04", "SC04")):
            user = db.session.scalar(
                sa.select(VaUsers).where(VaUsers.email == f"{local}@digitva.com")
            )
            self.assertIsNotNone(user)
            self.assertEqual(user.other, {"created_by_user_id": None, "created_via": "seed"})
            worker = db.session.scalar(
                sa.select(MasOrgUnitWorker).where(MasOrgUnitWorker.user_id == user.user_id)
            )
            self.assertIsNotNone(worker)
            self.assertEqual(worker.unit.unit_code, unit_code)
            # The one grant is a death_reporter at their sub-centre.
            self.assertEqual(
                db.session.scalars(
                    sa.select(VaUserAccessGrants.role).where(VaUserAccessGrants.user_id == user.user_id)
                ).all(),
                [VaAccessRoles.death_reporter],
            )

        workers = db.session.scalar(
            sa.select(sa.func.count()).where(MasOrgUnitWorker.project_id == TEST_PROJECT_ID)
        )
        self.assertEqual(workers, len({spec[0] for spec in _TST_USERS if spec[2]}))

    def test_roster_roles_are_known_and_test_all_holds_every_surface(self):
        known = {role.value for role in VaAccessRoles}
        self.assertLessEqual({r for *_x, roles in _TST_USERS for r in roles}, known)
        mine = {(unit, cadre, r) for local, _l, unit, cadre, roles in _TST_USERS
                if local == "test.all" for r in roles}
        self.assertEqual(
            mine,
            {(None, None, "coder"), (None, None, "reviewer"),
             ("SC01", "ANM", "death_reporter"), ("PHC01", "MO", "interview_supervisor")},
        )
        self.assertEqual(
            {(unit, cadre) for unit, cadre, _r in mine if unit},
            {("SC01", "ANM"), ("PHC01", "MO")},
        )
        # Every unit-scope entry is a (level, cadre) the template grid allows
        # for that role's flag.
        flag = {"death_reporter": 3, "interview_supervisor": 2}
        level = {"SC01": "subcentre", "PHC01": "phc"}
        for unit, cadre, role in mine:
            if unit:
                self.assertTrue(
                    org.DEFAULT_LEVEL_CADRE_TEMPLATE[(level[unit], cadre)][flag[role]]
                )

    def test_refuses_a_non_debug_app_without_the_staging_opt_in(self):
        runner = self.app.test_cli_runner()
        self.app.testing, self.app.debug = False, False
        try:
            refused = runner.invoke(args=["seed", "test-project", "--staging"])
        finally:
            self.app.testing = True
        self.assertNotEqual(refused.exit_code, 0)
        self.assertIn("DIGITVA_ALLOW_TEST_SEED", refused.output)
        self.assertIsNone(
            db.session.scalar(
                sa.select(VaUsers.user_id).where(VaUsers.email == "test.pi@digitva.com")
            )
        )

    def test_a_deactivated_roster_account_stays_deactivated_and_gets_no_grants(self):
        runner = self.app.test_cli_runner()
        self.assertEqual(runner.invoke(args=["seed", "test-project"]).exit_code, 0)
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "test.pi@digitva.com"))
        self.assertIsNotNone(user)
        user.user_status = VaStatuses.deactive
        db.session.execute(
            sa.update(VaUserAccessGrants)
            .where(VaUserAccessGrants.user_id == user.user_id)
            .values(grant_status=VaStatuses.deactive)
        )
        db.session.commit()

        rerun = runner.invoke(args=["seed", "test-project"])
        self.assertEqual(rerun.exit_code, 0, rerun.output)
        self.assertIn("test.pi@digitva.com", rerun.output)
        db.session.refresh(user)
        self.assertEqual(user.user_status, VaStatuses.deactive)
        self.assertNotIn(
            ("test.pi@digitva.com", "project_pi", TEST_PROJECT_ID, None), self._grants()
        )
        self.assertIn(("test.dm@digitva.com", "data_manager", TEST_PROJECT_ID, None), self._grants())

    def _user(self, local):
        return db.session.scalar(sa.select(VaUsers).where(VaUsers.email == f"{local}@digitva.com"))

    def _add_sademo(self):
        """The classical project the SADEMO coder grant needs."""
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id="SADEMO", project_code="SADEMO", project_name="Sites Demo",
            project_nickname="SADEMO", project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now,
        ))
        db.session.commit()
        self.assertIsNotNone(db.session.get(VaProjectMaster, "SADEMO"))

    def _sademo_grants(self):
        return db.session.scalars(
            sa.select(VaUserAccessGrants.role)
            .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
            .where(VaUsers.email == "test.all@digitva.com", VaUserAccessGrants.project_id == "SADEMO")
        ).all()

    def _staging(self, actor_email=None):
        args = ["seed", "test-project", "--staging"]
        if actor_email is not None:
            args += ["--actor-email", actor_email]
        return self.app.test_cli_runner().invoke(args=args)

    def test_dev_mode_writes_the_sademo_grant_with_the_shared_password(self):
        self._add_sademo()
        result = self.app.test_cli_runner().invoke(args=["seed", "test-project"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self._sademo_grants(), [VaAccessRoles.coder])
        self.assertTrue(self._user("test.dm").check_password(TEST_PROJECT_PASSWORD))
        self.assertIsNotNone(self._user("testadmin"))
        self.assertIsNotNone(self._user("test.pi"))

    def test_staging_refuses_without_an_active_global_admin_actor(self):
        inactive = self._make_user("inactive.admin@test.local", "Inactive123")
        db.session.add(VaUserAccessGrants(
            user_id=inactive.user_id, role=VaAccessRoles.admin,
            scope_type=VaAccessScopeTypes.global_scope, grant_status=VaStatuses.active,
        ))
        inactive.user_status = VaStatuses.deactive
        db.session.commit()
        self.assertTrue(inactive.is_admin())

        for actor_email in (None, "", "nobody@test.local", self.base_project_pi_user.email,
                            "inactive.admin@test.local"):
            with self.subTest(actor_email=actor_email):
                refused = self._staging(actor_email)
                self.assertNotEqual(refused.exit_code, 0)
                self.assertIn("--actor-email", refused.output)
        dev = self.app.test_cli_runner().invoke(
            args=["seed", "test-project", "--actor-email", self.base_admin_user.email]
        )
        self.assertNotEqual(dev.exit_code, 0)
        self.assertIn("only with --staging", dev.output)
        self.assertIsNone(self._user("test.dm"))
        self.assertIsNone(self._user("testadmin"))

    def test_staging_grants_no_admin_or_pi_and_sets_unknown_passwords(self):
        self._add_sademo()
        self.assertIn(("test.pi", "admin", None, None, ("project_pi",)), _TST_USERS)
        first = self._staging(self.base_admin_user.email.upper())
        self.assertEqual(first.exit_code, 0, first.output)
        second = self._staging(self.base_admin_user.email)
        self.assertEqual(second.exit_code, 0, second.output)

        expected = [
            (f"{local}@digitva.com", role, unit or TEST_PROJECT_ID, cadre)
            for local, _landing, unit, cadre, roles in _TST_USERS
            for role in roles
            if role != "project_pi"
        ]
        self.assertTrue(expected)
        self.assertEqual(sorted(self._grants()), sorted(expected))
        self.assertNotIn("project_pi", {role for _e, role, _s, _c in self._grants()})
        self.assertIsNone(self._user("testadmin"))
        self.assertIsNone(self._user("test.pi"))
        self.assertEqual(self._sademo_grants(), [])
        self.assertIn("already in place", second.output)

        dm, cho = self._user("test.dm"), self._user("test.cho.sc01")
        self.assertIsNotNone(dm)
        self.assertIsNotNone(cho)
        for user in (dm, cho):
            self.assertFalse(user.check_password(TEST_PROJECT_PASSWORD))
        self.assertNotEqual(dm.password, cho.password)
        self.assertNotIn(TEST_PROJECT_PASSWORD, first.output + second.output)
