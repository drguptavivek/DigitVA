"""Expo browser bootstrap and same-origin export hosting."""

import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
)
from tests.base import BaseTestCase

BOOTSTRAP = "/api/v1/client/bootstrap"


class ClientBootstrapTests(BaseTestCase):
    def test_factor_setup_returns_real_recovery_destination(self):
        previous = self.app.config.get("AUTH_FACTOR_ENFORCE_FROM")
        self.addCleanup(lambda: self.app.config.__setitem__("AUTH_FACTOR_ENFORCE_FROM", previous))
        self.app.config["AUTH_FACTOR_ENFORCE_FROM"] = "2000-01-01"
        db.session.add(VaUserAccessGrants(
            user_id=self.base_coder_user.user_id,
            role=VaAccessRoles.admin,
            scope_type=VaAccessScopeTypes.global_scope,
            notes="client factor recovery test",
        ))
        db.session.flush()
        self._login(self.base_coder_id)

        response = self.client.get(BOOTSTRAP)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "factor_setup_required")
        action = response.get_json()["redirect_url"]
        self.assertTrue(action.endswith("#passkeys-card"))
        self.assertEqual(self.client.get(action).status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_required_password_change_remains_enforced_as_json(self):
        self.base_coder_user.pw_reset_t_and_c = False
        db.session.flush()
        self._login(self.base_coder_id)

        response = self.client.get(BOOTSTRAP)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "password_change_required")
        self.assertTrue(response.get_json()["redirect_url"].startswith("/profile/"))
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_anonymous_bootstrap_is_json_401_and_never_cached(self):
        response = self.client.get(BOOTSTRAP)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json(),
            {
                "code": "authentication_required",
                "login_url": "/vaauth/valogin?next=/app/",
            },
        )
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(response.content_type, "application/json")
        self.assertEqual(self.client.get(response.get_json()["login_url"]).status_code, 200)

    def test_bearer_device_token_does_not_authenticate_browser_bootstrap(self):
        with mock.patch("app.services.device_auth_service.resolve_access_token") as resolve:
            response = self.client.get(
                BOOTSTRAP,
                headers={"Authorization": "Bearer a-device-token"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["code"], "authentication_required")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        resolve.assert_not_called()

    def test_authenticated_bootstrap_exposes_role_capabilities_and_csrf(self):
        # Capabilities follow the role gates (authz.effective_roles): a coder
        # grant opens coding once its pair has an active form (digitva-5hmc).
        now = datetime.now(UTC)
        self._ensure_base_research_project_and_site()
        db.session.add(VaForms(
            form_id="BASE01BS0101", project_id=self.BASE_PROJECT_ID, site_id=self.BASE_SITE_ID,
            odk_form_id="CLIENT_BOOT", odk_project_id="95", form_type="WHO VA 2022",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()
        self._login(self.base_coder_id)
        response = self.client.get(BOOTSTRAP)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        body = response.get_json()
        self.assertEqual(body["user"], {
            "id": self.base_coder_id,
            "name": self.base_coder_user.name,
        })
        self.assertEqual(body["csrf"]["header"], "X-CSRFToken")
        self.assertTrue(body["csrf"]["token"])
        self.assertEqual(
            body["capabilities"],
            {"intake": False, "coding": True, "reviewing": False},
        )
        self.assertNotIn("email", body["user"])
        self.assertEqual(body["links"]["intakeBootstrap"], "/intake/api/bootstrap")
        self.assertEqual(body["links"]["coding"], "/coding/")
        login_url = urlsplit(body["links"]["login"])
        # An already authenticated account is sent to its landing page.
        self.assertEqual(self.client.get(body["links"]["login"]).status_code, 302)
        self.assertEqual(login_url.path, "/vaauth/valogin")
        self.assertEqual(parse_qs(login_url.query)["next"], ["/app/"])

    def test_a_coder_whose_pair_has_no_form_is_not_offered_coding(self):
        """The coding gate refuses this coder (no active form in reach), so
        bootstrap does not offer a tab that would 403."""
        self._login(self.base_coder_id)
        body = self.client.get(BOOTSTRAP).get_json()
        self.assertIn("coding", body["capabilities"])
        self.assertFalse(body["capabilities"]["coding"])
        self.assertEqual(self.client.get("/coding/").status_code, 403)

    def test_capabilities_follow_authoritative_roles_for_intake_and_review(self):
        from app.models import VaForms, VaStatuses

        self._ensure_base_research_project_and_site()
        db.session.add(VaForms(
            form_id="BASE01BS0101",
            project_id=self.BASE_PROJECT_ID,
            site_id=self.BASE_SITE_ID,
            odk_form_id="ODK_CLIENT_BOOTSTRAP",
            odk_project_id="7",
            form_type="WHO VA 2022",
            form_status=VaStatuses.active,
        ))
        db.session.flush()
        project_site = self._base_project_site()
        db.session.add_all(
            [
                VaUserAccessGrants(
                    user_id=self.base_coder_user.user_id,
                    role=VaAccessRoles.interviewer,
                    scope_type=VaAccessScopeTypes.project_site,
                    project_site_id=project_site.project_site_id,
                    notes="client bootstrap test",
                ),
                VaUserAccessGrants(
                    user_id=self.base_coder_user.user_id,
                    role=VaAccessRoles.reviewer,
                    scope_type=VaAccessScopeTypes.project_site,
                    project_site_id=project_site.project_site_id,
                    notes="client bootstrap test",
                ),
            ]
        )
        db.session.flush()
        self._login(self.base_coder_id)

        body = self.client.get(BOOTSTRAP).get_json()

        self.assertEqual(
            body["capabilities"],
            {"intake": True, "coding": True, "reviewing": True},
        )
        intake_response = self.client.get("/intake/api/bootstrap")
        self.assertEqual(intake_response.status_code, 200)
        self.assertEqual(intake_response.headers.get("Cache-Control"), "no-store")

    def test_anonymous_intake_error_is_not_cached(self):
        response = self.client.get("/intake/api/bootstrap")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def _base_project_site(self):
        return db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == self.BASE_PROJECT_ID,
                VaProjectSites.site_id == self.BASE_SITE_ID,
            )
        )


class ExpoClientHostingTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self._old_dist = self.app.config.get("EXPO_CLIENT_DIST")
        self._tempdir = tempfile.TemporaryDirectory()
        root = Path(self._tempdir.name)
        (root / "assets").mkdir()
        (root / "index.html").write_text("<html>expo shell</html>", encoding="utf-8")
        (root / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
        self.app.config["EXPO_CLIENT_DIST"] = self._tempdir.name

    def tearDown(self):
        if self._old_dist is None:
            self.app.config.pop("EXPO_CLIENT_DIST", None)
        else:
            self.app.config["EXPO_CLIENT_DIST"] = self._old_dist
        self._tempdir.cleanup()
        super().tearDown()

    def test_index_asset_and_known_deep_link_are_served(self):
        index = self.client.get("/app/")
        self.assertEqual(index.status_code, 200)
        self.assertEqual(index.data, b"<html>expo shell</html>")
        self.assertEqual(index.headers.get("Cache-Control"), "no-cache")
        self.assertEqual(
            self.client.get("/app/worklist").data,
            b"<html>expo shell</html>",
        )
        self.assertEqual(
            self.client.get("/app/assets/app.js").data,
            b"console.log('ok')",
        )

    def test_missing_assets_unknown_routes_and_traversal_are_404(self):
        for path in (
            "/app/assets/missing.js",
            "/app/unknown-route",
            "/app/%2e%2e/%2e%2e/etc/passwd",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_hidden_files_in_the_export_are_never_served(self):
        root = Path(self._tempdir.name)
        (root / ".env").write_text("SECRET=1", encoding="utf-8")
        (root / "assets" / ".DS_Store").write_text("x", encoding="utf-8")
        self.assertEqual(self.client.get("/app/assets/app.js").status_code, 200)
        for path in ("/app/.env", "/app/assets/.DS_Store"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_missing_export_is_safe_404(self):
        self.app.config["EXPO_CLIENT_DIST"] = os.path.join(
            self._tempdir.name, "does-not-exist"
        )

        response = self.client.get("/app/")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
