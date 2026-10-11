"""Expo web access (GET /api/v1/me/access) and same-origin export hosting."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sqlalchemy as sa
from flask import g

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

ME_ACCESS = "/api/v1/me/access"


class ExpoWebAccessTests(BaseTestCase):
    """Expo web learns who is signed in, its access and its CSRF token from
    GET /api/v1/me/access (the removed /api/v1/client/bootstrap)."""

    def test_privileged_access_is_not_blocked_by_factor_setup(self):
        db.session.add(VaUserAccessGrants(
            user_id=self.base_coder_user.user_id,
            role=VaAccessRoles.admin,
            scope_type=VaAccessScopeTypes.global_scope,
            notes="client factor recovery test",
        ))
        db.session.flush()
        self._login(self.base_coder_id)

        response = self.client.get(ME_ACCESS)

        self.assertEqual(response.status_code, 200)

    def test_pending_terms_remain_enforced_as_json(self):
        self.base_coder_user.pw_reset_t_and_c = False
        db.session.flush()
        self._login(self.base_coder_id)
        from flask import g
        g.pop("csrf_token", None)  # the harness keeps one g across requests

        response = self.client.get(ME_ACCESS)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "terms_required")
        self.assertTrue(response.get_json()["redirect_url"].startswith("/profile/"))
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        # The refusal carries a CSRF token, so the app can accept the terms
        # itself without reaching me/access first.
        token = response.headers.get("X-CSRFToken")
        self.assertTrue(token)
        g.pop("csrf_token", None)
        accepted = self.client.post("/api/v1/me/terms", json={"accept_terms": True},
                                    headers={"X-CSRFToken": token})
        self.assertEqual(accepted.status_code, 200, accepted.get_data(as_text=True))
        self.assertEqual(self.client.get(ME_ACCESS).status_code, 200)

    def test_signed_out_is_json_401_and_never_cached(self):
        response = self.client.get(ME_ACCESS)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "Authentication required.", "code": "unauthorized"})
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(response.content_type, "application/json")
        # The documented sign-in page the client goes to on that 401.
        self.assertEqual(self.client.get("/vaauth/valogin").status_code, 200)

    def test_unresolvable_bearer_token_is_refused(self):
        # /api/v1 takes a bearer too (digitva-uzhq): a bad one is a 401, never
        # an anonymous answer.
        with mock.patch("app.services.device_auth_service.resolve_access_token", return_value=None) as resolve:
            response = self.client.get(ME_ACCESS, headers={"Authorization": "Bearer a-device-token"})

        resolve.assert_called_once()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "Authentication required.", "code": "unauthorized"})

    def test_signed_in_gets_access_and_a_csrf_token_in_the_header(self):
        self._login(self.base_coder_id)
        response = self.client.get(ME_ACCESS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertTrue(response.headers["X-CSRFToken"])
        body = response.get_json()
        user = self.base_coder_user
        self.assertEqual(body["user"], {
            "user_id": self.base_coder_id, "name": user.name,
            "landing_page": user.landing_page, "coding_languages": list(user.vacode_language)})
        self.assertNotIn("csrf", body)
        # An already authenticated account is sent to its landing page.
        self.assertEqual(self.client.get("/vaauth/valogin").status_code, 302)

    def test_the_header_token_authorizes_a_json_write(self):
        self._login(self.base_coder_id)
        g.pop("csrf_token", None)  # the suite's app context outlives requests; production's g does not
        token = self.client.get(ME_ACCESS).headers["X-CSRFToken"]
        previous = self.app.config.get("WTF_CSRF_ENABLED")
        self.addCleanup(lambda: self.app.config.__setitem__("WTF_CSRF_ENABLED", previous))
        self.app.config["WTF_CSRF_ENABLED"] = True
        refused = self.client.post("/api/v1/me/terms", json={})
        self.assertNotEqual((refused.get_json(silent=True) or {}).get("code"), "invalid_request")
        accepted = self.client.post("/api/v1/me/terms", json={}, headers={"X-CSRFToken": token})
        self.assertEqual((accepted.status_code, accepted.get_json()["code"]), (400, "invalid_request"))

    def test_an_interviewer_grant_shows_in_access_and_opens_intake(self):
        self._ensure_base_research_project_and_site()
        db.session.add(VaForms(
            form_id="BASE01BS0101", project_id=self.BASE_PROJECT_ID, site_id=self.BASE_SITE_ID,
            odk_form_id="ODK_CLIENT_ACCESS", odk_project_id="7", form_type="WHO VA 2022",
            form_status=VaStatuses.active,
        ))
        db.session.flush()
        project_site = self._base_project_site()
        db.session.add(VaUserAccessGrants(
            user_id=self.base_coder_user.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=project_site.project_site_id,
            notes="client access test",
        ))
        db.session.flush()
        self._login(self.base_coder_id)

        body = self.client.get(ME_ACCESS).get_json()

        roles = {g["role"] for p in body["projects"] for g in p["grants"]}
        self.assertIn("interviewer", roles)
        intake_response = self.client.get("/api/v1/intake/cases")
        self.assertEqual(intake_response.status_code, 200)
        self.assertEqual(intake_response.headers.get("Cache-Control"), "no-store")

    def test_anonymous_intake_error_is_not_cached(self):
        response = self.client.get("/api/v1/intake/cases")
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
