import uuid
import unittest
from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)

from tests.base import BaseTestCase


class AdminApiTests(BaseTestCase):
    project_id = "ADM001"
    other_project_id = "ADM002"
    site_a = "AA01"
    site_b = "AB01"
    other_site = "AC01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_fixture_rows()

    @classmethod
    def _create_fixture_rows(cls):
        now = datetime.now(timezone.utc)
        db.session.add_all(
            [
                VaProjectMaster(
                    project_id=cls.project_id,
                    project_code=cls.project_id,
                    project_name="Admin API Test Project",
                    project_nickname="AdminApiTest",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaProjectMaster(
                    project_id=cls.other_project_id,
                    project_code=cls.other_project_id,
                    project_name="Admin API Other Project",
                    project_nickname="AdminApiOther",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaSiteMaster(
                    site_id=cls.site_a,
                    site_name="Admin API Site A",
                    site_abbr=cls.site_a,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
                VaSiteMaster(
                    site_id=cls.site_b,
                    site_name="Admin API Site B",
                    site_abbr=cls.site_b,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
                VaSiteMaster(
                    site_id=cls.other_site,
                    site_name="Admin API Other Site",
                    site_abbr=cls.other_site,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
            ]
        )
        db.session.flush()
        db.session.add_all(
            [
                VaProjectSites(
                    project_id=cls.project_id,
                    site_id=cls.site_a,
                    project_site_status=VaStatuses.active,
                    project_site_registered_at=now,
                    project_site_updated_at=now,
                ),
                VaProjectSites(
                    project_id=cls.other_project_id,
                    site_id=cls.other_site,
                    project_site_status=VaStatuses.active,
                    project_site_registered_at=now,
                    project_site_updated_at=now,
                ),
            ]
        )
        db.session.commit()

    def setUp(self):
        super().setUp()
        sfx = uuid.uuid4().hex[:8]
        self.manager = self._create_user(f"admin.api.manager.{sfx}@example.com")
        self.target = self._create_user(f"admin.api.target.{sfx}@example.com")
        self.viewer = self._create_user(f"admin.api.viewer.{sfx}@example.com")
        self.admin_user = self._create_user(f"admin.api.root.{sfx}@example.com")
        self._grant(
            self.manager,
            VaAccessRoles.project_pi,
            VaAccessScopeTypes.project,
            "admin api project pi grant",
            project_id=self.project_id,
        )
        self._grant(
            self.admin_user,
            VaAccessRoles.admin,
            VaAccessScopeTypes.global_scope,
            "admin api admin grant",
        )
        self.manager_id = str(self.manager.user_id)
        self.target_id = str(self.target.user_id)
        self.viewer_id = str(self.viewer.user_id)
        self.admin_user_id = str(self.admin_user.user_id)

    def _create_user(self, email):
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status=VaStatuses.active,
        )
        user.set_password("AdminApiTest123")
        db.session.add(user)
        db.session.flush()
        return user

    def _grant(
        self,
        user,
        role,
        scope_type,
        notes,
        project_id=None,
        project_site_id=None,
    ):
        grant = VaUserAccessGrants(
            user_id=user.user_id,
            role=role,
            scope_type=scope_type,
            project_id=project_id,
            project_site_id=project_site_id,
            notes=notes,
            grant_status=VaStatuses.active,
        )
        db.session.add(grant)
        db.session.flush()
        return grant

    def _project_site_id(self, project_id, site_id):
        return db.session.scalar(
            sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == project_id,
                VaProjectSites.site_id == site_id,
            )
        )

    def test_bootstrap_denies_non_admin_non_project_pi(self):
        self._login(self.viewer_id)

        response = self.client.get("/admin/api/bootstrap")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["error"],
            "Admin API access is not allowed for this user.",
        )

    def test_bootstrap_returns_csrf_contract_and_scope_for_project_pi(self):
        self._login(self.manager_id)

        response = self.client.get("/admin/api/bootstrap")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["csrf_header_name"], "X-CSRFToken")
        self.assertTrue(payload["csrf_token"])
        self.assertEqual(payload["accessible_projects"], [self.project_id])
        self.assertEqual(payload["user"]["project_pi_projects"], [self.project_id])

    def test_create_access_grant_requires_csrf_header(self):
        self._login(self.manager_id)

        response = self.client.post(
            "/admin/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "reviewer",
                "scope_type": "project_site",
                "project_site_id": str(
                    self._project_site_id(self.project_id, self.site_a)
                ),
                "notes": "admin api reviewer grant",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("CSRF", response.get_json()["error"])

    def test_project_pi_can_create_project_site_grant_within_owned_project(self):
        self._login(self.manager_id)
        headers = self._csrf_headers()

        response = self.client.post(
            "/admin/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "reviewer",
                "scope_type": "project_site",
                "project_site_id": str(
                    self._project_site_id(self.project_id, self.site_a)
                ),
                "notes": "admin api reviewer grant",
            },
            headers=headers,
        )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()["grant"]
        self.assertEqual(payload["role"], "reviewer")
        self.assertEqual(payload["scope_type"], "project_site")
        self.assertEqual(payload["project_id"], self.project_id)
        self.assertEqual(payload["site_id"], self.site_a)

    def test_project_pi_cannot_create_project_pi_grant(self):
        self._login(self.manager_id)
        headers = self._csrf_headers()

        response = self.client.post(
            "/admin/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "project_pi",
                "scope_type": "project",
                "project_id": self.project_id,
            },
            headers=headers,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["error"],
            "Project PI may not manage admin or project_pi grants.",
        )

    def test_project_pi_cannot_create_grant_outside_owned_project(self):
        self._login(self.manager_id)
        headers = self._csrf_headers()

        response = self.client.post(
            "/admin/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "reviewer",
                "scope_type": "project_site",
                "project_site_id": str(
                    self._project_site_id(self.other_project_id, self.other_site)
                ),
                "notes": "admin api reviewer grant",
            },
            headers=headers,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["error"],
            "You do not have access to that project.",
        )

    def test_project_site_mapping_create_is_idempotent(self):
        self._login(self.manager_id)
        headers = self._csrf_headers()

        first_response = self.client.post(
            "/admin/api/project-sites",
            json={"project_id": self.project_id, "site_id": self.site_b},
            headers=headers,
        )
        second_response = self.client.post(
            "/admin/api/project-sites",
            json={"project_id": self.project_id, "site_id": self.site_b},
            headers=headers,
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            first_response.get_json()["project_site"]["project_site_id"],
            second_response.get_json()["project_site"]["project_site_id"],
        )

    def test_project_pi_can_deactivate_owned_project_grant(self):
        self._login(self.manager_id)
        grant = self._grant(
            db.session.get(VaUsers, uuid.UUID(self.target_id)),
            VaAccessRoles.reviewer,
            VaAccessScopeTypes.project_site,
            "admin api existing reviewer grant",
            project_site_id=self._project_site_id(self.project_id, self.site_a),
        )
        grant_id = str(grant.grant_id)
        db.session.expire_all()
        headers = self._csrf_headers()

        response = self.client.post(
            f"/admin/api/access-grants/{grant_id}/deactivate",
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], VaStatuses.deactive.value)
        refreshed_grant = db.session.get(VaUserAccessGrants, uuid.UUID(grant_id))
        self.assertEqual(refreshed_grant.grant_status, VaStatuses.deactive)

    def test_project_site_toggle_deactivates_then_activates(self):
        self._login(self.manager_id)
        headers = self._csrf_headers()

        # Create a mapping first
        create = self.client.post(
            "/admin/api/project-sites",
            json={"project_id": self.project_id, "site_id": self.site_b},
            headers=headers,
        )
        self.assertIn(create.status_code, [200, 201])
        ps_id = create.get_json()["project_site"]["project_site_id"]

        # Ensure active before toggling (re-activate if previous test left it deactive)
        self.client.post(f"/admin/api/project-sites/{ps_id}/toggle", headers=headers)
        # Now status is unknown — do two toggles and verify the cycle
        r1 = self.client.post(f"/admin/api/project-sites/{ps_id}/toggle", headers=headers)
        self.assertEqual(r1.status_code, 200)
        status_after_first = r1.get_json()["status"]

        r2 = self.client.post(f"/admin/api/project-sites/{ps_id}/toggle", headers=headers)
        self.assertEqual(r2.status_code, 200)
        status_after_second = r2.get_json()["status"]
        self.assertNotEqual(status_after_first, status_after_second)

        # Toggle again → reactivate
        r2 = self.client.post(f"/admin/api/project-sites/{ps_id}/toggle", headers=headers)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()["status"], "active")

    def test_project_sites_include_inactive_returns_all(self):
        self._login(self.manager_id)
        headers = self._csrf_headers()

        # Create and deactivate a mapping
        create = self.client.post(
            "/admin/api/project-sites",
            json={"project_id": self.project_id, "site_id": self.site_b},
            headers=headers,
        )
        ps_id = create.get_json()["project_site"]["project_site_id"]
        self.client.post(f"/admin/api/project-sites/{ps_id}/toggle", headers=headers)

        active_only = self.client.get(
            f"/admin/api/project-sites?project_id={self.project_id}"
        )
        all_sites = self.client.get(
            f"/admin/api/project-sites?project_id={self.project_id}&include_inactive=1"
        )
        active_ids = {r["project_site_id"] for r in active_only.get_json()["project_sites"]}
        all_ids    = {r["project_site_id"] for r in all_sites.get_json()["project_sites"]}
        self.assertNotIn(ps_id, active_ids)
        self.assertIn(ps_id, all_ids)

    def test_admin_sees_all_projects(self):
        self._login(self.admin_user_id)

        response = self.client.get("/admin/api/projects")

        self.assertEqual(response.status_code, 200)
        project_ids = [row["project_id"] for row in response.get_json()["projects"]]
        self.assertIn(self.project_id, project_ids)
        self.assertIn(self.other_project_id, project_ids)

    def test_admin_can_create_and_edit_site_master(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        # Create site
        create_resp = self.client.post(
            "/admin/api/sites",
            json={
                "site_id": "XX99",
                "site_name": "Test Master Site",
                "site_abbr": "TX99"
            },
            headers=headers
        )
        self.assertEqual(create_resp.status_code, 201)
        
        # Verify it shows up in master list
        list_resp = self.client.get("/admin/api/sites?master=1")
        self.assertEqual(list_resp.status_code, 200)
        site_ids = [s["site_id"] for s in list_resp.get_json()["sites"]]
        self.assertIn("XX99", site_ids)
        
        # Edit site
        edit_resp = self.client.put(
            "/admin/api/sites/XX99",
            json={
                "site_name": "Updated Master Site",
                "status": "deactive"
            },
            headers=headers
        )
        self.assertEqual(edit_resp.status_code, 200)
        self.assertEqual(edit_resp.get_json()["site"]["site_name"], "Updated Master Site")
        self.assertEqual(edit_resp.get_json()["site"]["status"], "deactive")
        
        # Ensure non-admin cannot access master list
        self._login(self.manager_id)
        forbidden_resp = self.client.get("/admin/api/sites?master=1")
        self.assertEqual(forbidden_resp.status_code, 403)
