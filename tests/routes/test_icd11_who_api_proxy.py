"""Authenticated WHO ICD-11 API proxy and codeinfo client checks."""

from unittest.mock import Mock, patch

from requests import Response

from app.services.who_icd_api import WhoIcdApiUnavailable
from tests.base import BaseTestCase


def _response(status: int, payload: bytes = b"{}", content_type: str = "application/json"):
    response = Response()
    response.status_code = status
    response._content = payload
    response.headers["Content-Type"] = content_type
    return response


class TestIcd11WhoApiProxy(BaseTestCase):
    SID = "uuid:test-who-api-proxy"

    def setUp(self):
        super().setUp()
        self._login(self.base_admin_id)

    def _patch_access(self):
        return patch.multiple(
            "app.routes.api.icd11",
            _require_coding_or_reviewing_access=Mock(return_value=None),
            get_icd_classification_for_submission=Mock(return_value="icd11"),
        )

    def test_proxy_forwards_bounded_request_with_required_who_headers(self):
        upstream = _response(200, b'{"code":"GB61.Z"}')
        with self._patch_access(), patch(
            "app.routes.api.icd11.proxy_who_icd_request", return_value=upstream
        ) as proxy:
            response = self.client.get(
                f"/api/v1/icd11/who-api/{self.SID}/icd/release/11/2026-01/mms"
                "?q=diabetes"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"code": "GB61.Z"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        proxy.assert_called_once_with(
            "icd/release/11/2026-01/mms",
            method="GET",
            query_string=b"q=diabetes",
            body=b"",
            content_type=None,
        )

    def test_analytics_is_discarded_without_contacting_upstream(self):
        with self._patch_access(), patch(
            "app.routes.api.icd11.proxy_who_icd_request"
        ) as proxy:
            response = self.client.post(
                f"/api/v1/icd11/who-api/{self.SID}/analytics/clientanalytics",
                json={"search": "diabetic nephropathy"},
            )

        self.assertEqual(response.status_code, 204)
        proxy.assert_not_called()

    def test_proxy_preserves_bounded_json_post_for_ect_search(self):
        upstream = _response(200, b"[]")
        with self._patch_access(), patch(
            "app.routes.api.icd11.proxy_who_icd_request", return_value=upstream
        ) as proxy:
            response = self.client.post(
                f"/api/v1/icd11/who-api/{self.SID}/icd/release/11/2026-01/mms/search",
                json={"q": "diabetes"},
            )

        self.assertEqual(response.status_code, 200)
        kwargs = proxy.call_args.kwargs
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(kwargs["content_type"], "application/json")
        self.assertEqual(self.app.json.loads(kwargs["body"]), {"q": "diabetes"})

    def test_proxy_preserves_ect_multipart_search(self):
        upstream = _response(200, b"[]")
        with self._patch_access(), patch(
            "app.routes.api.icd11.proxy_who_icd_request", return_value=upstream
        ) as proxy:
            response = self.client.post(
                f"/api/v1/icd11/who-api/{self.SID}/icd/release/11/2026-01/mms/search",
                data={"q": "diabetic nephropathy"},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        kwargs = proxy.call_args.kwargs
        self.assertEqual(kwargs["content_type"], "application/x-www-form-urlencoded")
        self.assertEqual(kwargs["body"], b"q=diabetic+nephropathy")

    def test_upstream_failure_is_a_controlled_service_unavailable(self):
        with self._patch_access(), patch(
            "app.routes.api.icd11.proxy_who_icd_request",
            side_effect=WhoIcdApiUnavailable("unavailable"),
        ):
            response = self.client.get(
                f"/api/v1/icd11/who-api/{self.SID}/icd/release/11/2026-01/mms"
            )

        self.assertEqual(response.status_code, 503)

    def test_submission_access_is_checked_before_proxying(self):
        with patch(
            "app.routes.api.icd11._require_coding_or_reviewing_access",
            return_value=({"error": "denied"}, 403),
        ), patch("app.routes.api.icd11.proxy_who_icd_request") as proxy:
            response = self.client.get(
                f"/api/v1/icd11/who-api/{self.SID}/icd/entity/123"
            )

        self.assertEqual(response.status_code, 403)
        proxy.assert_not_called()

    def test_forbidden_resource_is_rejected_before_forwarding(self):
        with self._patch_access(), patch(
            "app.services.who_icd_api.requests.request"
        ) as upstream:
            response = self.client.get(
                f"/api/v1/icd11/who-api/{self.SID}/swagger/index.html"
            )

        self.assertEqual(response.status_code, 400)
        upstream.assert_not_called()

    def test_selection_check_returns_canonical_expression_and_title(self):
        previous_csrf = self.app.config["WTF_CSRF_ENABLED"]
        self.app.config["WTF_CSRF_ENABLED"] = False
        try:
            with self._patch_access(), patch(
                "app.routes.api.icd11.validate_icd11_mms_coding_value_for_submission"
            ) as validate, patch(
                "app.routes.api.icd11.build_icd11_provenance",
                return_value={
                    "code": "1G40.0&XN8Q",
                    "title": "Canonical title",
                    "selected_text": "Example title",
                    "release": "2026-01",
                    "linearization_uri": "http://id.who.int/icd/release/11/2026-01/mms/1",
                    "foundation_uri": None,
                    "codeinfo_uri": "http://id.who.int/icd/release/11/2026-01/mms/codeinfo/1G40.0%26XN8Q",
                },
            ):
                response = self.client.post(
                    f"/api/v1/icd11/selection-check/{self.SID}",
                    json={"code": "1g40.0&xn8q", "selectedText": "  Example title  "},
                )
        finally:
            self.app.config["WTF_CSRF_ENABLED"] = previous_csrf

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "code": "1G40.0&XN8Q",
                "title": "Canonical title",
                "selectedText": "Example title",
                "value": "1G40.0&XN8Q Example title",
                "provenance": {
                    "code": "1G40.0&XN8Q",
                    "title": "Canonical title",
                    "selected_text": "Example title",
                    "release": "2026-01",
                    "linearization_uri": "http://id.who.int/icd/release/11/2026-01/mms/1",
                    "foundation_uri": None,
                    "codeinfo_uri": "http://id.who.int/icd/release/11/2026-01/mms/codeinfo/1G40.0%26XN8Q",
                },
            },
        )
        validate.assert_called_once_with(
            self.SID, "1g40.0&xn8q Example title"
        )

    def test_selection_check_keeps_normal_csrf_protection(self):
        with patch(
            "app.routes.api.icd11._require_coding_or_reviewing_access"
        ) as access:
            response = self.client.post(
                f"/api/v1/icd11/selection-check/{self.SID}",
                json={"code": "GB61.Z", "selectedText": "Diabetic nephropathy"},
            )

        self.assertEqual(response.status_code, 400)
        access.assert_not_called()
