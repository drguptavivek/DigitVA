import uuid
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
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
                "project_nickname": "TMP"
            },
            headers=headers
        )
        self.assertEqual(create_resp.status_code, 201)
        
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
                "coding_intake_mode": "pick_and_choose",
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
                "phone": "1234567890"
            },
            headers=headers
        )
        self.assertEqual(create_resp.status_code, 201)
        new_user_id = create_resp.get_json()["user"]["user_id"]
        
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
                "status": "deactive"
            },
            headers=headers
        )
        self.assertEqual(edit_resp.status_code, 200)
        self.assertEqual(edit_resp.get_json()["user"]["name"], "Updated Admin User")
        self.assertEqual(edit_resp.get_json()["user"]["status"], "deactive")
        
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
            "odk_form_id": "test_form"
        }, headers=headers)
        self.assertEqual(save_resp.status_code, 201)
        
        # List mapping
        list_resp = self.client.get(f"/admin/api/projects/{self.project_id}/odk-site-mappings")
        self.assertEqual(list_resp.status_code, 200)
        mappings = list_resp.get_json()["mappings"]
        self.assertTrue(any(m["site_id"] == self.site_a and m["odk_project_id"] == 10 for m in mappings))
        
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
