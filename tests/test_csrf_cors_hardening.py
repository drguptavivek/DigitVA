"""CSRF exemptions are named per view, sign-in cookies stay same-site, and no
route sends CORS headers (docs/policy/api-v1.md rule 5).

What each exempt view answers is pinned in tests/fixtures/route_auth_matrix.json;
this file guards the rules that keep that safe as routes are added."""

import unittest

from app import _require_same_site_cookies, create_app, csrf
from app.routes.api import auth as auth_routes
from config import TestConfig
from tests.base import BaseTestCase


class SameSiteCookieStartupTests(unittest.TestCase):
    def test_lax_and_strict_are_kept_and_anything_else_becomes_lax_with_an_error(self):
        for key in ("SESSION_COOKIE_SAMESITE", "REMEMBER_COOKIE_SAMESITE"):
            other = ({"SESSION_COOKIE_SAMESITE", "REMEMBER_COOKIE_SAMESITE"} - {key}).pop()
            for good in ("Lax", "Strict"):
                config = {key: good, other: "Lax"}
                _require_same_site_cookies(config)
                self.assertEqual(config[key], good)
            for bad in ("None", "none", None, ""):
                with self.subTest(key=key, value=bad):
                    config = {key: bad, other: "Lax"}
                    with self.assertLogs("app", level="ERROR") as logs:
                        _require_same_site_cookies(config)
                    self.assertEqual(config[key], "Lax")
                    self.assertIn(key, logs.output[0])

    def test_create_app_starts_with_lax_when_the_env_says_none(self):
        class NoneSameSite(TestConfig):
            SESSION_COOKIE_SAMESITE = "None"

        with self.assertLogs("app", level="ERROR"):
            app = create_app(NoneSameSite, register_routes=False)
        self.assertEqual(app.config["SESSION_COOKIE_SAMESITE"], "Lax")


class CsrfExemptionTests(BaseTestCase):
    def test_auth_api_is_exempt_view_by_view_not_as_a_blueprint(self):
        blueprint = self.app.blueprints["api_v1.auth_api"]
        self.assertIsNotNone(blueprint)
        self.assertNotIn(blueprint, csrf._exempt_blueprints)
        exempt = {name.rsplit(".", 1)[1] for name in csrf._exempt_views
                  if name.startswith(f"{auth_routes.__name__}.")}
        self.assertEqual(exempt, set(auth_routes.CSRF_EXEMPT_VIEWS))

    def test_every_named_view_is_a_registered_route(self):
        registered = {
            (view.__module__, view.__name__)
            for endpoint, view in self.app.view_functions.items()
            if endpoint.startswith("api_v1.auth_api.")
        }
        for name in auth_routes.CSRF_EXEMPT_VIEWS:
            self.assertIn((auth_routes.__name__, name), registered, name)


class NoCorsHeaderTests(BaseTestCase):
    """No route lets another site read a reply with the user's credentials."""

    PATHS = (
        ("GET", "/api/v1/me/access"),
        ("OPTIONS", "/api/v1/me/access"),
        ("POST", "/api/v1/auth/sessions"),
        ("OPTIONS", "/api/v1/auth/sessions"),
        ("GET", "/api/v1/server-version"),
        ("GET", "/"),
    )

    def test_no_access_control_header_for_a_foreign_origin(self):
        # Present first: the probe reaches a real route, not a 404.
        self.assertEqual(self.client.get("/api/v1/me/access").status_code, 401)
        for method, path in self.PATHS:
            with self.subTest(method=method, path=path):
                response = self.client.open(
                    path, method=method,
                    headers={"Origin": "https://other-site.example",
                             "Access-Control-Request-Method": "POST"},
                )
                leaked = [h for h in response.headers.keys() if h.lower().startswith("access-control-")]
                self.assertEqual(leaked, [], (method, path, response.status_code))
