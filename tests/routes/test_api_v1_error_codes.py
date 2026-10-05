"""Every /api/v1 error reply is {"error": <message>, "code": <machine code>}.

Policy: docs/policy/api-v1.md (rule 3). The one exception is
/api/v1/doris-clinical/*, which keeps its nested body. The static sweep below
is the guard; the request tests show one real refusal per converted blueprint
with the status unchanged.
"""
import ast
import pathlib
from types import SimpleNamespace
from unittest import mock

from werkzeug.exceptions import Forbidden, RequestEntityTooLarge, UnprocessableEntity

from app import db
from app.models import VaAccessRoles, VaAccessScopeTypes, VaStatuses, VaUserAccessGrants
from app.routes.api import request_helpers
from tests.base import BaseTestCase

API_DIR = pathlib.Path(request_helpers.__file__).parent


def _assert_error(test, response, status, code=None):
    test.assertEqual(response.status_code, status)
    body = response.get_json()
    test.assertIsInstance(body["error"], str)
    test.assertTrue(body["error"])
    test.assertTrue(body["code"])
    if code is not None:
        test.assertEqual(body["code"], code)
    return body


class StaticSweepTests(BaseTestCase):
    def test_no_error_dict_without_code_under_routes_api(self):
        files = [p for p in sorted(API_DIR.rglob("*.py")) if p.name != "doris_clinical.py"]
        self.assertGreater(len(files), 20)  # the sweep found the blueprints
        offenders = []
        for path in files:
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Dict):
                    continue
                keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
                if "error" in keys and "code" not in keys:
                    offenders.append(f"{path.relative_to(API_DIR)}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_code_less_helpers_are_gone(self):
        for name in ("coding", "coding_search_demo", "icd10", "organization", "profile"):
            tree = ast.parse((API_DIR / f"{name}.py").read_text())
            local = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_error"]
            self.assertEqual(local, [], name)


class HelperTests(BaseTestCase):
    def test_code_defaults_from_status(self):
        with self.app.test_request_context("/api/v1/x"):
            for status, code in (
                (400, "invalid_request"), (403, "forbidden"), (404, "not_found"), (409, "conflict"),
                (418, "invalid_request"), (500, "server_error"), (503, "unavailable"),
            ):
                response, got_status = request_helpers.error("m", status_code=status)
                self.assertEqual((got_status, response.get_json()), (status, {"error": "m", "code": code}))

    def test_explicit_code_and_extra_keys_win(self):
        with self.app.test_request_context("/api/v1/x"):
            response, status = request_helpers.error("m", "custom", 409, stored={"a": 1})
        self.assertEqual(status, 409)
        self.assertEqual(response.get_json(), {"error": "m", "code": "custom", "stored": {"a": 1}})


class ConvertedBlueprintTests(BaseTestCase):
    """One real refusal per blueprint that used to answer a code-less body."""

    def test_icd10_policy_import_file_required(self):
        self._login(self.base_admin_id)
        response = self.client.post("/api/v1/icd10/2019-2/policy-import", headers=self._csrf_headers())
        _assert_error(self, response, 400, "invalid_request")

    def test_icd10_coding_search_unknown_submission(self):
        self._login(self.base_admin_id)
        response = self.client.get("/api/v1/icd10/2019-2/coding-search/NO-SUCH-SID?q=fever")
        _assert_error(self, response, 404, "not_found")

    def test_icd11_selection_check_unknown_submission(self):
        self._login(self.base_admin_id)
        response = self.client.post(
            "/api/v1/icd11/selection-check/NO-SUCH-SID", json={}, headers=self._csrf_headers()
        )
        _assert_error(self, response, 404, "not_found")

    def test_coding_allocation_refusal(self):
        self._login(self.base_admin_id)
        response = self.client.post(
            "/api/v1/coding/allocation", json={"sid": "NO-SUCH-SID"}, headers=self._csrf_headers()
        )
        _assert_error(self, response, 404, "not_found")

    def test_coding_search_demo_bad_classification(self):
        self._login(self.base_admin_id)
        response = self.client.get("/api/v1/coding-search-demo/search?classification=x")
        _assert_error(self, response, 400, "invalid_request")

    def test_va_definitions_bad_classification(self):
        self._login(self.base_admin_id)
        response = self.client.get("/api/v1/va-definitions/for-icd?code=x&classification=x")
        _assert_error(self, response, 400, "invalid_request")

    def test_workflow_unknown_submission(self):
        self._login(self.base_admin_id)
        response = self.client.get("/api/v1/workflow/events/NO-SUCH-SID")
        _assert_error(self, response, 404, "not_found")

    def test_area_missing_project(self):
        self._login(self.base_project_pi_id)
        response = self.client.get("/api/v1/area/staff")
        _assert_error(self, response, 400, "invalid_request")

    def test_cod_buckets_form_outside_scope(self):
        self._login(self.base_admin_id)
        response = self.client.get("/api/v1/cod-buckets/aggregates?form_id=NO-SUCH-FORM")
        _assert_error(self, response, 403, "forbidden")

    def test_data_management_bad_include(self):
        self._login(self.base_admin_id)
        response = self.client.get("/api/v1/data-management/submissions/unrouted?include=bad")
        _assert_error(self, response, 400, "invalid_request")

    def test_dm_kpi_sync_system_level_refused_has_code(self):
        # Present first: a direct grant reads the figures.
        self._login(self.base_admin_id)
        self.assertEqual(self.client.get("/api/v1/analytics/dm-kpi/sync/status").status_code, 200)
        # A unit-only data manager has no direct grant.
        with mock.patch("app.routes.api.dm_kpi.dm_kpi_sync.dm_scope",
                        return_value=SimpleNamespace(direct=False)):
            response = self.client.get("/api/v1/analytics/dm-kpi/sync/status")
        _assert_error(self, response, 403, "forbidden")

    def test_analytics_refresh_failure(self):
        db.session.add(VaUserAccessGrants(
            user_id=self.base_project_pi_user.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project, project_id=self.BASE_PROJECT_ID,
            grant_status=VaStatuses.active,
        ))
        db.session.flush()
        self._login(self.base_project_pi_id)
        with mock.patch(
            "app.routes.api.analytics.refresh_submission_analytics_mv", side_effect=RuntimeError("boom")
        ):
            response = self.client.post("/api/v1/analytics/mv/refresh", headers=self._csrf_headers())
        body = _assert_error(self, response, 500, "server_error")
        self.assertNotIn("boom", body["error"])

    def test_organization_unknown_project(self):
        self._login(self.base_admin_id)
        response = self.client.get("/api/v1/organization/NO-SUCH-PROJECT/units")
        _assert_error(self, response, 404, "not_found")

    def test_profile_timezone_required(self):
        self._login(self.base_admin_id)
        response = self.client.patch("/api/v1/profile/timezone", json={}, headers=self._csrf_headers())
        _assert_error(self, response, 400, "invalid_request")


class SafetyNetTests(BaseTestCase):
    """Any other HTTPException on /api/v1 answers JSON; elsewhere it is unchanged."""

    def _handle(self, path, exc):
        with self.app.test_request_context(path):
            return self.app.make_response(self.app.handle_user_exception(exc))

    def test_unsupported_method(self):
        self._login(self.base_admin_id)
        response = self.client.delete("/api/v1/workflow/events/NO-SUCH-SID", headers=self._csrf_headers())
        _assert_error(self, response, 405, "method_not_allowed")

    def test_other_4xx_on_api_path_is_json_with_code(self):
        response = self._handle("/api/v1/anything", UnprocessableEntity())
        _assert_error(self, response, 422, "unprocessable")
        response = self._handle("/api/v1/anything", RequestEntityTooLarge())
        _assert_error(self, response, 413, "payload_too_large")

    def test_403_on_api_path_is_json(self):
        response = self._handle("/api/v1/anything", Forbidden())
        _assert_error(self, response, 403, "forbidden")

    def test_non_api_path_is_unchanged(self):
        response = self._handle("/anything", UnprocessableEntity())
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(response.get_json(silent=True))
        response = self._handle("/anything", Forbidden())
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(response.get_json(silent=True))


class TermsRefusalTests(BaseTestCase):
    def test_terms_pending_error_is_a_message_and_code_is_unchanged(self):
        self.base_project_pi_user.pw_reset_t_and_c = False
        db.session.flush()
        self._login(self.base_project_pi_id)
        response = self.client.get("/api/v1/profile/")
        body = _assert_error(self, response, 403, "terms_required")
        self.assertEqual(body["error"], "Accept the terms of use to continue.")
        self.assertIn("redirect_url", body)
