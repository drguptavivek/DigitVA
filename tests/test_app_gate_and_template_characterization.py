"""Characterization of the password/terms/maintenance gate and the template
helpers create_app registers (digitva-r8nh.8, slice 2).

Pins every branch of the ``force_password_update`` before_request hook (skip
paths, request timers, temporary IP ban, user re-resolution for bearer and
cookie requests, maintenance cutoff, terms gate and its exempt endpoints) and
the registered template globals, filters and context processors, so splitting
the hook and moving the template helpers cannot change behaviour.

Governing docs: docs/policy/api-v1.md, docs/policy/access-control-model.md,
docs/current-state/authentication-and-onboarding.md,
docs/current-state/runtime-and-operations.md.
"""

import types
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest import mock

import pytz
from flask import g, render_template_string, session
from werkzeug.routing import Rule

from app import db
from app.models import VaStatuses
from app.services.request_abuse_service import abuse_ban_message
from tests.base import BaseTestCase
from tests.test_account_onboarding import OnboardingTestBase

CUTOFF = "app.services.site_maintenance_service.should_block_non_admin_after_cutoff"
BAN = "app.services.request_abuse_service.get_temporary_ban"
MAINTENANCE = "Site is under maintenance. Only admin login is allowed right now."
TERMS = "Accept the terms of use to continue."
TERMS_PAGE = "/profile/force-password-change"
G_KEYS = ("_request_started_at", "_slow_started_at", "_sql_count", "_sql_ms", "_login_user", "bearer_auth")
EXEMPT_ENDPOINTS = (
    "static",
    "profile.force_password_change",
    "va_auth.va_logout",
    "va_auth.va_login",
    "va_auth.forgot_password",
    "va_auth.reset_password",
    "va_auth.verify_email",
    "va_auth.resend_verification",
    "api_v1.profile_api.accept_terms",
    "api_v1.me_api.accept_terms",
    "api_v1.auth_api.end_session",
)


def _hook(app, name):
    return next(f for f in app.before_request_funcs[None] if f.__name__ == name)


class _GateCase(OnboardingTestBase):
    """Calls the gate directly inside a request context it controls."""

    @contextmanager
    def _request(self, path, *, user=None, uid=None, bearer=None, endpoint=None, headers=None):
        """``user`` is what current_user resolves to (anonymous when None);
        ``uid`` the login session's ``_user_id``; ``bearer`` sets g.bearer_auth
        and sends a bearer header; ``endpoint`` overrides the matched one."""
        headers = dict(headers or {})
        if bearer is not None:
            headers["Authorization"] = "Bearer some-token"
        for key in G_KEYS:
            g.pop(key, None)
        try:
            with self.app.test_request_context(path, headers=headers, environ_base={"REMOTE_ADDR": "10.1.2.3"}) as ctx:
                if endpoint is not None:
                    ctx.request.url_rule = Rule("/x", endpoint=endpoint)
                g._login_user = user if user is not None else self.app.login_manager.anonymous_user()
                if bearer is not None:
                    g.bearer_auth = bearer
                if uid is not None:
                    session["_user_id"] = uid
                yield ctx
        finally:
            for key in G_KEYS:
                g.pop(key, None)

    def _gate(self):
        result = _hook(self.app, "force_password_update")()
        return None if result is None else self.app.make_response(result)


class SkipAndTimerTests(_GateCase):
    def test_static_and_health_skip_everything(self):
        with mock.patch(BAN, return_value={"remaining_seconds": 5}) as ban:
            for path in ("/static/x.png", "/static", "/health"):
                with self.subTest(path=path), self._request(path):
                    self.assertIsNone(self._gate())
                    for key in ("_request_started_at", "_slow_started_at", "_sql_count", "_sql_ms"):
                        self.assertNotIn(key, g)
        ban.assert_not_called()

    def test_timed_prefixes_start_the_request_timer(self):
        cases = [
            ("/data-management/x", True),
            ("/api/v1/data-management/x", True),
            ("/api/v1/analytics/x", True),
            ("/api/v1/me/access", False),
            ("/coding/", False),
            ("/healthz", False),
        ]
        for path, timed in cases:
            with self.subTest(path=path), self._request(path):
                self.assertIsNone(self._gate())
                self.assertEqual("_request_started_at" in g, timed)
                self.assertIsInstance(g._slow_started_at, float)
                self.assertEqual((g._sql_count, g._sql_ms), (0, 0.0))


