"""Characterization of the app-wide request hooks (digitva-r8nh.8).

Pins what create_app's before/after-request hooks do today so moving them out
of app/__init__.py cannot change behaviour: registration order, the CSRF
exemptions, the bearer/CSRF/terms/ban refusals, the per-path upload caps,
the response headers and the CLI command order.

Governing docs: docs/policy/api-v1.md, docs/policy/access-control-model.md,
docs/policy/field-data-collection.md ("Phone clock"),
docs/policy/training-demo-project.md,
docs/current-state/authentication-and-onboarding.md,
docs/current-state/runtime-and-operations.md.
"""

from unittest import mock

from flask import g, request, session

from app import csrf
from app.services.attachment_service import MAX_BYTES as ATTACHMENT_MAX_BYTES
from app.services.bundle_ingest_service import MAX_BYTES as BUNDLE_MAX_BYTES
from tests.base import BaseTestCase
from tests.test_account_onboarding import OnboardingTestBase

MIB = 1024 * 1024
SLACK = 64 * 1024
UNAUTHORIZED = {"error": "Authentication required.", "code": "unauthorized"}


def _name(func):
    return getattr(func, "__name__", None) or f"partial:{func.func.__name__}"


class HookRegistrationTests(BaseTestCase):
    def test_app_wide_before_request_order(self):
        self.assertEqual(
            [_name(f) for f in self.app.before_request_funcs[None]],
            [
                "authenticate_bearer",
                "enforce_idle_timeout",
                "open_trainer_tools",
                "_raise_upload_body_limit",
                "csrf_protect",
                "csrf_protect_cookie_requests",
                "_check_request_limit",
                "_force_https",
                "_make_nonce",
                "log_request_info",
                "force_password_update",
                "training_demo_onboarding",
            ],
        )

    def test_app_wide_after_request_order(self):
        self.assertEqual(
            [_name(f) for f in self.app.after_request_funcs[None]],
            [
                "_update_remember_cookie",
                "partial:__inject_headers",
                "_set_response_headers",
                "log_response_info",
                "apply_static_cache_headers",
            ],
        )

    def test_csrf_exemptions(self):
        # auth_api is exempt view by view since 2026-11-25 (api-v1.md rule 5).
        self.assertEqual(set(csrf._exempt_views), {"app.routes.api.icd11.who_icd_api_proxy"} | {
            f"app.routes.api.auth.{name}" for name in (
                "enroll", "open_session", "password_enroll", "redeem_sign_in_code",
                "forgot_password", "redeem_sign_in_qr", "demo_enroll", "demo_signup",
                "record_profile_deletion", "refresh_session",
                "set_device_signing_key", "set_device_project", "end_session",
            )
        } | {
            # ICD-11 client API (digitva-ddpf): token-authenticated, cookie-blind.
            f"app.routes.icd11_client_api.{name}" for name in (
                "client_info", "search", "words", "lookup", "details", "axes", "values", "validate",
            )
        })
        self.assertEqual({b.name for b in csrf._exempt_blueprints}, set())
        self.assertIs(self.app.config["WTF_CSRF_CHECK_DEFAULT"], False)
        self.assertEqual(self.app.config["WTF_CSRF_HEADERS"], ["X-CSRFToken", "X-CSRF-Token"])

    def test_cli_command_order(self):
        self.assertEqual(
            list(self.app.cli.commands),
            [
                "db", "odk-sync", "form-types", "seed", "organization-demo",
                "training-demo", "public-demo", "analytics", "users", "auth",
                "payload-backfill", "cod-buckets", "icd10", "icd11",
                "va-definitions", "ai-search", "ai-catalog", "org",
                "mentor-institute", "instrument-translations", "ui-strings",
                "translations", "repair", "odk-mappings", "attachments",
                "smartva", "backups", "web-intake", "devices", "schema",
                "xlsform", "pii",
            ],
        )


class UploadLimitHookTests(BaseTestCase):
    CAPS = [
        ("PUT", "/api/v1/intake/drafts/d/attachments/a", ATTACHMENT_MAX_BYTES),
        ("POST", "/api/v1/intake/bundles", BUNDLE_MAX_BYTES),
        ("POST", "/api/v1/intake/bundles/validate", BUNDLE_MAX_BYTES),
        ("POST", "/admin/api/organization/1/project-users/import", MIB + SLACK),
        ("POST", "/admin/api/organization/1/import", 5 * MIB + SLACK),
        ("POST", "/admin/api/instrument-translations/a/b/import", 5 * MIB + SLACK),
        ("POST", "/admin/api/instrument-translations/a/b/xliff", 5 * MIB + SLACK),
        ("POST", "/admin/api/form-types/import", 10 * MIB + SLACK),
        ("POST", "/admin/api/icd10/2019-2/policy-import", 16 * MIB),
        ("POST", "/admin/api/icd11/mms/policy-import", 16 * MIB),
        ("POST", "/admin/api/cod-bucket-schemes/1/import", 16 * MIB),
        ("POST", "/api/v1/icd10/2019-2/policy-import", 16 * MIB),
        # Wrong method or no match: the default stands.
        ("GET", "/admin/api/form-types/import", 2 * MIB),
        ("POST", "/api/v1/intake/drafts/d/attachments/a", 2 * MIB),
        ("POST", "/admin/api/form-types/import/extra", 2 * MIB),
    ]

    def test_cap_per_path(self):
        hook = next(f for f in self.app.before_request_funcs[None] if f.__name__ == "_raise_upload_body_limit")
        for method, path, cap in self.CAPS:
            with self.subTest(method=method, path=path):
                with self.app.test_request_context(path, method=method):
                    self.assertIsNone(hook())
                    self.assertEqual(request.max_content_length, cap)


