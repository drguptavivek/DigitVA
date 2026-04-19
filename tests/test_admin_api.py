import uuid
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import sqlalchemy as sa

from app import db
from app.models import (
    MasLanguages,
    MasOdkConnections,
    MapProjectSiteOdk,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSubmissionAttachments,
    VaSmartvaResults,
    VaSubmissions,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSyncRun,
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
                MasLanguages(
                    language_code="english",
                    language_name="English",
                    is_active=True,
                ),
                MasLanguages(
                    language_code="hindi",
                    language_name="Hindi",
                    is_active=True,
                ),
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
                VaResearchProjects(
                    project_id=cls.project_id,
                    project_code=cls.project_id,
                    project_name="Admin API Test Project",
                    project_nickname="AdminApiTest",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaResearchProjects(
                    project_id=cls.other_project_id,
                    project_code=cls.other_project_id,
                    project_name="Admin API Other Project",
                    project_nickname="AdminApiOther",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
            ]
        )
        db.session.commit()
        db.session.add_all(
            [
                VaSites(
                    site_id=cls.site_a,
                    project_id=cls.project_id,
                    site_name="Admin API Site A",
                    site_abbr=cls.site_a,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
                VaSites(
                    site_id=cls.site_b,
                    project_id=cls.project_id,
                    site_name="Admin API Site B",
                    site_abbr=cls.site_b,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
                VaSites(
                    site_id=cls.other_site,
                    project_id=cls.other_project_id,
                    site_name="Admin API Other Site",
                    site_abbr=cls.other_site,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
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
                MapProjectSiteOdk(
                    project_id=cls.project_id,
                    site_id=cls.site_a,
                    odk_project_id=11,
                    odk_form_id="ADMIN_API_FORM_A",
                    form_type_id=None,
                ),
            ]
        )
        db.session.commit()
        db.session.add_all(
            [
                VaForms(
                    form_id="ADM001AA0101",
                    project_id=cls.project_id,
                    site_id=cls.site_a,
                    odk_form_id="ADMIN_API_FORM_A",
                    odk_project_id="11",
                    form_type="WHO VA 2022",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
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
            f"/admin/api/access-grants/{grant_id}/toggle",
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

    def test_admin_can_create_and_edit_project_master(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        # Create project
        create_resp = self.client.post(
            "/admin/api/projects",
            json={
                "project_id": "PRJ999",
                "project_name": "Test Master Project",
                "project_nickname": "TMP",
                "social_autopsy_enabled": False,
                "demo_training_enabled": True,
                "demo_retention_minutes": 10,
            },
            headers=headers
        )
        self.assertEqual(create_resp.status_code, 201)
        self.assertFalse(create_resp.get_json()["project"]["social_autopsy_enabled"])
        self.assertTrue(create_resp.get_json()["project"]["demo_training_enabled"])
        self.assertEqual(create_resp.get_json()["project"]["demo_retention_minutes"], 10)
        
        # Verify it shows up in master list
        list_resp = self.client.get("/admin/api/projects?master=1")
        self.assertEqual(list_resp.status_code, 200)
        project_ids = [p["project_id"] for p in list_resp.get_json()["projects"]]
        self.assertIn("PRJ999", project_ids)
        
        # Edit project
        edit_resp = self.client.put(
            "/admin/api/projects/PRJ999",
            json={
                "project_name": "Updated Master Project",
                "project_code": "UPD999",
                "status": "deactive",
                "social_autopsy_enabled": True,
                "coding_intake_mode": "pick_and_choose",
                "demo_training_enabled": True,
                "demo_retention_minutes": 15,
            },
            headers=headers
        )
        self.assertEqual(edit_resp.status_code, 200)
        self.assertEqual(edit_resp.get_json()["project"]["project_name"], "Updated Master Project")
        self.assertEqual(edit_resp.get_json()["project"]["project_code"], "UPD999")
        self.assertEqual(edit_resp.get_json()["project"]["status"], "deactive")
        self.assertEqual(
            edit_resp.get_json()["project"]["coding_intake_mode"],
            "pick_and_choose",
        )
        self.assertTrue(edit_resp.get_json()["project"]["social_autopsy_enabled"])
        self.assertTrue(edit_resp.get_json()["project"]["demo_training_enabled"])
        self.assertEqual(edit_resp.get_json()["project"]["demo_retention_minutes"], 15)
        
        # Toggle project status
        toggle_resp = self.client.post(
            "/admin/api/projects/PRJ999/toggle",
            headers=headers
        )
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertEqual(toggle_resp.get_json()["status"], "active")
        
        # Ensure non-admin cannot access master list
        self._login(self.manager_id)
        forbidden_resp = self.client.get("/admin/api/projects?master=1")
        self.assertEqual(forbidden_resp.status_code, 403)

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
        
        # Toggle site status
        toggle_resp = self.client.post(
            "/admin/api/sites/XX99/toggle",
            headers=headers
        )
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertEqual(toggle_resp.get_json()["status"], "active")
        
        # Ensure non-admin cannot access master list
        self._login(self.manager_id)
        forbidden_resp = self.client.get("/admin/api/sites?master=1")
        self.assertEqual(forbidden_resp.status_code, 403)

    def test_admin_can_manage_users(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        # Create user
        create_resp = self.client.post(
            "/admin/api/users",
            json={
                "email": "new.admin.user@example.com",
                "name": "New Admin User",
                "password": "SecurePassword123!",
                "phone": "1234567890",
                "languages": ["english", "hindi"],
            },
            headers=headers
        )
        self.assertEqual(create_resp.status_code, 201)
        new_user_id = create_resp.get_json()["user"]["user_id"]
        self.assertEqual(
            create_resp.get_json()["user"]["languages"],
            ["english", "hindi"],
        )
        
        # Ensure non-admin cannot access master list
        self._login(self.manager_id)
        forbidden_resp = self.client.get("/admin/api/users?master=1")
        self.assertEqual(forbidden_resp.status_code, 403)
        
        # Switch back to admin
        self._login(self.admin_user_id)

        # Edit user
        edit_resp = self.client.put(
            f"/admin/api/users/{new_user_id}",
            json={
                "name": "Updated Admin User",
                "status": "deactive",
                "languages": ["hindi"],
            },
            headers=headers
        )
        self.assertEqual(edit_resp.status_code, 200)
        self.assertEqual(edit_resp.get_json()["user"]["name"], "Updated Admin User")
        self.assertEqual(edit_resp.get_json()["user"]["status"], "deactive")
        self.assertEqual(edit_resp.get_json()["user"]["languages"], ["hindi"])
        
        # Toggle user status
        toggle_resp = self.client.post(
            f"/admin/api/users/{new_user_id}/toggle",
            headers=headers
        )
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertEqual(toggle_resp.get_json()["status"], "active")
        
        # Cannot toggle self
        self_toggle = self.client.post(
            f"/admin/api/users/{self.admin_user_id}/toggle",
            headers=headers
        )
        self.assertEqual(self_toggle.status_code, 400)

    def test_orphaned_grants_api(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        # Create a project and site
        prj_resp = self.client.post("/admin/api/projects", json={
            "project_id": "ORPH01", "project_name": "Orphan", "project_nickname": "ORPH"
        }, headers=headers)
        site_resp = self.client.post("/admin/api/sites", json={
            "site_id": "OR01", "site_name": "Orphan Site", "site_abbr": "ORPH"
        }, headers=headers)
        
        # Create a mapping
        map_resp = self.client.post("/admin/api/project-sites", json={
            "project_id": "ORPH01", "site_id": "OR01"
        }, headers=headers)
        ps_id = map_resp.get_json()["project_site"]["project_site_id"]
        
        # Create a grant
        grant_resp = self.client.post("/admin/api/access-grants", json={
            "user_id": self.target_id,
            "role": "reviewer",
            "scope_type": "project_site",
            "project_site_id": ps_id
        }, headers=headers)
        
        # Deactivate mapping
        self.client.post(f"/admin/api/project-sites/{ps_id}/toggle", headers=headers)
        
        # Fetch orphaned
        orphaned_resp = self.client.get("/admin/api/access-grants/orphaned")
        self.assertEqual(orphaned_resp.status_code, 200)
        grants = orphaned_resp.get_json()["grants"]
        self.assertTrue(any(g["project_site_id"] == ps_id for g in grants))

    def test_odk_connections_crud(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()
        
        # Create
        create_resp = self.client.post("/admin/api/odk-connections", json={
            "connection_name": "Test ODK",
            "base_url": "https://odk.example.com",
            "username": "admin@example.com",
            "password": "password123"
        }, headers=headers)
        self.assertEqual(create_resp.status_code, 201)
        conn_id = create_resp.get_json()["connection"]["connection_id"]
        
        # List
        list_resp = self.client.get("/admin/api/odk-connections")
        self.assertEqual(list_resp.status_code, 200)
        conns = list_resp.get_json()["connections"]
        self.assertTrue(any(c["connection_id"] == conn_id for c in conns))
        
        # Update
        update_resp = self.client.put(f"/admin/api/odk-connections/{conn_id}", json={
            "connection_name": "Updated ODK"
        }, headers=headers)
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(update_resp.get_json()["connection"]["connection_name"], "Updated ODK")
        
        # Toggle
        toggle_resp = self.client.post(f"/admin/api/odk-connections/{conn_id}/toggle", headers=headers)
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertEqual(toggle_resp.get_json()["status"], "deactive")

    def test_odk_project_assignment(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()
        
        # Create a connection
        create_resp = self.client.post("/admin/api/odk-connections", json={
            "connection_name": "Assign ODK",
            "base_url": "https://odk.example.com",
            "username": "admin@example.com",
            "password": "password123"
        }, headers=headers)
        conn_id = create_resp.get_json()["connection"]["connection_id"]
        
        # Assign project
        assign_resp = self.client.post(f"/admin/api/odk-connections/{conn_id}/assign-project", json={
            "project_id": self.project_id
        }, headers=headers)
        self.assertEqual(assign_resp.status_code, 201)
        
        # Fetch connection projects
        conn_prj_resp = self.client.get(f"/admin/api/odk-connections/{conn_id}/projects")
        self.assertEqual(conn_prj_resp.status_code, 200)
        self.assertIn(self.project_id, conn_prj_resp.get_json()["project_ids"])
        
        # Unassign project
        unassign_resp = self.client.delete(f"/admin/api/odk-connections/{conn_id}/assign-project/{self.project_id}", headers=headers)
        self.assertEqual(unassign_resp.status_code, 200)

    def test_odk_site_mappings(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()
        
        # Save mapping
        save_resp = self.client.post(f"/admin/api/projects/{self.project_id}/odk-site-mappings", json={
            "site_id": self.site_a,
            "odk_project_id": 10,
            "odk_form_id": "test_form",
            "form_smartvahiv": "True",
            "form_smartvamalaria": "True",
            "form_smartvahce": "False",
            "form_smartvafreetext": "False",
            "form_smartvacountry": "ZAF",
        }, headers=headers)
        self.assertEqual(save_resp.status_code, 201)
        saved_mapping = save_resp.get_json()["mapping"]
        self.assertEqual(saved_mapping["form_smartvahiv"], "True")
        self.assertEqual(saved_mapping["form_smartvamalaria"], "True")
        self.assertEqual(saved_mapping["form_smartvahce"], "False")
        self.assertEqual(saved_mapping["form_smartvafreetext"], "False")
        self.assertEqual(saved_mapping["form_smartvacountry"], "ZAF")
        
        # List mapping
        list_resp = self.client.get(f"/admin/api/projects/{self.project_id}/odk-site-mappings")
        self.assertEqual(list_resp.status_code, 200)
        mappings = list_resp.get_json()["mappings"]
        saved = next(m for m in mappings if m["site_id"] == self.site_a)
        self.assertEqual(saved["odk_project_id"], 10)
        self.assertEqual(saved["form_smartvahiv"], "True")
        self.assertEqual(saved["form_smartvamalaria"], "True")
        self.assertEqual(saved["form_smartvahce"], "False")
        self.assertEqual(saved["form_smartvafreetext"], "False")
        self.assertEqual(saved["form_smartvacountry"], "ZAF")

        form = db.session.get(VaForms, "ADM001AA0101")
        self.assertIsNotNone(form)
        self.assertEqual(form.form_smartvahiv, "True")
        self.assertEqual(form.form_smartvamalaria, "True")
        self.assertEqual(form.form_smartvahce, "False")
        self.assertEqual(form.form_smartvafreetext, "False")
        self.assertEqual(form.form_smartvacountry, "ZAF")
        
        # Delete mapping
        del_resp = self.client.delete(f"/admin/api/projects/{self.project_id}/odk-site-mappings/{self.site_a}", headers=headers)
        self.assertEqual(del_resp.status_code, 200)

    def test_admin_can_stop_running_sync_task(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        run = VaSyncRun(
            triggered_by="manual",
            triggered_user_id=uuid.UUID(self.admin_user_id),
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        db.session.add(run)
        db.session.commit()

        mock_celery = MagicMock()
        mock_inspect = MagicMock()
        mock_inspect.active.return_value = {
            "worker@node1": [
                {
                    "id": "task-123",
                    "name": "app.tasks.sync_tasks.run_odk_sync",
                }
            ]
        }
        mock_celery.control.inspect.return_value = mock_inspect
        original_celery = self.app.extensions.get("celery")
        self.app.extensions["celery"] = mock_celery

        try:
            response = self.client.post("/admin/api/sync/stop", headers=headers)
        finally:
            self.app.extensions["celery"] = original_celery

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["task_ids"], ["task-123"])
        self.assertEqual(payload["runs_cancelled"], 1)

        db.session.expire_all()
        cancelled = db.session.get(VaSyncRun, run.sync_run_id)
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(cancelled.error_message, "Cancelled by admin.")
        mock_celery.control.revoke.assert_called_once_with(
            "task-123",
            terminate=True,
            signal="SIGTERM",
        )

    def test_sync_backfill_stats_returns_form_completeness(self):
        self._login(self.admin_user_id)
        baseline_response = self.client.get("/admin/api/sync/backfill-stats")
        self.assertEqual(baseline_response.status_code, 200)
        baseline = baseline_response.get_json()
        baseline_local_total = int((baseline.get("totals") or {}).get("local_total") or 0)
        baseline_metadata_complete = int((baseline.get("totals") or {}).get("metadata_complete") or 0)
        baseline_attachments_complete = int((baseline.get("totals") or {}).get("attachments_complete") or 0)
        baseline_smartva_complete = int((baseline.get("totals") or {}).get("smartva_complete") or 0)
        baseline_smartva_failed = int((baseline.get("totals") or {}).get("smartva_failed") or 0)
        baseline_smartva_missing = int((baseline.get("totals") or {}).get("smartva_missing") or 0)
        baseline_smartva_no_consent = int((baseline.get("totals") or {}).get("smartva_no_consent") or 0)
        baseline_project = next(
            p for p in (baseline.get("projects") or []) if p["project_id"] == self.project_id
        )
        baseline_site = next(s for s in baseline_project["sites"] if s["site_id"] == self.site_a)
        baseline_form = next(f for f in baseline_site["forms"] if f["form_id"] == "ADM001AA0101")
        baseline_form_local_total = int(baseline_form.get("local_total") or 0)
        baseline_form_metadata_complete = int(baseline_form.get("metadata_complete") or 0)
        baseline_form_attachments_complete = int(baseline_form.get("attachments_complete") or 0)
        baseline_form_smartva_complete = int(baseline_form.get("smartva_complete") or 0)
        baseline_form_smartva_failed = int(baseline_form.get("smartva_failed") or 0)
        baseline_form_metadata_missing = int(baseline_form.get("metadata_missing") or 0)
        baseline_form_attachments_missing = int(baseline_form.get("attachments_missing") or 0)
        baseline_form_smartva_missing = int(baseline_form.get("smartva_missing") or 0)
        baseline_form_smartva_no_consent = int(baseline_form.get("smartva_no_consent") or 0)

        now = datetime.now(timezone.utc)
        submission = VaSubmissions(
            va_sid="uuid:backfill-stats-adm001",
            va_form_id="ADM001AA0101",
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="ADM001AA0101_instance",
            va_uniqueid_real=None,
            va_uniqueid_masked="ADM001AA0101",
            va_consent="yes",
            va_narration_language="english",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_summary=["fever"],
            va_catcount={},
            va_category_list=["fever"],
        )
        db.session.add(submission)
        db.session.flush()
        payload_version = VaSubmissionPayloadVersion(
            va_sid=submission.va_sid,
            source_updated_at=now,
            payload_fingerprint="test-fingerprint-backfill-stats-adm001",
            payload_data={"AttachmentsExpected": 1},
            version_status="active",
            has_required_metadata=True,
            attachments_expected=1,
        )
        db.session.add(payload_version)
        db.session.flush()
        submission.active_payload_version_id = payload_version.payload_version_id
        db.session.add(
            VaSubmissionAttachments(
                va_sid="uuid:backfill-stats-adm001",
                filename="photo.jpg",
                local_path="/tmp/photo.jpg",
                mime_type="image/jpeg",
                etag=None,
                exists_on_odk=True,
                last_downloaded_at=now,
            )
        )
        db.session.commit()

        response = self.client.get("/admin/api/sync/backfill-stats")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["totals"]["local_total"], baseline_local_total + 1)
        self.assertEqual(payload["totals"]["metadata_complete"], baseline_metadata_complete + 1)
        self.assertEqual(payload["totals"]["attachments_complete"], baseline_attachments_complete + 1)
        self.assertEqual(payload["totals"]["smartva_complete"], baseline_smartva_complete)
        self.assertEqual(payload["totals"]["smartva_failed"], baseline_smartva_failed)
        self.assertEqual(payload["totals"]["smartva_missing"], baseline_smartva_missing + 1)
        self.assertEqual(payload["totals"]["smartva_no_consent"], baseline_smartva_no_consent)

        project = next(p for p in payload["projects"] if p["project_id"] == self.project_id)
        site = next(s for s in project["sites"] if s["site_id"] == self.site_a)
        form = next(f for f in site["forms"] if f["form_id"] == "ADM001AA0101")
        self.assertEqual(form["local_total"], baseline_form_local_total + 1)
        self.assertEqual(form["metadata_complete"], baseline_form_metadata_complete + 1)
        self.assertEqual(form["attachments_complete"], baseline_form_attachments_complete + 1)
        self.assertEqual(form["smartva_complete"], baseline_form_smartva_complete)
        self.assertEqual(form["smartva_failed"], baseline_form_smartva_failed)
        self.assertEqual(form["metadata_missing"], baseline_form_metadata_missing)
        self.assertEqual(form["attachments_missing"], baseline_form_attachments_missing)
        self.assertEqual(form["smartva_missing"], baseline_form_smartva_missing + 1)
        self.assertEqual(form["smartva_no_consent"], baseline_form_smartva_no_consent)

    def test_sync_backfill_stats_excludes_unmapped_active_legacy_forms(self):
        self._login(self.admin_user_id)

        now = datetime.now(timezone.utc)
        db.session.add(
            VaForms(
                form_id="ADM001AB0101",
                project_id=self.project_id,
                site_id=self.site_b,
                odk_form_id="ADMIN_API_FORM_B",
                odk_project_id="11",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.commit()

        response = self.client.get("/admin/api/sync/backfill-stats")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        project = next(p for p in payload["projects"] if p["project_id"] == self.project_id)
        site_ids = {site["site_id"] for site in project["sites"]}
        self.assertIn(self.site_a, site_ids)
        self.assertNotIn(self.site_b, site_ids)

    def test_sync_backfill_stats_counts_failed_or_null_smartva_separately(self):
        self._login(self.admin_user_id)
        baseline_response = self.client.get("/admin/api/sync/backfill-stats")
        self.assertEqual(baseline_response.status_code, 200)
        baseline = baseline_response.get_json()
        baseline_local_total = int((baseline.get("totals") or {}).get("local_total") or 0)
        baseline_smartva_complete = int((baseline.get("totals") or {}).get("smartva_complete") or 0)
        baseline_smartva_failed = int((baseline.get("totals") or {}).get("smartva_failed") or 0)
        baseline_smartva_missing = int((baseline.get("totals") or {}).get("smartva_missing") or 0)
        baseline_smartva_no_consent = int((baseline.get("totals") or {}).get("smartva_no_consent") or 0)
        baseline_project = next(
            p for p in (baseline.get("projects") or []) if p["project_id"] == self.project_id
        )
        baseline_site = next(s for s in baseline_project["sites"] if s["site_id"] == self.site_a)
        baseline_form = next(f for f in baseline_site["forms"] if f["form_id"] == "ADM001AA0101")
        baseline_form_local_total = int(baseline_form.get("local_total") or 0)
        baseline_form_smartva_complete = int(baseline_form.get("smartva_complete") or 0)
        baseline_form_smartva_failed = int(baseline_form.get("smartva_failed") or 0)
        baseline_form_smartva_missing = int(baseline_form.get("smartva_missing") or 0)
        baseline_form_smartva_no_consent = int(baseline_form.get("smartva_no_consent") or 0)

        now = datetime.now(timezone.utc)
        sid = "uuid:backfill-stats-smartva-failed-adm001"
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id="ADM001AA0101",
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="tester",
                va_odk_reviewstate=None,
                va_instance_name="ADM001AA0101_failed",
                va_uniqueid_real=None,
                va_uniqueid_masked="ADM001AA0101_failed",
                va_consent="yes",
                va_narration_language="english",
                va_deceased_age=42,
                va_deceased_gender="male",
                va_summary=["fever"],
                va_catcount={},
                va_category_list=["fever"],
            )
        )
        db.session.flush()
        db.session.add(
            VaSmartvaResults(
                va_sid=sid,
                va_smartva_status=VaStatuses.active,
                va_smartva_outcome=VaSmartvaResults.OUTCOME_FAILED,
                va_smartva_cause1=None,
            )
        )
        db.session.commit()

        response = self.client.get("/admin/api/sync/backfill-stats")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["totals"]["local_total"], baseline_local_total + 1)
        self.assertEqual(payload["totals"]["smartva_complete"], baseline_smartva_complete)
        self.assertEqual(payload["totals"]["smartva_failed"], baseline_smartva_failed + 1)
        self.assertEqual(payload["totals"]["smartva_missing"], baseline_smartva_missing)
        self.assertEqual(payload["totals"]["smartva_no_consent"], baseline_smartva_no_consent)

        project = next(p for p in payload["projects"] if p["project_id"] == self.project_id)
        site = next(s for s in project["sites"] if s["site_id"] == self.site_a)
        form = next(f for f in site["forms"] if f["form_id"] == "ADM001AA0101")
        self.assertEqual(form["local_total"], baseline_form_local_total + 1)
        self.assertEqual(form["smartva_complete"], baseline_form_smartva_complete)
        self.assertEqual(form["smartva_failed"], baseline_form_smartva_failed + 1)
        self.assertEqual(form["smartva_missing"], baseline_form_smartva_missing)
        self.assertEqual(form["smartva_no_consent"], baseline_form_smartva_no_consent)

    def test_sync_backfill_stats_excludes_consent_no_from_smartva_missing(self):
        self._login(self.admin_user_id)
        baseline_response = self.client.get("/admin/api/sync/backfill-stats")
        self.assertEqual(baseline_response.status_code, 200)
        baseline = baseline_response.get_json()
        baseline_local_total = int((baseline.get("totals") or {}).get("local_total") or 0)
        baseline_smartva_complete = int((baseline.get("totals") or {}).get("smartva_complete") or 0)
        baseline_smartva_failed = int((baseline.get("totals") or {}).get("smartva_failed") or 0)
        baseline_smartva_missing = int((baseline.get("totals") or {}).get("smartva_missing") or 0)
        baseline_smartva_no_consent = int((baseline.get("totals") or {}).get("smartva_no_consent") or 0)
        baseline_project = next(
            p for p in (baseline.get("projects") or []) if p["project_id"] == self.project_id
        )
        baseline_site = next(s for s in baseline_project["sites"] if s["site_id"] == self.site_a)
        baseline_form = next(f for f in baseline_site["forms"] if f["form_id"] == "ADM001AA0101")
        baseline_form_local_total = int(baseline_form.get("local_total") or 0)
        baseline_form_smartva_complete = int(baseline_form.get("smartva_complete") or 0)
        baseline_form_smartva_failed = int(baseline_form.get("smartva_failed") or 0)
        baseline_form_smartva_missing = int(baseline_form.get("smartva_missing") or 0)
        baseline_form_smartva_no_consent = int(baseline_form.get("smartva_no_consent") or 0)

        now = datetime.now(timezone.utc)
        db.session.add(
            VaSubmissions(
                va_sid="uuid:backfill-stats-consent-no-adm001",
                va_form_id="ADM001AA0101",
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="tester",
                va_odk_reviewstate=None,
                va_instance_name="ADM001AA0101_consent_no",
                va_uniqueid_real=None,
                va_uniqueid_masked="ADM001AA0101_consent_no",
                va_consent="no",
                va_narration_language="english",
                va_deceased_age=42,
                va_deceased_gender="male",
                va_summary=["fever"],
                va_catcount={},
                va_category_list=["fever"],
            )
        )
        db.session.commit()

        response = self.client.get("/admin/api/sync/backfill-stats")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["totals"]["local_total"], baseline_local_total + 1)
        self.assertEqual(payload["totals"]["smartva_complete"], baseline_smartva_complete)
        self.assertEqual(payload["totals"]["smartva_failed"], baseline_smartva_failed)
        self.assertEqual(payload["totals"]["smartva_missing"], baseline_smartva_missing)
        self.assertEqual(payload["totals"]["smartva_no_consent"], baseline_smartva_no_consent + 1)

        project = next(p for p in payload["projects"] if p["project_id"] == self.project_id)
        site = next(s for s in project["sites"] if s["site_id"] == self.site_a)
        form = next(f for f in site["forms"] if f["form_id"] == "ADM001AA0101")
        self.assertEqual(form["local_total"], baseline_form_local_total + 1)
        self.assertEqual(form["smartva_complete"], baseline_form_smartva_complete)
        self.assertEqual(form["smartva_failed"], baseline_form_smartva_failed)
        self.assertEqual(form["smartva_missing"], baseline_form_smartva_missing)
        self.assertEqual(form["smartva_no_consent"], baseline_form_smartva_no_consent + 1)

    def test_admin_can_trigger_form_backfill(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        with patch("app.tasks.sync_tasks.run_single_form_backfill.delay") as mocked_delay:
            mocked_delay.return_value.id = "task-form-backfill"

            response = self.client.post(
                "/admin/api/sync/backfill/form/ADM001AA0101",
                headers=headers,
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.get_json()["message"],
            "Repair started for form ADM001AA0101.",
        )
        mocked_delay.assert_called_once()
        self.assertEqual(
            mocked_delay.call_args.kwargs["triggered_by"],
            "backfill",
        )
        self.assertEqual(
            mocked_delay.call_args.kwargs["form_id"],
            "ADM001AA0101",
        )

    def test_admin_backfill_reconciles_orphaned_running_row(self):
        from datetime import datetime, timezone
        from app import db
        from app.models.va_sync_runs import VaSyncRun

        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        stale_run = VaSyncRun(
            triggered_by="backfill",
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        db.session.add(stale_run)
        db.session.commit()

        fake_celery = MagicMock()
        fake_inspect = MagicMock()
        fake_inspect.active.return_value = {}
        fake_celery.control.inspect.return_value = fake_inspect

        self.app.extensions["celery"] = fake_celery

        with patch("app.tasks.sync_tasks.run_single_form_backfill.delay") as mocked_delay:
            mocked_delay.return_value.id = "task-form-backfill"

            response = self.client.post(
                "/admin/api/sync/backfill/form/ADM001AA0101",
                headers=headers,
            )

        self.assertEqual(response.status_code, 202)
        db.session.refresh(stale_run)
        self.assertEqual(stale_run.status, "error")
        self.assertIn("no active Celery sync/backfill task", stale_run.error_message)
        mocked_delay.assert_called_once()

    def test_sync_status_returns_null_schedule_when_beat_tables_missing(self):
        self._login(self.admin_user_id)

        with patch("app.routes.admin.db.engine.connect") as mocked_connect:
            mocked_conn = MagicMock()
            mocked_connect.return_value.__enter__.return_value = mocked_conn
            mocked_conn.execute.return_value.scalar.return_value = False

            response = self.client.get("/admin/api/sync/status")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["schedule_hours"])

    def test_sync_schedule_returns_503_when_beat_tables_missing(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        with patch("app.routes.admin.db.engine.begin") as mocked_begin:
            mocked_conn = MagicMock()
            mocked_begin.return_value.__enter__.return_value = mocked_conn
            mocked_conn.execute.return_value.scalar.return_value = False

            response = self.client.post(
                "/admin/api/sync/schedule",
                headers=headers,
                json={"interval_hours": 6},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json()["error"],
            "Celery Beat schedule tables are not initialized yet.",
        )

    def test_sync_status_includes_odk_connection_alerts(self):
        self._login(self.admin_user_id)

        create_resp = self.client.post("/admin/api/odk-connections", json={
            "connection_name": "Alert ODK",
            "base_url": "https://odk.example.com",
            "username": "admin@example.com",
            "password": "password123"
        }, headers=self._csrf_headers())
        self.assertEqual(create_resp.status_code, 201)
        conn_id = create_resp.get_json()["connection"]["connection_id"]

        conn = db.session.get(MasOdkConnections, uuid.UUID(conn_id))
        conn.consecutive_failure_count = 2
        conn.last_failure_message = "connect timeout"
        conn.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=3)
        db.session.commit()

        response = self.client.get("/admin/api/sync/status")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        alerts = payload["odk_connection_alerts"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["connection_name"], "Alert ODK")
        self.assertTrue(alerts[0]["guard"]["cooldown_active"])
