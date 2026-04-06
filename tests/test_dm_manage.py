"""Tests for data-manager user and grant management routes.

Covers:
  - Bootstrap returns correct scope context
  - DM can create users
  - Project-scoped DM can create coder/data_manager grants at project and site level
  - Site-scoped DM can only create grants at site level for their sites
  - DM cannot create admin/project_pi/site_pi/reviewer/collaborator grants
  - DM can toggle coder/data_manager grants within scope
  - DM cannot toggle grants outside scope
  - Non-DM users get 403
"""

import uuid
import unittest
from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    MasLanguages,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)

from tests.base import BaseTestCase


class DmManageTests(BaseTestCase):
    project_id = "DMM001"
    other_project_id = "DMM002"
    site_a = "DA01"
    site_b = "DB01"
    other_site = "DC01"

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
                VaProjectMaster(
                    project_id=cls.project_id,
                    project_code=cls.project_id,
                    project_name="DM Manage Test Project",
                    project_nickname="DmManageTest",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaProjectMaster(
                    project_id=cls.other_project_id,
                    project_code=cls.other_project_id,
                    project_name="DM Manage Other Project",
                    project_nickname="DmManageOther",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaResearchProjects(
                    project_id=cls.project_id,
                    project_code=cls.project_id,
                    project_name="DM Manage Test Project",
                    project_nickname="DmManageTest",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaResearchProjects(
                    project_id=cls.other_project_id,
                    project_code=cls.other_project_id,
                    project_name="DM Manage Other Project",
                    project_nickname="DmManageOther",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaSiteMaster(
                    site_id=cls.site_a,
                    site_name="DM Manage Site A",
                    site_abbr=cls.site_a,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
                VaSiteMaster(
                    site_id=cls.site_b,
                    site_name="DM Manage Site B",
                    site_abbr=cls.site_b,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
                VaSiteMaster(
                    site_id=cls.other_site,
                    site_name="DM Manage Other Site",
                    site_abbr=cls.other_site,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
            ]
        )
        db.session.commit()
        db.session.add_all(
            [
                VaSites(
                    site_id=cls.site_a,
                    project_id=cls.project_id,
                    site_name="DM Manage Site A",
                    site_abbr=cls.site_a,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
                VaSites(
                    site_id=cls.site_b,
                    project_id=cls.project_id,
                    site_name="DM Manage Site B",
                    site_abbr=cls.site_b,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
                VaSites(
                    site_id=cls.other_site,
                    project_id=cls.other_project_id,
                    site_name="DM Manage Other Site",
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
                    project_id=cls.project_id,
                    site_id=cls.site_b,
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
        # Flask 3.1 ties flask.g to the app context, which stays pushed
        # for the whole test session.  Flask-Login caches the loaded user
        # in g._login_user.  Without clearing it, the user from the
        # previous test's request leaks into the next test's request,
        # causing role_required to check the wrong user.
        from flask import g

        if hasattr(g, "_login_user"):
            del g._login_user

        sfx = uuid.uuid4().hex[:8]
        # Project-scoped data-manager for project_id
        self.project_dm = self._create_user(f"dm.project.{sfx}@example.com")
        self._grant(
            self.project_dm,
            VaAccessRoles.data_manager,
            VaAccessScopeTypes.project,
            "project-scoped DM",
            project_id=self.project_id,
        )
        # Site-scoped data-manager for site_a only
        self.site_dm = self._create_user(f"dm.site.{sfx}@example.com")
        self._grant(
            self.site_dm,
            VaAccessRoles.data_manager,
            VaAccessScopeTypes.project_site,
            "site-scoped DM",
            project_site_id=self._project_site_id(self.project_id, self.site_a),
        )
        # Target user for grant operations
        self.target = self._create_user(f"dm.target.{sfx}@example.com")
        # Plain user with no DM role
        self.plain_user = self._create_user(f"dm.plain.{sfx}@example.com")

        self.project_dm_id = str(self.project_dm.user_id)
        self.site_dm_id = str(self.site_dm.user_id)
        self.target_id = str(self.target.user_id)
        self.plain_user_id = str(self.plain_user.user_id)

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
        user.set_password("DmManageTest123")
        db.session.add(user)
        db.session.flush()
        return user

    def _grant(self, user, role, scope_type, notes, project_id=None, project_site_id=None):
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

    # ── Bootstrap ──────────────────────────────────────────────────────────────

    def test_bootstrap_returns_scope_for_project_dm(self):
        self._login(self.project_dm_id)
        resp = self.client.get("/data-management/api/bootstrap")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["user"]["is_project_scoped"])
        self.assertIn(self.project_id, data["user"]["managed_project_ids"])
        self.assertEqual(data["allowed_roles"], ["coder", "data_manager"])

    def test_bootstrap_returns_scope_for_site_dm(self):
        self._login(self.site_dm_id)
        resp = self.client.get("/data-management/api/bootstrap")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data["user"]["is_project_scoped"])
        pairs = data["user"]["managed_site_pairs"]
        self.assertTrue(
            any(p["project_id"] == self.project_id and p["site_id"] == self.site_a for p in pairs)
        )

    def test_bootstrap_denies_non_dm(self):
        self._login(self.plain_user_id)
        resp = self.client.get("/data-management/api/bootstrap")
        self.assertEqual(resp.status_code, 403)

    # ── User creation ──────────────────────────────────────────────────────────

    def test_dm_can_create_user(self):
        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            "/data-management/api/users",
            json={
                "email": "new.dm.user@example.com",
                "name": "New DM User",
                "password": "TestPass123!@special",
                "languages": ["english"],
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertIn("user", data)
        # Verify the user was actually created in the DB
        new_user = db.session.scalar(
            sa.select(VaUsers).where(VaUsers.email == "new.dm.user@example.com")
        )
        self.assertIsNotNone(new_user)
        self.assertEqual(new_user.name, "New DM User")

    def test_dm_create_user_validates_fields(self):
        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            "/data-management/api/users",
            json={"email": "", "name": "", "password": ""},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_dm_create_user_rejects_duplicate_email(self):
        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        self.client.post(
            "/data-management/api/users",
            json={
                "email": "dup.dm@example.com",
                "name": "Dup DM",
                "password": "TestPass123!@special",
                "languages": ["english"],
            },
            headers=headers,
        )
        resp = self.client.post(
            "/data-management/api/users",
            json={
                "email": "dup.dm@example.com",
                "name": "Dup DM 2",
                "password": "TestPass123!@special",
                "languages": ["english"],
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_non_dm_cannot_create_user(self):
        self._login(self.plain_user_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            "/data-management/api/users",
            json={
                "email": "blocked@example.com",
                "name": "Blocked",
                "password": "TestPass123!@special",
                "languages": ["english"],
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 403)

    # ── Grant creation: project-scoped DM ──────────────────────────────────────

    def test_project_dm_can_create_coder_grant_at_project_level(self):
        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            "/data-management/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "coder",
                "scope_type": "project",
                "project_id": self.project_id,
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["grant"]["role"], "coder")
        self.assertEqual(data["grant"]["scope_type"], "project")

    def test_project_dm_can_create_dm_grant_at_site_level(self):
        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        ps_id = str(self._project_site_id(self.project_id, self.site_a))
        resp = self.client.post(
            "/data-management/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "data_manager",
                "scope_type": "project_site",
                "project_site_id": ps_id,
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["grant"]["role"], "data_manager")
        self.assertEqual(data["grant"]["scope_type"], "project_site")

    def test_project_dm_cannot_create_grant_for_other_project(self):
        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            "/data-management/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "coder",
                "scope_type": "project",
                "project_id": self.other_project_id,
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 403)

    # ── Grant creation: site-scoped DM ─────────────────────────────────────────

    def test_site_dm_can_create_coder_grant_at_site_level(self):
        self._login(self.site_dm_id)
        headers = self._csrf_headers()
        ps_id = str(self._project_site_id(self.project_id, self.site_a))
        resp = self.client.post(
            "/data-management/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "coder",
                "scope_type": "project_site",
                "project_site_id": ps_id,
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201)

    def test_site_dm_cannot_create_grant_at_project_level(self):
        self._login(self.site_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            "/data-management/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "coder",
                "scope_type": "project",
                "project_id": self.project_id,
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_site_dm_cannot_create_grant_for_other_site(self):
        self._login(self.site_dm_id)
        headers = self._csrf_headers()
        ps_id = str(self._project_site_id(self.project_id, self.site_b))
        resp = self.client.post(
            "/data-management/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "coder",
                "scope_type": "project_site",
                "project_site_id": ps_id,
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 403)

    # ── Role restrictions ──────────────────────────────────────────────────────

    def test_dm_cannot_create_admin_grant(self):
        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            "/data-management/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "admin",
                "scope_type": "global",
            },
            headers=headers,
        )
        # Fails because admin requires global scope which _resolve_scope_from_payload
        # validates, or because DM role check fails
        self.assertIn(resp.status_code, [400, 403])

    def test_dm_cannot_create_project_pi_grant(self):
        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            "/data-management/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "project_pi",
                "scope_type": "project",
                "project_id": self.project_id,
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_dm_cannot_create_reviewer_grant(self):
        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            "/data-management/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "reviewer",
                "scope_type": "project",
                "project_id": self.project_id,
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 403)

    # ── Grant toggle ───────────────────────────────────────────────────────────

    def test_dm_can_toggle_coder_grant_within_scope(self):
        # First create a grant
        grant = self._grant(
            self.target,
            VaAccessRoles.coder,
            VaAccessScopeTypes.project,
            "toggle test",
            project_id=self.project_id,
        )
        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            f"/data-management/api/access-grants/{grant.grant_id}/toggle",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "deactive")

    def test_dm_cannot_toggle_grant_outside_scope(self):
        # Create a grant on a project the DM doesn't manage
        grant = self._grant(
            self.target,
            VaAccessRoles.coder,
            VaAccessScopeTypes.project,
            "out of scope",
            project_id=self.other_project_id,
        )
        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            f"/data-management/api/access-grants/{grant.grant_id}/toggle",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_dm_cannot_toggle_non_coder_dm_grant(self):
        grant = self._grant(
            self.target,
            VaAccessRoles.reviewer,
            VaAccessScopeTypes.project,
            "reviewer grant",
            project_id=self.project_id,
        )
        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            f"/data-management/api/access-grants/{grant.grant_id}/toggle",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_site_dm_cannot_toggle_grant_for_other_site(self):
        ps_id = self._project_site_id(self.project_id, self.site_b)
        grant = self._grant(
            self.target,
            VaAccessRoles.coder,
            VaAccessScopeTypes.project_site,
            "other site grant",
            project_site_id=ps_id,
        )
        self._login(self.site_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            f"/data-management/api/access-grants/{grant.grant_id}/toggle",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 403)

    # ── Grant listing ──────────────────────────────────────────────────────────

    def test_grant_listing_shows_only_coder_dm_in_scope(self):
        # Create grants of various types
        self._grant(
            self.target,
            VaAccessRoles.coder,
            VaAccessScopeTypes.project,
            "coder in scope",
            project_id=self.project_id,
        )
        self._grant(
            self.target,
            VaAccessRoles.reviewer,
            VaAccessScopeTypes.project,
            "reviewer in scope",
            project_id=self.project_id,
        )
        self._grant(
            self.target,
            VaAccessRoles.coder,
            VaAccessScopeTypes.project,
            "coder out of scope",
            project_id=self.other_project_id,
        )
        self._login(self.project_dm_id)
        resp = self.client.get("/data-management/api/access-grants")
        self.assertEqual(resp.status_code, 200)
        grants = resp.get_json()["grants"]
        # Should only see coder grants in the DM's project
        for g in grants:
            self.assertIn(g["role"], ["coder", "data_manager"])
        # At least the coder grant in the DM's project should be present
        project_coder = [g for g in grants if g["project_id"] == self.project_id and g["role"] == "coder"]
        self.assertTrue(len(project_coder) >= 1)
        # Reviewer and out-of-scope grants should not appear
        reviewer_grants = [g for g in grants if g["role"] == "reviewer"]
        self.assertEqual(len(reviewer_grants), 0)
        other_project = [g for g in grants if g["project_id"] == self.other_project_id]
        self.assertEqual(len(other_project), 0)

    # ── Users page access ──────────────────────────────────────────────────────

    def test_dm_can_access_users_page(self):
        self._login(self.project_dm_id)
        resp = self.client.get("/data-management/users")
        self.assertEqual(resp.status_code, 200)

    def test_non_dm_cannot_access_users_page(self):
        self._login(self.plain_user_id)
        resp = self.client.get("/data-management/users")
        self.assertEqual(resp.status_code, 403)

    # ── CSRF required ──────────────────────────────────────────────────────────

    def test_grant_creation_requires_csrf(self):
        self._login(self.project_dm_id)
        resp = self.client.post(
            "/data-management/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "coder",
                "scope_type": "project",
                "project_id": self.project_id,
            },
        )
        self.assertEqual(resp.status_code, 400)
        # CSRF rejection may return JSON or HTML depending on config
        body = resp.get_json()
        if body:
            self.assertIn("CSRF", body.get("error", ""))
        else:
            self.assertIn(b"CSRF", resp.data)

    # ── Reactivating existing grant ────────────────────────────────────────────

    def test_dm_can_reactivate_deactivated_grant(self):
        grant = self._grant(
            self.target,
            VaAccessRoles.coder,
            VaAccessScopeTypes.project,
            "reactivate test",
            project_id=self.project_id,
        )
        grant.grant_status = VaStatuses.deactive
        db.session.flush()

        self._login(self.project_dm_id)
        headers = self._csrf_headers()
        resp = self.client.post(
            "/data-management/api/access-grants",
            json={
                "user_id": self.target_id,
                "role": "coder",
                "scope_type": "project",
                "project_id": self.project_id,
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["grant"]["status"], "active")
