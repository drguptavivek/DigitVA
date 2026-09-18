"""GET /api/v1/organization/<project_id>/units.

Rules under test live in app/routes/api/organization.py, backed by the
single-query subtree resolution in app/services/org_grant_service.py
(``scope_unit_ids_for_roles``). Policy: docs/policy/organization-model.md.
"""
from datetime import UTC, datetime

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import organization_service as org
from tests.base import BaseTestCase


class OrganizationApiTests(BaseTestCase):
    PROJECT = "ORGA01"
    SITE = "OA01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(
                VaProjectMaster(
                    project_id=cls.PROJECT,
                    project_code=cls.PROJECT,
                    project_name="Organization API Project",
                    project_nickname="OrgApi",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
            db.session.flush()
        if db.session.get(VaSiteMaster, cls.SITE) is None:
            db.session.add(
                VaSiteMaster(
                    site_id=cls.SITE,
                    site_name="Organization API Site",
                    site_abbr=cls.SITE,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
            db.session.flush()
        project_site = db.session.scalar(
            db.select(VaProjectSites).where(
                VaProjectSites.project_id == cls.PROJECT,
                VaProjectSites.site_id == cls.SITE,
            )
        )
        if project_site is None:
            project_site = VaProjectSites(
                project_id=cls.PROJECT,
                site_id=cls.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
            db.session.add(project_site)
            db.session.flush()
        cls.project_site_id = project_site.project_site_id

        org.seed_default_organization(cls.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(cls.PROJECT)}
        cls.district = org.create_unit(
            cls.PROJECT,
            org_level_id=levels["district"].org_level_id,
            unit_code="OD1",
            unit_name="Org District One",
        )
        cls.chc_a = org.create_unit(
            cls.PROJECT,
            org_level_id=levels["chc"].org_level_id,
            parent_org_unit_id=cls.district.org_unit_id,
            unit_code="OCA",
            unit_name="Org CHC A",
        )
        cls.phc_a = org.create_unit(
            cls.PROJECT,
            org_level_id=levels["phc"].org_level_id,
            parent_org_unit_id=cls.chc_a.org_unit_id,
            unit_code="OPA",
            unit_name="Org PHC A",
        )
        cls.chc_b = org.create_unit(
            cls.PROJECT,
            org_level_id=levels["chc"].org_level_id,
            parent_org_unit_id=cls.district.org_unit_id,
            unit_code="OCB",
            unit_name="Org CHC B",
        )
        db.session.commit()

        cls.interviewer_at_a = cls._get_or_make_user(
            "org.api.interviewer.a@test.local", "OrgApiUser123"
        )
        cls.project_scoped_interviewer = cls._get_or_make_user(
            "org.api.interviewer.project@test.local", "OrgApiUser123"
        )
        cls.no_grant_user = cls._get_or_make_user(
            "org.api.no.grant@test.local", "OrgApiUser123"
        )
        cls.coder_and_interviewer = cls._get_or_make_user(
            "org.api.coder.interviewer@test.local", "OrgApiUser123"
        )
        db.session.commit()

    def _grant(self, user_id, role, **kwargs):
        grant = VaUserAccessGrants(
            user_id=user_id,
            role=role,
            grant_status=VaStatuses.active,
            **kwargs,
        )
        db.session.add(grant)
        db.session.commit()
        return grant

    # -- unit-scoped interviewer --------------------------------------------

    def test_unit_scoped_interviewer_gets_subtree_not_sibling_branch(self):
        self._grant(
            self.interviewer_at_a.user_id,
            VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.chc_a.org_unit_id,
        )
        self._login(str(self.interviewer_at_a.user_id))

        response = self.client.get(f"/api/v1/organization/{self.PROJECT}/units?role=interviewer")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["scoped"])
        unit_ids = {u["org_unit_id"] for u in payload["units"]}
        self.assertIn(str(self.chc_a.org_unit_id), unit_ids)
        self.assertIn(str(self.phc_a.org_unit_id), unit_ids)
        self.assertNotIn(str(self.district.org_unit_id), unit_ids)
        self.assertNotIn(str(self.chc_b.org_unit_id), unit_ids)

    # -- project-wide interviewer --------------------------------------------

    def test_project_scoped_interviewer_gets_whole_tree_unscoped(self):
        self._grant(
            self.project_scoped_interviewer.user_id,
            VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )
        self._login(str(self.project_scoped_interviewer.user_id))

        response = self.client.get(f"/api/v1/organization/{self.PROJECT}/units?role=interviewer")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["scoped"])
        unit_ids = {u["org_unit_id"] for u in payload["units"]}
        self.assertIn(str(self.district.org_unit_id), unit_ids)
        self.assertIn(str(self.chc_b.org_unit_id), unit_ids)

    def test_site_scoped_grant_also_reaches_whole_tree(self):
        user = self._get_or_make_user("org.api.site.scoped@test.local", "OrgApiUser123")
        self._grant(
            user.user_id,
            VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=self.project_site_id,
        )
        self._login(str(user.user_id))

        response = self.client.get(f"/api/v1/organization/{self.PROJECT}/units?role=interviewer")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["scoped"])

    # -- no grant -------------------------------------------------------------

    def test_no_grant_on_project_is_refused(self):
        self._login(str(self.no_grant_user.user_id))
        response = self.client.get(f"/api/v1/organization/{self.PROJECT}/units")
        self.assertEqual(response.status_code, 403)

    # -- role leak -------------------------------------------------------------

    def test_role_param_excludes_units_reachable_only_through_another_role(self):
        user = self.coder_and_interviewer
        # A coder grant at CHC B ...
        self._grant(
            user.user_id,
            VaAccessRoles.coder,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.chc_b.org_unit_id,
        )
        # ... and an interviewer grant only at CHC A.
        self._grant(
            user.user_id,
            VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.chc_a.org_unit_id,
        )
        self._login(str(user.user_id))

        # Without role: union across both grants leaks CHC B in.
        response = self.client.get(f"/api/v1/organization/{self.PROJECT}/units")
        self.assertEqual(response.status_code, 200)
        unit_ids = {u["org_unit_id"] for u in response.get_json()["units"]}
        self.assertIn(str(self.chc_b.org_unit_id), unit_ids)

        # With role=interviewer: CHC B (coder-only) must not appear.
        response = self.client.get(f"/api/v1/organization/{self.PROJECT}/units?role=interviewer")
        self.assertEqual(response.status_code, 200)
        unit_ids = {u["org_unit_id"] for u in response.get_json()["units"]}
        self.assertIn(str(self.chc_a.org_unit_id), unit_ids)
        self.assertNotIn(str(self.chc_b.org_unit_id), unit_ids)

    # -- validation -------------------------------------------------------------

    def test_unknown_role_value_is_400(self):
        self._grant(
            self.interviewer_at_a.user_id,
            VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.chc_a.org_unit_id,
        )
        self._login(str(self.interviewer_at_a.user_id))
        response = self.client.get(f"/api/v1/organization/{self.PROJECT}/units?role=not_a_role")
        self.assertEqual(response.status_code, 400)

    # -- include_inactive -------------------------------------------------------------

    def test_include_inactive_flags_a_closed_unit_default_omits_it(self):
        self._grant(
            self.project_scoped_interviewer.user_id,
            VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )
        self._login(str(self.project_scoped_interviewer.user_id))

        org.set_unit_active(self.PROJECT, self.chc_b.org_unit_id, False)
        db.session.commit()
        try:
            response = self.client.get(f"/api/v1/organization/{self.PROJECT}/units")
            self.assertEqual(response.status_code, 200)
            unit_ids = {u["org_unit_id"] for u in response.get_json()["units"]}
            self.assertNotIn(str(self.chc_b.org_unit_id), unit_ids)

            response = self.client.get(
                f"/api/v1/organization/{self.PROJECT}/units?include_inactive=1"
            )
            self.assertEqual(response.status_code, 200)
            units_by_id = {u["org_unit_id"]: u for u in response.get_json()["units"]}
            self.assertIn(str(self.chc_b.org_unit_id), units_by_id)
            self.assertFalse(units_by_id[str(self.chc_b.org_unit_id)]["is_active"])
        finally:
            org.set_unit_active(self.PROJECT, self.chc_b.org_unit_id, True)
            db.session.commit()

    # -- project existence -------------------------------------------------------------

    def test_missing_project_is_404(self):
        self._login(str(self.no_grant_user.user_id))
        response = self.client.get("/api/v1/organization/NOPE99/units")
        self.assertEqual(response.status_code, 404)

    def test_inactive_project_is_404(self):
        now = datetime.now(UTC)
        inactive_id = "ORGA02"
        if db.session.get(VaProjectMaster, inactive_id) is None:
            db.session.add(
                VaProjectMaster(
                    project_id=inactive_id,
                    project_code=inactive_id,
                    project_name="Inactive Org Project",
                    project_nickname="InactiveOrg",
                    project_status=VaStatuses.deactive,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
            db.session.commit()
        self._login(str(self.no_grant_user.user_id))
        response = self.client.get(f"/api/v1/organization/{inactive_id}/units")
        self.assertEqual(response.status_code, 404)

    # -- authentication -------------------------------------------------------------

    def test_unauthenticated_request_is_refused(self):
        response = self.client.get(f"/api/v1/organization/{self.PROJECT}/units")
        self.assertIn(response.status_code, (302, 401))