class RefusalTests(BaseTestCase):
    def test_bad_bearer_is_401_json(self):
        response = self.client.get("/api/v1/me/access", headers={"Authorization": "Bearer not-a-token"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), UNAUTHORIZED)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_anonymous_cookie_post_on_api_v1_is_401_not_csrf(self):
        response = self.client.post("/api/v1/me/terms", json={})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), UNAUTHORIZED)

    def test_cookie_post_without_token_off_api_is_csrf_400(self):
        self.assertEqual(self.client.post("/vaauth/valogin", data={}).status_code, 400)

    def test_temporary_ban_json_and_text(self):
        from app.services.request_abuse_service import abuse_ban_message

        ban = {"remaining_seconds": 42}
        with mock.patch("app.services.request_abuse_service.get_temporary_ban", return_value=ban):
            api = self.client.get("/api/v1/me/access")
            page = self.client.get("/vaauth/valogin")
            static = self.client.get("/static/aiims_logo.png")
        self.assertEqual(api.status_code, 403)
        self.assertEqual(api.get_json(), {"error": abuse_ban_message(), "code": "temporarily_blocked"})
        self.assertEqual(api.headers["Retry-After"], "42")
        self.assertEqual(page.status_code, 403)
        self.assertEqual(page.mimetype, "text/plain")
        self.assertEqual(page.get_data(as_text=True), f"{abuse_ban_message()}\n")
        self.assertEqual(page.headers["Retry-After"], "42")
        self.assertEqual(static.status_code, 200)


class TermsGateTests(OnboardingTestBase):
    def test_json_refusal_carries_csrf_token(self):
        user = self._email_user(onboarded=False)
        self._login(user.get_id())
        response = self.client.get("/api/v1/profile/")
        self.assertEqual(response.status_code, 403)
        body = response.get_json()
        self.assertEqual(
            (body["error"], body["code"], body["redirect_url"]),
            ("Accept the terms of use to continue.", "terms_required", "/profile/force-password-change"),
        )
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertTrue(response.headers["X-CSRFToken"])
        page = self.client.get("/profile/")
        self.assertEqual(page.status_code, 302)
        self.assertTrue(page.headers["Location"].endswith("/profile/force-password-change"))


class MaintenanceGateTests(OnboardingTestBase):
    MESSAGE = "Site is under maintenance. Only admin login is allowed right now."

    def test_cookie_session_after_cutoff(self):
        user = self._email_user()
        cutoff = "app.services.site_maintenance_service.should_block_non_admin_after_cutoff"
        with mock.patch(cutoff, return_value=True):
            for path in ("/api/v1/profile/", "/admin/api/users"):
                with self.subTest(path=path):
                    self._login(user.get_id())
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.get_json(), {"error": self.MESSAGE, "code": "maintenance"})
            self._login(user.get_id())
            page = self.client.get("/profile/")
        self.assertEqual(page.status_code, 302)
        self.assertTrue(page.headers["Location"].endswith("/vaauth/valogin"))


class ResponseHeaderTests(BaseTestCase):
    def test_static_asset_is_publicly_cached(self):
        response = self.client.get("/static/aiims_logo.png")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cache_control.public)
        self.assertEqual(response.cache_control.max_age, self.app.config["STATIC_ASSET_CACHE_MAX_AGE"])
        self.assertIn("Date", response.headers)

    def test_missing_static_asset_is_not_publicly_cached(self):
        response = self.client.get("/static/no-such-file.png")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.cache_control.public)

    def test_no_store_prefixes_and_date(self):
        for path in ("/api/v1/me/access", "/api/v1/intake/x", "/api/v1/cases", "/api/v1/coding/x"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertIn("Date", response.headers)

    def test_timed_prefix_gets_server_timing(self):
        response = self.client.get("/api/v1/analytics/nothing-here")
        self.assertRegex(response.headers["Server-Timing"], r"^app;dur=\d+\.\d$")
        self.assertRegex(response.headers["X-Response-Time"], r"^\d+\.\dms$")


class TrainingOnboardingHookTests(BaseTestCase):
    def test_off_without_training_project(self):
        hook = next(f for f in self.app.before_request_funcs[None] if f.__name__ == "training_demo_onboarding")
        with mock.patch.dict(self.app.config, {"DIGITVA_TRAINING_PROJECT_ID": None}), \
                mock.patch("app.services.training_demo_service.should_redirect_to_welcome") as decide:
            with self.app.test_request_context("/somewhere"):
                self.assertIsNone(hook())
        decide.assert_not_called()

    def test_pending_trainee_page_load_is_redirected(self):
        hook = next(f for f in self.app.before_request_funcs[None] if f.__name__ == "training_demo_onboarding")
        user_id = "12345678-1234-5678-1234-567812345678"
        cases = [
            ("/coding/", {}, "/app/training"),
            ("/coding/", {"HX-Request": "true"}, None),
            ("/vaauth/valogin", {}, None),
            ("/no/such/page", {}, None),
        ]
        with mock.patch.dict(self.app.config, {"DIGITVA_TRAINING_PROJECT_ID": "TRN01"}), \
                mock.patch("app.services.training_demo_service.should_redirect_to_welcome", return_value=True), \
                mock.patch("app.routes.expo_client.export_ready", return_value=True):
            for path, headers, location in cases:
                with self.subTest(path=path, headers=headers):
                    with self.app.test_request_context(path, headers=headers):
                        session["_user_id"] = f"{user_id}:3"
                        g.pop("bearer_auth", None)
                        response = hook()
                        if location is None:
                            self.assertIsNone(response)
                        else:
                            self.assertEqual((response.status_code, response.location), (302, location))
