"""App-wide request body cap (digitva-ssg7.9).

Config.MAX_CONTENT_LENGTH bounds every body before the CSRF hook parses it;
the table in app/__init__.py raises it for the uploads that need more.
"""
import io

from werkzeug.exceptions import RequestEntityTooLarge

from tests.base import BaseTestCase

OVER_DEFAULT = 3 * 1024 * 1024


class RequestBodyLimitTests(BaseTestCase):
    def test_default_cap_is_two_mib(self):
        self.assertEqual(self.app.config["MAX_CONTENT_LENGTH"], 2 * 1024 * 1024)

    def test_oversize_form_to_ordinary_route_is_413_before_csrf(self):
        response = self.client.post(
            "/vaauth/valogin",
            data={"file": (io.BytesIO(b"x" * OVER_DEFAULT), "a.bin")},
        )
        self.assertEqual(response.status_code, 413)

    def test_upload_route_accepts_body_over_default(self):
        # No CSRF token: the hook parses the form (no 413) and then refuses with 400.
        response = self.client.post("/admin/api/form-types/import", data={"file": (io.BytesIO(b"x" * OVER_DEFAULT), "a.json")})
        self.assertEqual(response.status_code, 400)

    def test_upload_route_still_refuses_over_its_own_cap(self):
        response = self.client.post(
            "/admin/api/organization/1/project-users/import",
            data={"file": (io.BytesIO(b"x" * 2 * 1024 * 1024), "a.csv")},
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["code"], "payload_too_large")

    def test_attachment_put_accepts_body_over_default(self):
        response = self.client.put(
            "/api/v1/intake/drafts/d/attachments/a",
            data=b"x" * OVER_DEFAULT,
            content_type="application/octet-stream",
        )
        self.assertNotEqual(response.status_code, 413)

    def test_api_v1_413_uses_json_error_shape(self):
        with self.app.test_request_context("/api/v1/anything", method="POST"):
            body, status = self.app.handle_user_exception(RequestEntityTooLarge())
        self.assertEqual(status, 413)
        self.assertEqual(body.get_json(), {"error": "The upload exceeds the 2 MB limit.", "code": "payload_too_large"})

    # One concrete URL per _upload_limits row, keyed by (method, pattern).
    ROW_URLS = {
        ("PUT", r"/api/v1/intake/drafts/[^/]+/attachments/[^/]+"): "/api/v1/intake/drafts/d/attachments/a",
        ("POST", r"/api/v1/intake/bundles(/validate)?"): "/api/v1/intake/bundles/validate",
        ("POST", r"/admin/api/organization/[^/]+/project-users/import"): "/admin/api/organization/1/project-users/import",
        ("POST", r"/admin/api/organization/[^/]+/import"): "/admin/api/organization/1/import",
        ("POST", r"/admin/api/instrument-translations/[^/]+/[^/]+/(import|xliff)"): "/admin/api/instrument-translations/a/b/import",
        ("POST", r"/admin/api/form-types/import"): "/admin/api/form-types/import",
        ("POST", r"/admin/api/(icd10/2019-2|icd11/mms)/policy-import"): "/admin/api/icd11/mms/policy-import",
        ("POST", r"/admin/api/cod-bucket-schemes/[^/]+/import"): "/admin/api/cod-bucket-schemes/1/import",
        ("POST", r"/api/v1/icd10/2019-2/policy-import"): "/api/v1/icd10/2019-2/policy-import",
    }

    def _table(self):
        hook = next(f for f in self.app.before_request_funcs[None] if f.__name__ == "_raise_upload_body_limit")
        return next(c.cell_contents for c in hook.__closure__ if isinstance(c.cell_contents, tuple))

    def test_every_upload_limit_row_has_a_url_and_admits_a_body_over_default(self):
        table = self._table()
        self.assertEqual({(m, p.pattern) for m, p, _ in table}, set(self.ROW_URLS))
        default = self.app.config["MAX_CONTENT_LENGTH"]
        for method, pattern, cap in table:
            url = self.ROW_URLS[(method, pattern.pattern)]
            with self.subTest(method=method, url=url):
                self.assertIsNotNone(pattern.fullmatch(url))
                # One row's cap sits below the default; stay just under it.
                size = default + 1 if default + 1 < cap else cap - 1024
                if method == "PUT":
                    response = self.client.put(url, data=b"x" * size, content_type="application/octet-stream")
                else:
                    response = self.client.post(url, data={"file": (io.BytesIO(b"x" * size), "a.bin")})
                self.assertNotEqual(response.status_code, 413)