class TemporaryBanTests(_GateCase):
    def test_admin_api_ban_is_json_and_logged(self):
        with mock.patch(BAN, return_value={"remaining_seconds": 9}) as ban, \
                self.assertLogs(self.app.logger, "WARNING") as logs, \
                self._request("/admin/api/users", user=self._email_user(onboarded=False)):
            response = self._gate()
            ban.assert_called_once_with("10.1.2.3")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": abuse_ban_message(), "code": "temporarily_blocked"})
        self.assertEqual(response.headers["Retry-After"], "9")
        self.assertEqual(
            logs.output,
            ["WARNING:app:blocked_temporarily_banned_ip ip=10.1.2.3 method=GET path=/admin/api/users remaining_seconds=9"],
        )

    def test_ban_runs_before_the_timers_are_read_and_after_they_start(self):
        with mock.patch(BAN, return_value={"remaining_seconds": 1}), self._request("/api/v1/analytics/x"):
            self.assertEqual(self._gate().status_code, 403)
            self.assertIn("_request_started_at", g)
            self.assertIn("_slow_started_at", g)


class BearerResolutionTests(_GateCase):
    def test_bearer_without_bearer_auth_is_not_gated(self):
        user = self._email_user(onboarded=False)
        with self._request("/api/v1/profile/", user=user, bearer=False):
            self.assertIsNone(self._gate())

    def test_bearer_pending_terms_is_bare_json_403(self):
        user = self._email_user(onboarded=False)
        with self._request("/api/v1/profile/", user=user, bearer=True):
            response = self._gate()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": TERMS, "code": "terms_required"})
        self.assertNotIn("X-CSRFToken", response.headers)
        self.assertNotEqual(response.headers.get("Cache-Control"), "no-store")

    def test_bearer_exempt_endpoint_passes(self):
        user = self._email_user(onboarded=False)
        with self._request("/api/v1/x", user=user, bearer=True, endpoint="api_v1.auth_api.end_session"):
            self.assertIsNone(self._gate())

    def test_bearer_maintenance_is_json_403_without_logout(self):
        user = self._email_user()
        with mock.patch(CUTOFF, return_value=True), \
                self._request("/api/v1/profile/", user=user, bearer=True, uid="keep"):
            response = self._gate()
            self.assertEqual(session.get("_user_id"), "keep")
            self.assertNotIn("_flashes", session)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": "Site is under maintenance.", "code": "maintenance"})

    def test_bearer_onboarded_passes(self):
        with self._request("/api/v1/profile/", user=self._email_user(), bearer=True):
            self.assertIsNone(self._gate())


class CookieResolutionTests(_GateCase):
    def test_unresolved_cookie_users_are_not_gated(self):
        pending = self._email_user(onboarded=False)
        inactive = self._email_user(onboarded=False)
        inactive.user_status = VaStatuses.deactive
        db.session.commit()
        cases = [
            ("anonymous", None, str(pending.user_id)),
            ("no session id", pending, None),
            ("empty session id", pending, ""),
            ("malformed id", pending, "not-a-uuid"),
            ("malformed id with version", pending, "not-a-uuid:3"),
            ("unknown user", pending, "12345678-1234-5678-1234-567812345678"),
            ("inactive user", pending, str(inactive.user_id)),
        ]
        for label, user, uid in cases:
            with self.subTest(label), self._request("/profile/", user=user, uid=uid):
                self.assertIsNone(self._gate())

    def test_gate_reads_the_database_user_not_current_user(self):
        onboarded = self._email_user()
        pending = self._email_user(onboarded=False)
        for uid in (str(pending.user_id), f"{pending.user_id}:7"):
            with self.subTest(uid=uid), self._request("/profile/", user=onboarded, uid=uid):
                response = self._gate()
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.location.endswith(TERMS_PAGE))
        with self._request("/profile/", user=pending, uid=str(onboarded.user_id)):
            self.assertIsNone(self._gate())


