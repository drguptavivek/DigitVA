"""The In-charge: ``site_pi`` held at ``org_unit`` (digitva-0wc stage 5).

Policy: docs/policy/access-control-model.md, "In-charge"; design
.tasks/digitva-0wc-design.md section 5. With real grant rows (the stage-5
migration lifted the role_scope CHECK) these tests pin:

- the grant validator accepts site_pi at a unit of a tree project, and
  refuses it for mentoring institute staff and where the project has no tree;
- an In-charge opens the data-manager pages for its subtree only, triages,
  pins into its subtree only, and opens the site PI report for its own units
  only;
- a project_pi gets the site PI report for its project's sites and units (F8);
- a classical (pair) site_pi keeps its report and opens nothing else.

Intake supervision by an In-charge and a tree project_pi is in
tests/services/test_interview_supervisor.py.
"""
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgLevel,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services import mentor_institute_service as mentors
from app.services import org_grant_service as og
from app.services.organization_service import OrganizationError
from app.services.sitepi_reporting_service import get_sitepi_unit_dashboard_data
from tests.base import BaseTestCase
from tests.test_unit_scoped_dm_tester import UnitScopeFixture

R = VaAccessRoles


class InChargeTests(UnitScopeFixture, BaseTestCase):
    """CSC001: District D01 > CHC C01 > PHC P01, P02."""

    def setUp(self):
        super().setUp()
        _, self.district, self.chc, self.phc_a, self.phc_b = self._tree()
        self._sub("csc-s5-unrouted")
        self._sub("csc-s5-phc-a", unit=self.phc_a)
        self._sub("csc-s5-phc-b", unit=self.phc_b)
        self._sub("csc-s5-district", unit=self.district)

    # -- fixtures ----------------------------------------------------------

    def _incharge(self, key, unit):
        return self._user_with(f"stage5.{key}@test.local", R.site_pi, unit)

    def _project_user(self, key, role):
        user = self._get_or_make_user(f"stage5.{key}@test.local", "Stage5Test123")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user

    def _pair_site_pi(self, key):
        user = self._get_or_make_user(f"stage5.{key}@test.local", "Stage5Test123")
        project_site_id = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == self.PROJECT, VaProjectSites.site_id == self.SITE,
        ))
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=R.site_pi, scope_type=VaAccessScopeTypes.project_site,
            project_site_id=project_site_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user

    def _set_state(self, sid, state):
        db.session.scalar(
            sa.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == sid)
        ).workflow_state = state
        db.session.commit()

    def _pin(self, sid, unit):
        return self.client.post(
            f"/api/v1/data-management/submissions/{sid}/org-unit",
            json={"org_unit_id": str(unit.org_unit_id)},
            headers=self._csrf_headers(),
        )

    def _report(self, key):
        return self.client.get(f"/sitepi/data?siteSelect={key}")

    # -- the grant validator -------------------------------------------------

    def test_the_validator_accepts_site_pi_at_a_unit_of_a_tree_project(self):
        user = self._get_or_make_user("stage5.valid@test.local", "Stage5Test123")
        unit, cadre = og.validate_org_unit_grant(
            role=R.site_pi, org_unit_id=self.chc.org_unit_id, user_id=user.user_id,
        )
        self.assertEqual(unit.org_unit_id, self.chc.org_unit_id)
        self.assertIsNone(cadre)  # optional for site_pi
        self.assertIn(R.site_pi, og.ROLES_ALLOWING_ORG_UNIT)

    def test_the_validator_refuses_mentoring_institute_staff(self):
        user = self._get_or_make_user("stage5.mentor@test.local", "Stage5Test123")
        mentors.create_institute("S5MI", "Stage Five Mentor Institute")
        mentors.attach_district("S5MI", self.PROJECT, "D01")
        mentors.add_member("S5MI", user.email)
        with self.assertRaisesRegex(OrganizationError, "mentoring institute member"):
            og.validate_org_unit_grant(
                role=R.site_pi, org_unit_id=self.chc.org_unit_id, user_id=user.user_id,
            )
        with self.assertRaisesRegex(OrganizationError, "mentoring institute member"):
            mentors.check_mentor_grant(user.user_id, R.site_pi, self.chc)

    def test_the_validator_refuses_site_pi_at_a_unit_without_a_tree(self):
        db.session.execute(sa.update(MasOrgLevel).where(
            MasOrgLevel.project_id == self.PROJECT,
        ).values(is_active=False))
        db.session.flush()
        with self.assertRaisesRegex(OrganizationError, "organization project"):
            og.validate_org_unit_grant(role=R.site_pi, org_unit_id=self.chc.org_unit_id)

    # -- data-manager powers in the subtree ----------------------------------

    def test_an_in_charge_sees_and_triages_its_subtree_only(self):
        incharge = self._incharge("dm", self.phc_a)
        self.assertTrue(incharge.is_data_manager())
        self.assertTrue(incharge.is_site_pi())
        self.assertTrue(incharge.is_interview_supervisor())
        self._login(str(incharge.user_id))

        self.assertEqual(self.client.get("/data-management/dashboard").status_code, 200)
        self.assertEqual(self.client.get("/data-management/view/csc-s5-phc-a").status_code, 200)
        self.assertIn(self.client.get("/data-management/view/csc-s5-phc-b").status_code, (302, 403))

        self._set_state("csc-s5-phc-a", "screening_pending")
        passed = self.client.post(
            "/api/v1/data-management/submissions/csc-s5-phc-a/screening-pass",
            headers=self._csrf_headers(),
        )
        self.assertEqual(passed.status_code, 200, passed.get_json())

        self._set_state("csc-s5-phc-b", "screening_pending")
        refused = self.client.post(
            "/api/v1/data-management/submissions/csc-s5-phc-b/screening-pass",
            headers=self._csrf_headers(),
        )
        self.assertIn(refused.status_code, (302, 403, 404))
        db.session.expire_all()
        state = db.session.scalar(sa.select(VaSubmissionWorkflow.workflow_state).where(
            VaSubmissionWorkflow.va_sid == "csc-s5-phc-b"))
        self.assertEqual(state, "screening_pending")

        with patch("app.tasks.sync_tasks.run_single_submission_sync.delay") as delay:
            delay.return_value.id = "task-stage5"
            synced = self.client.post(
                "/api/v1/data-management/submissions/csc-s5-phc-a/sync",
                headers=self._csrf_headers(),
            )
        self.assertEqual(synced.status_code, 202, synced.get_json())

    def test_an_in_charge_routes_into_its_subtree_only(self):
        incharge = self._incharge("pin", self.chc)
        self._login(str(incharge.user_id))
        pinned = self._pin("csc-s5-unrouted", self.phc_b)
        self.assertEqual(pinned.status_code, 200, pinned.get_json())
        refused = self._pin("csc-s5-phc-a", self.district)
        self.assertEqual(refused.status_code, 403, refused.get_json())

    # -- the site PI report --------------------------------------------------

    def test_an_in_charge_opens_the_unit_report_for_its_units_only(self):
        incharge = self._incharge("report", self.phc_a)
        self._login(str(incharge.user_id))

        page = self.client.get("/sitepi/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(f"unit:{self.phc_a.org_unit_id}".encode(), page.data)
        self.assertNotIn(f"unit:{self.phc_b.org_unit_id}".encode(), page.data)
        self.assertIn(b"In-charge area", page.data)

        self.assertEqual(self._report(f"unit:{self.phc_a.org_unit_id}").status_code, 200)
        self.assertEqual(self._report(f"unit:{self.phc_b.org_unit_id}").status_code, 403)
        self.assertEqual(self._report(f"unit:{self.district.org_unit_id}").status_code, 403)
        self.assertEqual(self._report("unit:not-a-uuid").status_code, 404)
        self.assertEqual(self._report(f"{self.PROJECT}:{self.SITE}").status_code, 403)

    def test_the_unit_report_counts_the_subtree_only(self):
        chc = get_sitepi_unit_dashboard_data(self.chc.org_unit_id)
        self.assertEqual(chc["total_submissions"], 2)
        self.assertEqual(
            {row["va_sid"] for row in chc["submission_rows"]},
            {"csc-s5-phc-a", "csc-s5-phc-b"},
        )
        phc = get_sitepi_unit_dashboard_data(self.phc_a.org_unit_id)
        self.assertEqual(phc["total_submissions"], 1)

    def test_the_unit_report_lists_coders_granted_in_the_subtree_once(self):
        coder = self._get_or_make_user("stage5.coder@test.local", "Stage5Test123")
        for unit in (self.phc_a, self.phc_b):
            db.session.add(VaUserAccessGrants(
                user_id=coder.user_id, role=R.coder, scope_type=VaAccessScopeTypes.org_unit,
                org_unit_id=unit.org_unit_id, grant_status=VaStatuses.active,
            ))
        db.session.commit()
        names = [r["coder_name"] for r in get_sitepi_unit_dashboard_data(self.chc.org_unit_id)["coder_kpis"]]
        self.assertEqual(names.count(coder.name), 1)
        names = [r["coder_name"] for r in get_sitepi_unit_dashboard_data(self.district.org_unit_id)["coder_kpis"]]
        self.assertIn(coder.name, names)

    def test_project_pi_gets_the_report_for_its_sites_and_units(self):
        pi = self._project_user("pi", R.project_pi)
        self.assertFalse(pi.is_site_pi())
        self._login(str(pi.user_id))
        page = self.client.get("/sitepi/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(f"{self.PROJECT}:{self.SITE}".encode(), page.data)
        self.assertIn(f"unit:{self.district.org_unit_id}".encode(), page.data)  # top level
        self.assertEqual(self._report(f"{self.PROJECT}:{self.SITE}").status_code, 200)
        self.assertEqual(self._report(f"unit:{self.phc_b.org_unit_id}").status_code, 200)
        self.assertIn(b'href="/sitepi/"', self.client.get("/data-management/dashboard").data)

    def test_a_classical_site_pi_is_unchanged(self):
        site_pi = self._pair_site_pi("pair")
        self.assertTrue(site_pi.is_site_pi())
        self.assertFalse(site_pi.is_data_manager())
        self.assertFalse(site_pi.is_interview_supervisor())
        self._login(str(site_pi.user_id))
        page = self.client.get("/sitepi/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(f"{self.PROJECT}:{self.SITE}".encode(), page.data)
        self.assertFalse(b'value="unit:' in page.data, "no unit option for a pair site_pi")
        self.assertEqual(self._report(f"{self.PROJECT}:{self.SITE}").status_code, 200)
        self.assertEqual(self._report(f"unit:{self.phc_a.org_unit_id}").status_code, 403)
        self.assertEqual(self.client.get("/data-management/dashboard").status_code, 403)
        self.assertEqual(self.client.get("/intake/supervision").status_code, 403)
