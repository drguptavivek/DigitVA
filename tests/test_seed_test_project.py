"""``flask seed test-project`` builds TST001 once, and a rerun changes nothing.

Roster and grid: docs/current-state/test-project-tst001.md.
"""
import sqlalchemy as sa

from app import db
from app.commands.seed import _TST_USERS, TEST_PROJECT_ID
from app.models import (
    MasCadre,
    MasOrgUnit,
    MasOrgUnitWorker,
    VaAccessRoles,
    VaAccessScopeTypes,
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
            {"district": True, "taluka": True, "chc": True, "phc": True,
             "subcentre": True, "village": False},
        )

        for local, unit_code in (("test.anm.sc01", "SC01"), ("test.mpw.sc04", "SC04")):
            user = db.session.scalar(
                sa.select(VaUsers).where(VaUsers.email == f"{local}@digitva.com")
            )
            self.assertIsNotNone(user)
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
        self.assertEqual(workers, sum(1 for spec in _TST_USERS if spec[2]))

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