class MaintenanceTests(_GateCase):
    def test_admin_passes_the_cutoff(self):
        admin = self.base_admin_user
        with mock.patch(CUTOFF, return_value=True) as cutoff, \
                self._request("/profile/", user=admin, uid=str(admin.user_id)):
            self.assertIsNone(self._gate())
        cutoff.assert_not_called()

    def test_non_admin_is_logged_out_and_flashed_on_every_path(self):
        cases = [
            ("/api/x", 401),
            ("/admin/api/x", 401),
            ("/api/v1/profile/", 401),
            ("/data-management/api/x", 302),
            ("/profile/", 302),
        ]
        for path, status in cases:
            user = self._email_user(onboarded=False)
            with self.subTest(path=path), mock.patch(CUTOFF, return_value=True), \
                    self._request(path, user=user, uid=str(user.user_id)):
                response = self._gate()
                self.assertNotIn("_user_id", session)
                self.assertEqual(session["_flashes"], [("warning", MAINTENANCE)])
            self.assertEqual(response.status_code, status)
            if status == 401:
                self.assertEqual(response.get_json(), {"error": MAINTENANCE, "code": "maintenance"})
            else:
                self.assertTrue(response.location.endswith("/vaauth/valogin"))

    def test_cutoff_off_falls_through_to_terms(self):
        user = self._email_user(onboarded=False)
        with mock.patch(CUTOFF, return_value=False), self._request("/profile/", user=user, uid=str(user.user_id)):
            self.assertEqual(self._gate().status_code, 302)


class TermsGateTests(_GateCase):
    def test_exempt_endpoints_pass_and_others_are_gated(self):
        user = self._email_user(onboarded=False)
        for endpoint in EXEMPT_ENDPOINTS:
            for path in ("/profile/", "/api/v1/x"):
                with self.subTest(endpoint=endpoint, path=path), \
                        self._request(path, user=user, uid=str(user.user_id), endpoint=endpoint):
                    self.assertIsNone(self._gate())
        for endpoint in ("profile.index", "api_v1.me_api.access", "va_auth.something_else"):
            with self.subTest(endpoint=endpoint), \
                    self._request("/profile/", user=user, uid=str(user.user_id), endpoint=endpoint):
                self.assertEqual(self._gate().status_code, 302)

    def test_cookie_refusal_per_path(self):
        user = self._email_user(onboarded=False)
        for path in ("/api/x", "/api/v1/x", "/admin/api/x", "/data-management/api/x"):
            with self.subTest(path=path), self._request(path, user=user, uid=str(user.user_id)):
                response = self._gate()
            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                response.get_json(),
                {"error": TERMS, "code": "terms_required", "redirect_url": TERMS_PAGE},
            )
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertTrue(response.headers["X-CSRFToken"])
        for path in ("/profile/", "/no/such/page", "/data-management/x"):
            with self.subTest(path=path), self._request(path, user=user, uid=str(user.user_id)):
                response = self._gate()
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith(TERMS_PAGE))
            self.assertNotIn("X-CSRFToken", response.headers)

    def test_onboarded_user_passes(self):
        user = self._email_user()
        with self._request("/profile/", user=user, uid=str(user.user_id)):
            self.assertIsNone(self._gate())


class TemplateHelperRegistrationTests(BaseTestCase):
    def test_globals_are_the_service_functions(self):
        from app.models.va_selectives import ROLE_LABELS
        from app.services.icd11_titles import icd11_alternatives_label, stored_cod_label
        from app.services.icd_coding_value import (
            classification_of_value,
            get_icd_classification_for_submission,
        )
        from app.services.organization_service import district_reference_model
        from app.services.smartva_icd11 import smartva_icd11_mapping
        from app.services.smartva_service import smartva_panel
        from app.utils.who_va_bundle import who_va_bundle_version

        expected = {
            "icd_classification_for": get_icd_classification_for_submission,
            "icd_classification_of": classification_of_value,
            "smartva_icd11_mapping": smartva_icd11_mapping,
            "icd11_alternatives_label": icd11_alternatives_label,
            "stored_cod_label": stored_cod_label,
            "smartva_panel": smartva_panel,
            "who_va_bundle_version": who_va_bundle_version,
            "district_reference_model": district_reference_model,
            "role_labels": ROLE_LABELS,
        }
        for name, value in expected.items():
            with self.subTest(name=name):
                self.assertIs(self.app.jinja_env.globals[name], value)
        self.assertTrue(callable(self.app.jinja_env.globals["training_page_url"]))

    def test_filters_are_registered(self):
        from app.services.cod_certificate_service import cert_date
        from app.utils.number_format import whole_number
        from app.utils.smartva_gender import smartva_gender

        filters = self.app.jinja_env.filters
        self.assertIs(filters["whole_number"], whole_number)
        self.assertIs(filters["smartva_gender"], smartva_gender)
        self.assertIs(filters["cert_date"], cert_date)
        self.assertTrue(callable(filters["user_timezone"]))

    def test_context_processor_order(self):
        self.assertEqual(
            [getattr(f, "__name__", repr(f)) for f in self.app.template_context_processors[None]],
            ["_default_template_ctx_processor", "_user_context_processor", "<lambda>",
             "inject_contextual_page_help", "inject_template_globals"],
        )

    def test_filters_render(self):
        with self.app.test_request_context("/"):
            g._login_user = self.app.login_manager.anonymous_user()
            try:
                rendered = render_template_string(
                    "{{ a|whole_number }} {{ b|smartva_gender }} {{ c|cert_date }} {{ d|user_timezone }}",
                    a="28.0", b=2, c="2026-01-05", d="2026-01-01T00:00:00Z",
                )
            finally:
                g.pop("_login_user", None)
        self.assertEqual(rendered, "28 Female 05-Jan-2026 2026-01-01 05:30:00")


