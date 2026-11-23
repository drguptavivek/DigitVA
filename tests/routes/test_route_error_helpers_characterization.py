"""Characterization of the route-local JSON error helpers and the blueprint
``no-store`` hooks (digitva-r8nh.5, first slice).

Pins, on the unchanged code, what each helper answers (status, exact body
bytes, mimetype) and what a real endpoint answers through it (status, body,
Cache-Control / Pragma / Expires), so delegating the helpers to
``request_helpers.error`` and dropping the blueprint ``no-store`` hooks
covered by ``cache_headers._NO_STORE_API_PREFIXES`` cannot change a reply.
Old APKs read ``body.code`` and the HTTP status only; both are pinned.

Governing docs: docs/current-state/api-v1.md ("Error body", "NQA and Social
Autopsy errors", the case list's no-store rule), docs/policy/api-v1.md,
docs/policy/offline-api-contract.md.
"""

import json
import re
import uuid
from datetime import UTC, datetime
from unittest import mock

from app import db, limiter
from app.hooks.cache_headers import _NO_STORE_API_PREFIXES
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
)
from app.routes.api import instruments, nqa, profile, reviewing, so
from app.services.reviewer_coding_service import ReviewerCodingError
from app.services.ui_string_service import UiStringError
from tests.base import BaseTestCase

_SUFFIX = uuid.uuid4().hex[:4].upper()
_JSON_OBJECT_REQUIRED = {"error": "A JSON object is required.", "code": "invalid_request"}


def _cache_headers(response):
    return (
        response.headers.get("Cache-Control"),
        response.headers.get("Pragma"),
        response.headers.get("Expires"),
    )


class HelperOutputTests(BaseTestCase):
    """Each helper, every argument shape its callers use, outside any hook."""

    def _assert_reply(self, rv, status, body):
        with self.app.test_request_context("/"):
            response = self.app.make_response(rv)
        self.assertEqual(response.status_code, status)
        # Exact bytes: jsonify's sorted, indented form in this config.
        self.assertEqual(response.get_data(as_text=True), json.dumps(body, indent=2, sort_keys=True) + "\n")
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(_cache_headers(response), (None, None, None))

    def test_instruments_json_error(self):
        self._assert_reply(
            instruments._json_error("Form version not found.", 404, "version_unknown"),
            404, {"error": "Form version not found.", "code": "version_unknown"},
        )

    def test_nqa_error(self):
        self._assert_reply(
            nqa._error("Active allocation required.", 403, "no_allocation"),
            403, {"error": "Active allocation required.", "code": "no_allocation"},
        )

    def test_so_error(self):
        self._assert_reply(
            so._error("remark is too long.", 422, "invalid_request"),
            422, {"error": "remark is too long.", "code": "invalid_request"},
        )

    def test_so_error_with_extra_key(self):
        self._assert_reply(
            so._error("m", 400, "invalid_request", missing_delay_levels=["delay_1"]),
            400, {"error": "m", "code": "invalid_request", "missing_delay_levels": ["delay_1"]},
        )

    def test_reviewing_error_without_processing_has_no_processing_key(self):
        expected = {"error": "m", "code": "not_available"}
        self._assert_reply(reviewing._error("m", 409, code="not_available"), 409, expected)
        self._assert_reply(reviewing._error("m", 409, code="not_available", processing=None), 409, expected)

    def test_reviewing_error_with_processing_and_extra(self):
        self._assert_reply(
            reviewing._error("m", 422, code="x", processing={"changed": True}, age_restriction={"a": 1}),
            422, {"error": "m", "code": "x", "age_restriction": {"a": 1}, "processing": {"changed": True}},
        )

    def test_reviewing_refusal_carries_messages_details_and_processing(self):
        exc = ReviewerCodingError(
            "Blocked.", 422, code="final_blocked", processing={"p": 1},
            details={"age_restriction": {"min": 1}}, messages=["one", "two"],
        )
        self._assert_reply(
            reviewing._refusal(exc), 422,
            {
                "error": "Blocked.", "code": "final_blocked", "messages": ["one", "two"],
                "age_restriction": {"min": 1}, "processing": {"p": 1},
            },
        )

    def test_reviewing_refusal_without_code_is_invalid_request(self):
        self._assert_reply(
            reviewing._refusal(ReviewerCodingError("No.", 403)),
            403, {"error": "No.", "code": "invalid_request"},
        )

    def test_profile_bearer_refusal_on_account_security(self):
        with self.app.test_request_context("/api/v1/profile/password/generate", method="POST"):
            with mock.patch("app.services.device_auth_service.request_bearer_token", return_value="tok"):
                response = self.app.make_response(profile._account_security_is_cookie_only())
        self.assertEqual(response.status_code, 403)
        body = {"error": "Sign in on the web to manage account security.", "code": "cookie_session_required"}
        self.assertEqual(response.get_data(as_text=True), json.dumps(body, indent=2, sort_keys=True) + "\n")
        self.assertEqual(response.mimetype, "application/json")


