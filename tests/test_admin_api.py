import uuid
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import sqlalchemy as sa

from app import db
from app.models import (
    MasLanguages,
    MasOdkConnections,
    MapProjectSiteOdk,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocations,
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
    VaSubmissionWorkflow,
    VaSubmissionPayloadVersion,
    VaSyncRun,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.va_selectives import VaAllocation

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
        # Reference languages are shared across test classes — get-or-create so a
        # class that runs after another one committed them does not collide.
        for language_code, language_name in (("english", "English"), ("hindi", "Hindi")):
            if db.session.get(MasLanguages, language_code) is None:
                db.session.add(
                    MasLanguages(
                        language_code=language_code,
                        language_name=language_name,
                        is_active=True,
                    )
                )
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

    def test_sync_task_names_include_canonical_repair_tasks(self):
        from app.routes.admin import _sync_task_names

        names = _sync_task_names()

        self.assertIn("app.tasks.sync_tasks.run_canonical_repair_batches_task", names)
        self.assertIn("app.tasks.sync_tasks.finalize_canonical_repair_run_task", names)
        self.assertIn("app.tasks.sync_tasks.run_legacy_attachment_repair", names)

    def test_sync_stop_recognizes_canonical_repair_tasks(self):
        self._login(self.admin_user_id)

        fake_inspect = MagicMock()
        fake_inspect.active.return_value = {
            "worker-a": [
                {
                    "id": "task-1",
                    "name": "app.tasks.sync_tasks.run_canonical_repair_batches_task",
                }
            ]
        }
        fake_inspect.reserved.return_value = {}
        fake_celery = MagicMock()
        fake_celery.control.inspect.return_value = fake_inspect

        now = datetime.now(timezone.utc)
        run = VaSyncRun(
            triggered_by="backfill",
            started_at=now,
            status="running",
        )
        db.session.add(run)
        db.session.commit()

        with patch.dict(self.app.extensions, {"celery": fake_celery}, clear=False):
            response = self.client.post("/admin/api/sync/stop", headers=self._csrf_headers())

        self.assertEqual(response.status_code, 200)
        fake_celery.control.revoke.assert_called_once_with(
            "task-1",
            terminate=True,
            signal="SIGTERM",
        )

    def setUp(self):
        super().setUp()
        self._restore_class_fixture_mapping()
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

    def _restore_class_fixture_mapping(self):
        """Re-assert the setUpClass ODK mapping for (project_id, site_a).

        Tests here mutate and even DELETE that mapping through /admin/api, and
        those routes commit — which releases the per-test SAVEPOINT and makes the
        change permanent (tests/base.py caveat, docs/policy/test-harness.md
        "Per-test isolation").  Restoring it in setUp keeps every test independent
        of whatever an earlier test committed.
        """
        mapping = db.session.scalar(
            sa.select(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id == self.project_id,
                MapProjectSiteOdk.site_id == self.site_a,
            )
        )
        if mapping is None:
            mapping = MapProjectSiteOdk(
                project_id=self.project_id,
                site_id=self.site_a,
                form_type_id=None,
            )
            db.session.add(mapping)
        mapping.odk_project_id = 11
        mapping.odk_form_id = "ADMIN_API_FORM_A"
        db.session.flush()

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
        # e12dd3a replaced admin.py's _require_admin_api_access() with @role_required();
        # the wrong-role contract is now "{role} access is required."
        # (docs/policy/auth-decorator-rbac.md:88).
        self.assertEqual(
            response.get_json()["error"],
            "admin or project_pi access is required.",
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

    def test_project_sites_excludes_rows_with_inactive_site_master(self):
        self._login(self.manager_id)

        site = db.session.get(VaSiteMaster, self.site_a)
        self.assertIsNotNone(site)
        original_status = site.site_status
        site.site_status = VaStatuses.deactive
        db.session.commit()
        try:
            response = self.client.get(
                f"/admin/api/project-sites?project_id={self.project_id}&include_inactive=1"
            )
        finally:
            site.site_status = original_status
            db.session.commit()

        self.assertEqual(response.status_code, 200)
        rows = response.get_json()["project_sites"]
        self.assertFalse(
            any(
                row["project_id"] == self.project_id and row["site_id"] == self.site_a
                for row in rows
            )
        )

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
                "reviewer_social_autopsy_enabled": True,
                "demo_training_enabled": True,
                "demo_retention_minutes": 10,
            },
            headers=headers
        )
        self.assertEqual(create_resp.status_code, 201)
        self.assertFalse(create_resp.get_json()["project"]["social_autopsy_enabled"])
        self.assertTrue(create_resp.get_json()["project"]["reviewer_social_autopsy_enabled"])
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
                "reviewer_social_autopsy_enabled": False,
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
        self.assertFalse(edit_resp.get_json()["project"]["reviewer_social_autopsy_enabled"])
        self.assertTrue(edit_resp.get_json()["project"]["demo_training_enabled"])
        self.assertEqual(edit_resp.get_json()["project"]["demo_retention_minutes"], 15)
        
        # Toggle project status
        toggle_resp = self.client.post(
            "/admin/api/projects/PRJ999/toggle",
            headers=headers
        )
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertEqual(toggle_resp.get_json()["status"], "active")
        
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
            # 338bc88 made admin user creation invite-only: matching email_confirm is
            # required and no operator password is accepted
            # (docs/policy/dm-user-grant-management.md:116).
            json={
                "email": "new.admin.user@example.com",
                "email_confirm": "new.admin.user@example.com",
                "name": "New Admin User",
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
        
        # Switch back to admin.  _login() clears the session, so the CSRF token
        # captured above is no longer valid — re-issue it for the new session
        # (X-CSRFToken stays required: docs/policy/admin-api-access.md, CSRF Baseline).
        self._login(self.admin_user_id)
        headers = self._csrf_headers()

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
        # setUpClass maps (ADM001, AA01) to ADMIN_API_FORM_A. A project-site may
        # map several ODK forms, so posting a different form adds a mapping
        # (201) rather than replacing that one
        # (docs/policy/admin-api-access.md, Several ODK forms per project-site).
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
        # Both forms are now mapped to this project-site.
        site_a_forms = {
            m["odk_form_id"] for m in mappings if m["site_id"] == self.site_a
        }
        self.assertEqual(site_a_forms, {"ADMIN_API_FORM_A", "test_form"})
        saved = next(
            m for m in mappings
            if m["site_id"] == self.site_a and m["odk_form_id"] == "test_form"
        )
        self.assertEqual(saved["odk_project_id"], 10)
        self.assertEqual(saved["form_smartvahiv"], "True")
        self.assertEqual(saved["form_smartvamalaria"], "True")
        self.assertEqual(saved["form_smartvahce"], "False")
        self.assertEqual(saved["form_smartvafreetext"], "False")
        self.assertEqual(saved["form_smartvacountry"], "ZAF")

        # The new mapping materialized its own va_forms row, distinct from the
        # one the fixture's form owns, and the SmartVA settings landed there.
        form = db.session.get(VaForms, saved_mapping["form_id"])
        self.assertIsNotNone(form)
        self.assertNotEqual(form.form_id, "ADM001AA0101")
        self.assertEqual(form.odk_form_id, "test_form")
        self.assertEqual(form.form_smartvahiv, "True")
        self.assertEqual(form.form_smartvamalaria, "True")
        self.assertEqual(form.form_smartvahce, "False")
        self.assertEqual(form.form_smartvafreetext, "False")
        self.assertEqual(form.form_smartvacountry, "ZAF")

        # The fixture's own form is untouched by the second mapping.
        first_form = db.session.get(VaForms, "ADM001AA0101")
        self.assertEqual(first_form.odk_form_id, "ADMIN_API_FORM_A")

        # Deleting without naming the mapping is refused while the pair holds
        # several forms, then succeeds once told which one.
        ambiguous = self.client.delete(
            f"/admin/api/projects/{self.project_id}/odk-site-mappings/{self.site_a}",
            headers=headers,
        )
        self.assertEqual(ambiguous.status_code, 409)
        self.assertIn("mapping_id", ambiguous.get_json()["error"])

        del_resp = self.client.delete(
            f"/admin/api/projects/{self.project_id}/odk-site-mappings/{self.site_a}"
            f"?mapping_id={saved_mapping['mapping_id']}",
            headers=headers,
        )
        self.assertEqual(del_resp.status_code, 200)

    def test_odk_site_mapping_ignores_retired_icd_classification(self):
        """The per-form ICD classification is retired: the mapping API neither
        reads, writes nor returns it (the project setting replaced it)."""
        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        # An older client still sending the key -- even an invalid value -- is
        # not refused, and the stored per-form column keeps its default.
        save_resp = self.client.post(
            f"/admin/api/projects/{self.project_id}/odk-site-mappings",
            json={
                "site_id": self.site_a,
                "odk_project_id": 11,
                "odk_form_id": "icd_test_form",
                "icd_classification": "icd9",
            },
            headers=headers,
        )
        self.assertEqual(save_resp.status_code, 201)
        mapping_json = save_resp.get_json()["mapping"]
        self.assertEqual(mapping_json["odk_form_id"], "icd_test_form")
        self.assertNotIn("icd_classification", mapping_json)

        mapping = db.session.scalar(
            sa.select(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id == self.project_id,
                MapProjectSiteOdk.site_id == self.site_a,
                MapProjectSiteOdk.odk_form_id == "icd_test_form",
            )
        )
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.icd_classification, "icd10")

        list_resp = self.client.get(f"/admin/api/projects/{self.project_id}/odk-site-mappings")
        saved = next(
            m for m in list_resp.get_json()["mappings"]
            if m["site_id"] == self.site_a and m["odk_form_id"] == "icd_test_form"
        )
        self.assertNotIn("icd_classification", saved)

    def test_project_icd_classification_set_and_validated(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        create_resp = self.client.post(
            "/admin/api/projects",
            json={"project_id": "ICDP01", "project_name": "ICD", "project_nickname": "ICD"},
            headers=headers,
        )
        self.assertEqual(create_resp.status_code, 201)
        self.assertEqual(create_resp.get_json()["project"]["icd_classification"], "icd10")

        for value in ("selectable", "icd11", "icd10"):
            resp = self.client.put(
                "/admin/api/projects/ICDP01",
                json={"icd_classification": value},
                headers=headers,
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["project"]["icd_classification"], value)
            self.assertEqual(
                db.session.get(VaProjectMaster, "ICDP01").icd_classification, value
            )

        for bad in ("icd9", "", None, ["icd10"], 11):
            resp = self.client.put(
                "/admin/api/projects/ICDP01",
                json={"icd_classification": bad, "project_name": "Must not stick"},
                headers=headers,
            )
            self.assertEqual(resp.status_code, 400, bad)
        project = db.session.get(VaProjectMaster, "ICDP01")
        db.session.refresh(project)
        self.assertEqual(project.icd_classification, "icd10")
        self.assertEqual(project.project_name, "ICD")

        create_bad = self.client.post(
            "/admin/api/projects",
            json={
                "project_id": "ICDP02",
                "project_name": "ICD",
                "project_nickname": "ICD",
                "icd_classification": "both",
            },
            headers=headers,
        )
        self.assertEqual(create_bad.status_code, 400)
        self.assertIsNone(db.session.get(VaProjectMaster, "ICDP02"))

        create_selectable = self.client.post(
            "/admin/api/projects",
            json={
                "project_id": "ICDP03",
                "project_name": "ICD",
                "project_nickname": "ICD",
                "icd_classification": "selectable",
            },
            headers=headers,
        )
        self.assertEqual(create_selectable.status_code, 201)
        self.assertEqual(
            create_selectable.get_json()["project"]["icd_classification"], "selectable"
        )

    def test_project_icd_classification_requires_csrf_and_admin(self):
        self._login(self.admin_user_id)
        no_csrf = self.client.put(
            f"/admin/api/projects/{self.project_id}",
            json={"icd_classification": "icd11"},
        )
        self.assertEqual(no_csrf.status_code, 400)
        self.assertIn("CSRF", no_csrf.get_json()["error"])

        self._login(self.manager_id)
        denied = self.client.put(
            f"/admin/api/projects/{self.project_id}",
            json={"icd_classification": "icd11"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(denied.status_code, 403)
        project = db.session.get(VaProjectMaster, self.project_id)
        db.session.refresh(project)
        self.assertEqual(project.icd_classification, "icd10")

    def test_project_cod_modes_default_and_validate_supported_combinations(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        default_response = self.client.post(
            "/admin/api/projects",
            json={
                "project_id": "CODM01",
                "project_name": "Default COD mode",
                "project_nickname": "COD default",
            },
            headers=headers,
        )
        self.assertEqual(default_response.status_code, 201)
        self.assertTrue(default_response.get_json()["project"]["masked_cod_required"])
        self.assertEqual(default_response.get_json()["project"]["cod_entry_mode"], "simple")

        for project_id, payload in (
            (
                "CODM02",
                {"masked_cod_required": False, "cod_entry_mode": "simple"},
            ),
            (
                "CODM03",
                {
                    "masked_cod_required": False,
                    "cod_entry_mode": "doris",
                    "icd_classification": "icd11",
                },
            ),
        ):
            response = self.client.post(
                "/admin/api/projects",
                json={
                    "project_id": project_id,
                    "project_name": project_id,
                    "project_nickname": project_id,
                    **payload,
                },
                headers=headers,
            )
            self.assertEqual(response.status_code, 201, response.get_json())

        for project_id, payload in (
            (
                "CODM04",
                {
                    "masked_cod_required": True,
                    "cod_entry_mode": "doris",
                    "icd_classification": "icd11",
                },
            ),
            (
                "CODM05",
                {
                    "masked_cod_required": False,
                    "cod_entry_mode": "doris",
                    "icd_classification": "selectable",
                },
            ),
            ("CODM06", {"masked_cod_required": "false"}),
        ):
            response = self.client.post(
                "/admin/api/projects",
                json={
                    "project_id": project_id,
                    "project_name": project_id,
                    "project_nickname": project_id,
                    **payload,
                },
                headers=headers,
            )
            self.assertEqual(response.status_code, 400, response.get_json())
            self.assertIsNone(db.session.get(VaProjectMaster, project_id))

    @patch("app.routes.admin._project_has_in_progress_coding", return_value=True)
    def test_project_cod_mode_change_blocked_during_in_progress_coding(self, _guard):
        self._login(self.admin_user_id)
        project = db.session.get(VaProjectMaster, self.project_id)
        original_name = project.project_name

        response = self.client.put(
            f"/admin/api/projects/{self.project_id}",
            json={
                "project_name": "Must not persist",
                "masked_cod_required": False,
            },
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 409)
        db.session.refresh(project)
        self.assertEqual(project.project_name, original_name)
        self.assertTrue(project.masked_cod_required)

    def test_project_cod_mode_can_change_when_no_coding_is_in_progress(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()
        created = self.client.post(
            "/admin/api/projects",
            json={
                "project_id": "CODM07",
                "project_name": "Change COD mode",
                "project_nickname": "Change COD",
            },
            headers=headers,
        )
        self.assertEqual(created.status_code, 201)
        with patch(
            "app.routes.admin._project_has_in_progress_coding", return_value=False
        ):
            response = self.client.put(
                "/admin/api/projects/CODM07",
                json={
                    "masked_cod_required": False,
                    "cod_entry_mode": "doris",
                    "icd_classification": "icd11",
                },
                headers=headers,
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        project = db.session.get(VaProjectMaster, "CODM07")
        self.assertFalse(project.masked_cod_required)
        self.assertEqual(project.cod_entry_mode, "doris")
        self.assertEqual(project.icd_classification, "icd11")

    def test_project_cod_mode_guard_detects_allocations_and_saved_step_one(self):
        from app.routes.admin import _project_has_in_progress_coding

        now = datetime.now(timezone.utc)
        submission = VaSubmissions(
            va_sid=f"uuid:cod-mode-{uuid.uuid4().hex}",
            va_form_id="ADM001AA0101",
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="cod-mode-guard",
            va_uniqueid_real=None,
            va_uniqueid_masked="cod-mode-guard",
            va_consent="yes",
            va_narration_language="english",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()
        allocation = VaAllocations(
            va_sid=submission.va_sid,
            va_allocated_to=uuid.UUID(self.target_id),
            va_allocation_for=VaAllocation.coding,
            va_allocation_status=VaStatuses.active,
        )
        db.session.add(allocation)
        db.session.flush()
        self.assertTrue(_project_has_in_progress_coding(self.project_id))

        allocation.va_allocation_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=submission.va_sid,
                workflow_state="coder_step1_saved",
            )
        )
        db.session.flush()
        self.assertTrue(_project_has_in_progress_coding(self.project_id))


    # ── ODK form uniqueness (one ODK form → one project-site per connection) ──

    def _assign_odk_connection(self, name, *project_ids):
        """Create an ODK connection and assign it to the given projects."""
        from app.models import MapProjectOdk
        from app.utils.credential_crypto import encrypt_credential

        pepper = self.app.config["ODK_CREDENTIAL_PEPPER"]
        username_enc, username_salt = encrypt_credential("admin@odk.test", pepper)
        password_enc, password_salt = encrypt_credential("s3cr3t", pepper)
        conn = MasOdkConnections(
            connection_name=name,
            base_url="https://odk.test",
            username_enc=username_enc,
            username_salt=username_salt,
            password_enc=password_enc,
            password_salt=password_salt,
            status=VaStatuses.active,
        )
        db.session.add(conn)
        db.session.flush()
        for project_id in project_ids:
            existing = db.session.scalar(
                sa.select(MapProjectOdk).where(MapProjectOdk.project_id == project_id)
            )
            if existing:
                existing.connection_id = conn.connection_id
            else:
                db.session.add(
                    MapProjectOdk(
                        project_id=project_id, connection_id=conn.connection_id
                    )
                )
        db.session.flush()
        return conn

    def _clear_site_mapping(self, project_id, site_id):
        """Drop a project-site mapping left committed by an earlier test.

        Routes commit, which releases the per-test SAVEPOINT (tests/base.py), so a
        mapping created through /admin/api survives into later tests of this class.
        """
        mapping = db.session.scalar(
            sa.select(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id == project_id,
                MapProjectSiteOdk.site_id == site_id,
            )
        )
        if mapping is not None:
            db.session.delete(mapping)
            db.session.commit()

    def test_odk_site_mapping_save_rejects_form_mapped_to_another_pair(self):
        self._clear_site_mapping(self.other_project_id, self.other_site)
        self._assign_odk_connection(
            f"Shared ODK {uuid.uuid4().hex[:6]}",
            self.project_id,
            self.other_project_id,
        )
        self._login(self.admin_user_id)

        response = self.client.post(
            f"/admin/api/projects/{self.other_project_id}/odk-site-mappings",
            json={
                "site_id": self.other_site,
                "odk_project_id": 11,
                "odk_form_id": "ADMIN_API_FORM_A",
            },
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 400)
        error = response.get_json()["error"]
        self.assertIn("ADMIN_API_FORM_A", error)
        self.assertIn(f"{self.project_id}/{self.site_a}", error)
        self.assertIsNone(
            db.session.scalar(
                sa.select(MapProjectSiteOdk).where(
                    MapProjectSiteOdk.project_id == self.other_project_id,
                    MapProjectSiteOdk.site_id == self.other_site,
                )
            )
        )

    def test_odk_site_mapping_save_allows_idempotent_resave_of_same_pair(self):
        self._assign_odk_connection(
            f"Shared ODK {uuid.uuid4().hex[:6]}",
            self.project_id,
            self.other_project_id,
        )
        self._login(self.admin_user_id)

        response = self.client.post(
            f"/admin/api/projects/{self.project_id}/odk-site-mappings",
            json={
                "site_id": self.site_a,
                "odk_project_id": 11,
                "odk_form_id": "ADMIN_API_FORM_A",
            },
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["mapping"]["odk_form_id"], "ADMIN_API_FORM_A"
        )

    def test_odk_site_mapping_save_allows_same_form_on_another_connection(self):
        self._clear_site_mapping(self.other_project_id, self.other_site)
        self._assign_odk_connection(f"ODK One {uuid.uuid4().hex[:6]}", self.project_id)
        self._assign_odk_connection(
            f"ODK Two {uuid.uuid4().hex[:6]}", self.other_project_id
        )
        self._login(self.admin_user_id)

        response = self.client.post(
            f"/admin/api/projects/{self.other_project_id}/odk-site-mappings",
            json={
                "site_id": self.other_site,
                "odk_project_id": 11,
                "odk_form_id": "ADMIN_API_FORM_A",
            },
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 201)
        # The route committed: leave no mapping behind for later tests.
        self._clear_site_mapping(self.other_project_id, self.other_site)

    def test_odk_forms_endpoint_annotates_existing_mapping_target(self):
        conn = self._assign_odk_connection(
            f"Picker ODK {uuid.uuid4().hex[:6]}",
            self.project_id,
            self.other_project_id,
        )
        self._login(self.admin_user_id)

        odk_forms = [
            SimpleNamespace(xmlFormId="ADMIN_API_FORM_A", name="Form A", version="1"),
            SimpleNamespace(xmlFormId="UNMAPPED_FORM", name="Free Form", version="1"),
        ]
        url = f"/admin/api/odk-connections/{conn.connection_id}/odk-projects/11/forms"
        with patch("app.routes.admin._get_odk_client_for_connection", return_value=MagicMock()), \
                patch("app.routes.admin.guarded_odk_call", return_value=odk_forms):
            other_resp = self.client.get(
                f"{url}?project_id={self.other_project_id}&site_id={self.other_site}"
            )
            own_resp = self.client.get(
                f"{url}?project_id={self.project_id}&site_id={self.site_a}"
            )

        self.assertEqual(other_resp.status_code, 200)
        other_forms = {f["xmlFormId"]: f for f in other_resp.get_json()["forms"]}
        self.assertEqual(
            other_forms["ADMIN_API_FORM_A"]["mapped_to"],
            {
                "project_id": self.project_id,
                "site_id": self.site_a,
                "same_target": False,
            },
        )
        self.assertIsNone(other_forms["UNMAPPED_FORM"]["mapped_to"])

        own_forms = {f["xmlFormId"]: f for f in own_resp.get_json()["forms"]}
        self.assertTrue(own_forms["ADMIN_API_FORM_A"]["mapped_to"]["same_target"])

    def test_odk_site_mapping_delete_works_for_deactivated_project_site(self):
        self._login(self.admin_user_id)
        project_site = db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == self.project_id,
                VaProjectSites.site_id == self.site_a,
            )
        )
        original_status = project_site.project_site_status
        project_site.project_site_status = VaStatuses.deactive
        db.session.flush()
        try:
            response = self.client.delete(
                f"/admin/api/projects/{self.project_id}/odk-site-mappings/{self.site_a}",
                headers=self._csrf_headers(),
            )
        finally:
            project_site.project_site_status = original_status
            db.session.flush()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(
            db.session.scalar(
                sa.select(MapProjectSiteOdk).where(
                    MapProjectSiteOdk.project_id == self.project_id,
                    MapProjectSiteOdk.site_id == self.site_a,
                )
            )
        )

    def test_odk_mapping_conflicts_endpoint_reports_stale_duplicate(self):
        self._clear_site_mapping(self.other_project_id, self.other_site)
        self._assign_odk_connection(
            f"Conflict ODK {uuid.uuid4().hex[:6]}",
            self.project_id,
            self.other_project_id,
        )
        other_pair = db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == self.other_project_id,
                VaProjectSites.site_id == self.other_site,
            )
        )
        other_pair.project_site_status = VaStatuses.deactive
        db.session.add(
            MapProjectSiteOdk(
                project_id=self.other_project_id,
                site_id=self.other_site,
                odk_project_id=11,
                odk_form_id="ADMIN_API_FORM_A",
            )
        )
        db.session.flush()
        self._login(self.admin_user_id)

        response = self.client.get("/admin/api/odk-site-mappings/conflicts")

        self.assertEqual(response.status_code, 200)
        conflicts = response.get_json()["conflicts"]
        conflict = next(
            c for c in conflicts if c["odk_form_id"] == "ADMIN_API_FORM_A"
        )
        self.assertFalse(conflict["needs_manual_decision"])
        targets = {(t["project_id"], t["site_id"]): t for t in conflict["targets"]}
        self.assertTrue(targets[(self.project_id, self.site_a)]["project_site_active"])
        self.assertFalse(targets[(self.project_id, self.site_a)]["removable"])
        stale = targets[(self.other_project_id, self.other_site)]
        self.assertFalse(stale["project_site_active"])
        self.assertTrue(stale["removable"])
        self.assertEqual(stale["submission_count"], 0)

    def test_admin_can_stop_running_sync_task(self):
        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        db.session.execute(
            sa.update(VaSyncRun)
            .where(VaSyncRun.status == "running")
            .values(status="error", finished_at=datetime.now(timezone.utc))
        )
        db.session.commit()

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

    def test_sync_coverage_excludes_inactive_or_unmapped_legacy_forms(self):
        self._login(self.admin_user_id)

        now = datetime.now(timezone.utc)
        legacy_form_id = f"ADM001AB{uuid.uuid4().hex[:4].upper()}"[:12]
        # Earlier tests in this class create (project_id, site_b) through
        # /admin/api/project-sites and commit, which releases the per-test SAVEPOINT
        # and leaves the row behind — so these must be get-or-create
        # (docs/policy/test-harness.md, Rule 5).
        project_site = db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == self.project_id,
                VaProjectSites.site_id == self.site_b,
            )
        )
        if project_site is None:
            project_site = VaProjectSites(
                project_id=self.project_id,
                site_id=self.site_b,
                project_site_registered_at=now,
            )
            db.session.add(project_site)
        project_site.project_site_status = VaStatuses.deactive
        project_site.project_site_updated_at = now

        odk_map = db.session.scalar(
            sa.select(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id == self.project_id,
                MapProjectSiteOdk.site_id == self.site_b,
            )
        )
        if odk_map is None:
            odk_map = MapProjectSiteOdk(
                project_id=self.project_id,
                site_id=self.site_b,
                form_type_id=None,
            )
            db.session.add(odk_map)
        odk_map.odk_project_id = 22
        odk_map.odk_form_id = "ADMIN_API_FORM_B"

        db.session.add_all(
            [
                VaForms(
                    form_id=legacy_form_id,
                    project_id=self.project_id,
                    site_id=self.site_b,
                    odk_form_id="ADMIN_API_FORM_B",
                    odk_project_id="22",
                    form_type="WHO VA 2022",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                ),
            ]
        )
        db.session.commit()

        with patch(
            "app.utils.va_odk.va_odk_04_submissioncount.va_odk_submissioncount",
            return_value=0,
        ):
            response = self.client.get("/admin/api/sync/coverage")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        rows = payload["mappings"]
        project_site_pairs = {(row["project_id"], row["site_id"]) for row in rows}
        self.assertIn((self.project_id, self.site_a), project_site_pairs)
        self.assertNotIn((self.project_id, self.site_b), project_site_pairs)

    def test_sync_backfill_stats_reports_non_audit_audit_and_legacy_attachment_counts(self):
        self._login(self.admin_user_id)
        now = datetime.now(timezone.utc)
        current_submission = VaSubmissions(
            va_sid="uuid:backfill-stats-attachment-current-adm001",
            va_form_id="ADM001AA0101",
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="ADM001AA0101_attachment_current",
            va_uniqueid_real=None,
            va_uniqueid_masked="ADM001AA0101_attachment_current",
            va_consent="yes",
            va_narration_language="english",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_summary=["fever"],
            va_catcount={},
            va_category_list=["fever"],
        )
        legacy_submission = VaSubmissions(
            va_sid="uuid:backfill-stats-attachment-legacy-adm001",
            va_form_id="ADM001AA0101",
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="ADM001AA0101_attachment_legacy",
            va_uniqueid_real=None,
            va_uniqueid_masked="ADM001AA0101_attachment_legacy",
            va_consent="yes",
            va_narration_language="english",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_summary=["fever"],
            va_catcount={},
            va_category_list=["fever"],
        )
        db.session.add_all([current_submission, legacy_submission])
        db.session.flush()
        payload_versions = [
            VaSubmissionPayloadVersion(
                va_sid=current_submission.va_sid,
                source_updated_at=now,
                payload_fingerprint="test-fingerprint-backfill-stats-attachment-current-adm001",
                payload_data={"AttachmentsExpected": 1},
                version_status="active",
                has_required_metadata=True,
                attachments_expected=1,
            ),
            VaSubmissionPayloadVersion(
                va_sid=legacy_submission.va_sid,
                source_updated_at=now,
                payload_fingerprint="test-fingerprint-backfill-stats-attachment-legacy-adm001",
                payload_data={"AttachmentsExpected": 1},
                version_status="active",
                has_required_metadata=True,
                attachments_expected=1,
            ),
        ]
        db.session.add_all(payload_versions)
        db.session.flush()
        current_submission.active_payload_version_id = payload_versions[0].payload_version_id
        legacy_submission.active_payload_version_id = payload_versions[1].payload_version_id
        db.session.add_all(
            [
                VaSubmissionAttachments(
                    va_sid=current_submission.va_sid,
                    filename="photo-current.jpg",
                    local_path="/tmp/current-photo.jpg",
                    storage_name="opaque-current-photo.jpg",
                    mime_type="image/jpeg",
                    etag=None,
                    exists_on_odk=True,
                    last_downloaded_at=now,
                ),
                VaSubmissionAttachments(
                    va_sid=legacy_submission.va_sid,
                    filename="audit.csv",
                    local_path="/tmp/legacy-audit.csv",
                    storage_name=None,
                    mime_type="text/csv",
                    etag=None,
                    exists_on_odk=True,
                    last_downloaded_at=now,
                ),
            ]
        )
        db.session.commit()

        def fake_exists(path):
            return path in {
                "/tmp/current-photo.jpg",
                "/tmp/legacy-audit.csv",
                "/app/data/ADM001AA0101/media/opaque-current-photo.jpg",
            }

        with patch("app.routes.admin.os.path.exists", side_effect=fake_exists):
            response = self.client.get("/admin/api/sync/backfill-stats")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        project = next(p for p in payload["projects"] if p["project_id"] == self.project_id)
        site = next(s for s in project["sites"] if s["site_id"] == self.site_a)
        form = next(f for f in site["forms"] if f["form_id"] == "ADM001AA0101")
        self.assertGreaterEqual(form["non_audit_attachments_expected"], 1)
        self.assertGreaterEqual(form["non_audit_attachments_present"], 1)
        self.assertEqual(form["audit_attachments_expected"], 0)
        self.assertEqual(form["audit_attachments_present"], 0)
        self.assertGreaterEqual(form["legacy_attachment_rows_total"], 1)

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
        from datetime import datetime, timedelta, timezone
        from app import db
        from app.models.va_sync_runs import VaSyncRun

        self._login(self.admin_user_id)
        headers = self._csrf_headers()

        # _reconcile_orphaned_running_sync_rows() only reclaims rows older than its
        # 5-minute stale_cutoff; a freshly started run is a live job and must still
        # return 409 (docs/current-state/async-tasks.md:314 — orphan detection is
        # age-gated).  Start the row before the cutoff so it qualifies as orphaned.
        stale_run = VaSyncRun(
            triggered_by="backfill",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
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
        # 8bdd7bf reworded this from "Stale run — no active Celery sync/backfill task".
        self.assertIn("no active sync/repair worker task is running", stale_run.error_message)
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

    def test_sync_status_reports_running_when_canonical_child_task_active(self):
        self._login(self.admin_user_id)

        now = datetime.now(timezone.utc)
        run = VaSyncRun(
            triggered_by="backfill",
            started_at=now - timedelta(minutes=5),
            finished_at=now - timedelta(minutes=1),
            status="cancelled",
            error_message="Cancelled by admin.",
        )
        db.session.add(run)
        db.session.commit()

        fake_inspect = MagicMock()
        fake_inspect.active.return_value = {
            "worker-a": [
                {
                    "id": "task-1",
                    "name": "app.tasks.sync_tasks.run_canonical_repair_batches_task",
                    "kwargs": {
                        "run_id": str(run.sync_run_id),
                        "form_id": "ADM001AA0101",
                    },
                }
            ]
        }
        fake_inspect.reserved.return_value = {}
        fake_celery = MagicMock()
        fake_celery.control.inspect.return_value = fake_inspect

        with patch.dict(self.app.extensions, {"celery": fake_celery}, clear=False):
            response = self.client.get("/admin/api/sync/status")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["is_running"])
        self.assertIsNotNone(payload["current_run"])
        self.assertEqual(payload["current_run"]["sync_run_id"], str(run.sync_run_id))
        self.assertEqual(len(payload["active_tasks"]), 1)
        self.assertEqual(payload["active_tasks"][0]["run_id"], str(run.sync_run_id))
        self.assertEqual(payload["active_task_summary"]["repair_batch_count"], 1)
        self.assertEqual(payload["reserved_tasks"], [])

    def test_interrupted_sync_error_helper_matches_new_and_legacy_messages(self):
        from app.routes.admin import _is_interrupted_sync_error

        self.assertTrue(
            _is_interrupted_sync_error(
                "Interrupted run — no active sync/repair worker task is running and no recent progress was recorded."
            )
        )
        self.assertTrue(
            _is_interrupted_sync_error(
                "Stale run — no active Celery sync/backfill task was found and no recent progress was recorded."
            )
        )
        self.assertTrue(
            _is_interrupted_sync_error(
                "Stale run — worker likely restarted before completion"
            )
        )
        self.assertFalse(_is_interrupted_sync_error("Cancelled by admin."))


class AdminWebFormLocalesApiTests(BaseTestCase):
    """GET /admin/api/web-form-locales — the bundled questionnaire's languages.

    Separate from /admin/api/languages on purpose: that endpoint is
    ``mas_languages``, which describes narration recordings, while this one is
    what the browser VA form can actually render.
    Policy: docs/policy/va-web-form-options.md.
    """

    URL = "/admin/api/web-form-locales"

    def test_admin_gets_the_base_locale_first(self):
        self._login(self.base_admin_id)

        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, 200)
        locales = response.get_json()["locales"]
        self.assertEqual(
            locales[0], {"code": "en", "label": "English", "under_review": False}
        )

    def test_project_pi_is_refused(self):
        self._login(self.base_project_pi_id)

        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_anonymous_is_refused(self):
        self.assertEqual(self.client.get(self.URL).status_code, 401)