class TemplateHelperOutputTests(BaseTestCase):
    @contextmanager
    def _as(self, user):
        with self.app.test_request_context("/"):
            g._login_user = user if user is not None else self.app.login_manager.anonymous_user()
            try:
                yield
            finally:
                g.pop("_login_user", None)

    def test_user_timezone_filter(self):
        tz_filter = self.app.jinja_env.filters["user_timezone"]
        naive = datetime(2026, 1, 1, 0, 0, 0)
        aware = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        cases = [
            (None, {}, ""),
            ("", {}, ""),
            ("not a date", {}, "not a date"),
            ("2026-01-01T00:00:00Z", {}, "2026-01-01 05:30:00"),
            ("2026-01-01T00:00:00+00:00", {}, "2026-01-01 05:30:00"),
            ("2026-01-01T00:00:00", {}, "2026-01-01 05:30:00"),
            (naive, {}, "2026-01-01 05:30:00"),
            (aware, {"format": "%H:%M"}, "05:30"),
        ]
        with self._as(None):
            for value, kwargs, expected in cases:
                with self.subTest(value=value):
                    self.assertEqual(tz_filter(value, **kwargs), expected)
        for tz_name, expected in (("UTC", "00:00"), ("Mars/Base", "05:30"), (None, "05:30"), ("", "05:30")):
            with self.subTest(tz=tz_name), self._as(types.SimpleNamespace(timezone=tz_name)):
                self.assertEqual(tz_filter(aware, "%H:%M"), expected)

    def test_inject_template_globals_anonymous(self):
        from app.services.icd11_licence import DIGITVA_ADDITION_LABEL, ICD11_CITATION
        from app.services.site_maintenance_service import get_site_maintenance_banner_context

        processor = next(
            f for f in self.app.template_context_processors[None] if f.__name__ == "inject_template_globals"
        )
        with self._as(None):
            context = processor()
            banner = get_site_maintenance_banner_context(is_authenticated=False, is_admin=False)
        now = datetime.now(pytz.UTC).astimezone(pytz.timezone("Asia/Kolkata"))
        self.assertEqual(
            context,
            {
                "current_year": now.year,
                "current_user_today": now.date().isoformat(),
                "site_maintenance_banner": banner,
                "icd11_citation": ICD11_CITATION,
                "digitva_addition_label": DIGITVA_ADDITION_LABEL,
                "site_maintenance_watcher_enabled": False,
                "site_maintenance_user_is_admin": False,
            },
        )

    def test_inject_template_globals_admin(self):
        processor = next(
            f for f in self.app.template_context_processors[None] if f.__name__ == "inject_template_globals"
        )
        with self._as(self.base_admin_user):
            context = processor()
        self.assertIs(context["site_maintenance_watcher_enabled"], True)
        self.assertIs(context["site_maintenance_user_is_admin"], True)

    def test_training_page_url_branches(self):
        training_page_url = self.app.jinja_env.globals["training_page_url"]
        with self.app.test_request_context("/"):
            with mock.patch("app.routes.expo_client.export_ready", return_value=True):
                self.assertEqual(training_page_url(), "/app/training")
            with mock.patch("app.routes.expo_client.export_ready", return_value=False):
                self.assertEqual(training_page_url(), "/demo/welcome")