class EndpointErrorTests(BaseTestCase):
    """One real request per changed helper or inline site, through every hook."""

    BASE_PROJECT_ID = f"RE{_SUFFIX}"
    BASE_SITE_ID = f"E{_SUFFIX[:3]}"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_base_research_project_and_site()
        # A reviewer grant opens its gate only on a pair with an active form.
        db.session.add(VaForms(
            form_id=f"{cls.BASE_PROJECT_ID}{cls.BASE_SITE_ID}01", project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID, odk_form_id="R8NH5_FORM", odk_project_id="1",
            form_type="WHO 2022 VA", form_status=VaStatuses.active,
        ))
        db.session.flush()
        pair_id = db.session.scalar(db.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == cls.BASE_PROJECT_ID,
            VaProjectSites.site_id == cls.BASE_SITE_ID,
        ))
        cls.reviewer = cls._make_user(f"r8nh5.reviewer.{_SUFFIX.lower()}@test.local", "Reviewer123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.reviewer.user_id, role=VaAccessRoles.reviewer,
            scope_type=VaAccessScopeTypes.project_site, project_site_id=pair_id,
            notes="r8nh.5 characterization", grant_status=VaStatuses.active,
        ))
        cls.unverified = cls._make_user(f"r8nh5.unverified.{_SUFFIX.lower()}@test.local", "Unverified123")
        cls.unverified.email_verified = False
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()

    def _post(self, path, body):
        return self.client.post(path, json=body, headers=self._csrf_headers())

    def _assert(self, response, status, body, cache):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assertEqual(response.get_json(), body)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(_cache_headers(response), cache)

    def test_nqa_non_object_body(self):
        self._login(str(self.reviewer.user_id))
        self._assert(
            self._post("/api/v1/va/uuid:none/narrative-qa", [1]), 400, _JSON_OBJECT_REQUIRED, (None, None, None),
        )

    def test_so_non_object_body(self):
        self._login(str(self.reviewer.user_id))
        self._assert(
            self._post("/api/v1/va/uuid:none/social-autopsy", [1]), 400, _JSON_OBJECT_REQUIRED, (None, None, None),
        )

    def test_instrument_definition_without_project(self):
        self._login(self.base_admin_id)
        self._assert(
            self.client.get("/api/v1/instruments/WHO_2022_VA/definition"), 400,
            {"error": "project_id is required.", "code": "invalid_request"},
            (None, None, None),
        )

    def test_reviewing_finalize_non_object_body(self):
        self._login(str(self.reviewer.user_id))
        self._assert(
            self._post("/api/v1/reviewing/finalize/uuid:none", [1]), 400, _JSON_OBJECT_REQUIRED,
            (None, None, None),
        )

    def test_ui_string_pack_not_found(self):
        self._assert(
            self.client.get("/api/v1/ui-strings/en"), 404,
            {"error": "Translation not found.", "code": "not_found"},
            (None, None, None),
        )

    def test_ui_strings_unavailable(self):
        with mock.patch("app.routes.api.ui_strings.published_languages", side_effect=UiStringError("gone")):
            response = self.client.get("/api/v1/ui-strings")
        self._assert(response, 503, {"error": "UI strings are unavailable.", "code": "unavailable"}, (None, None, None))

    def test_ui_string_pack_unavailable(self):
        with mock.patch("app.routes.api.ui_strings.pack", side_effect=UiStringError("gone")):
            response = self.client.get("/api/v1/ui-strings/hi")
        self._assert(response, 503, {"error": "UI strings are unavailable.", "code": "unavailable"}, (None, None, None))

    def test_profile_terms_refused(self):
        self._login(self.base_admin_id)
        self._assert(
            self._post("/api/v1/profile/terms", [1]), 400,
            {"error": "Please accept the terms of use.", "code": "invalid_request"},
            (None, None, None),
        )

    def test_profile_password_generate_email_unverified(self):
        self._login(str(self.unverified.user_id))
        with self.client.session_transaction() as sess:
            sess["auth_verified_at"] = datetime.now(UTC).isoformat()
        self._assert(
            self._post("/api/v1/profile/password/generate", {}), 409,
            {"error": profile.EMAIL_UNVERIFIED_GENERATE_MESSAGE, "code": "email_unverified"},
            (None, None, None),
        )


class BlueprintNoStoreTests(BaseTestCase):
    """Every route of the blueprints whose own ``no-store`` after_request
    overlaps the app-level ``_NO_STORE_API_PREFIXES`` answers ``no-store``
    (and nothing else), errors included."""

    BLUEPRINTS = ("cases_api", "intake_api", "bundles_api")

    def setUp(self):
        super().setUp()
        limiter.reset()

    def _rules(self, blueprint):
        rules = [r for r in self.app.url_map.iter_rules() if r.endpoint.startswith(f"api_v1.{blueprint}.")]
        self.assertTrue(rules, blueprint)
        return rules

    def test_every_rule_sits_under_an_app_no_store_prefix(self):
        for blueprint in self.BLUEPRINTS:
            for rule in self._rules(blueprint):
                with self.subTest(rule=rule.rule):
                    self.assertTrue(rule.rule.startswith(_NO_STORE_API_PREFIXES), rule.rule)

    def test_every_route_answers_no_store_anonymous(self):
        for blueprint in self.BLUEPRINTS:
            for rule in self._rules(blueprint):
                path = re.sub(r"<[^>]+>", "x", rule.rule)
                for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                    with self.subTest(method=method, path=path):
                        response = self.client.open(path, method=method)
                        # Reached the route: neither unmatched nor a wrong method.
                        self.assertNotIn(response.status_code, (404, 405))
                        self.assertEqual(_cache_headers(response), ("no-store", None, None))

    def test_signed_in_replies_are_no_store(self):
        self._login(self.base_admin_id)
        for path in ("/api/v1/cases", "/api/v1/cases/stage-counts", "/api/v1/intake/drafts"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(_cache_headers(response), ("no-store", None, None))
