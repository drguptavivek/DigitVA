"""WHO ICD-11 client contract tests."""

from unittest.mock import patch

from requests import Response

from app.services.who_icd_api import (
    WhoIcdApiUnavailable,
    get_icd11_codeinfo,
    proxy_who_icd_request,
)
from tests.base import BaseTestCase


def _response(status: int, payload: bytes = b"{}"):
    response = Response()
    response.status_code = status
    response._content = payload
    response.headers["Content-Type"] = "application/json"
    return response


class TestWhoIcdApi(BaseTestCase):
    def test_proxy_injects_who_headers_and_does_not_forward_credentials(self):
        response = _response(200, b'{"ok":true}')
        response.raw = type(
            "Raw",
            (),
            {"read": lambda self, limit: b'{"ok":true}', "close": lambda self: None},
        )()
        with patch(
            "app.services.who_icd_api.requests.request", return_value=response
        ) as request:
            result = proxy_who_icd_request(
                "icd/release/11/2026-01/mms/search",
                method="GET",
                query_string=b"q=diabetes",
            )

        self.assertEqual(result.content, b'{"ok":true}')
        request.assert_called_once()
        args, kwargs = request.call_args
        self.assertEqual(args, ("GET", "http://icd_api_service/icd/release/11/2026-01/mms/search?q=diabetes"))
        self.assertEqual(kwargs["headers"]["API-Version"], "v2")
        self.assertEqual(kwargs["headers"]["Accept"], "application/json")
        self.assertEqual(kwargs["headers"]["Accept-Language"], "en")
        self.assertTrue(kwargs["stream"])

    def test_codeinfo_returns_json_object(self):
        with patch(
            "app.services.who_icd_api.proxy_who_icd_request",
            return_value=_response(200, b'{"code":"GB61.Z","stemId":"uri"}'),
        ) as proxy:
            payload = get_icd11_codeinfo("GB61.Z")

        self.assertEqual(payload, {"code": "GB61.Z", "stemId": "uri"})
        proxy.assert_called_once_with(
            "icd/release/11/2026-01/mms/codeinfo/GB61.Z"
        )

    def test_codeinfo_returns_none_for_unknown_expression(self):
        with patch(
            "app.services.who_icd_api.proxy_who_icd_request",
            return_value=_response(404, b"not found"),
        ):
            self.assertIsNone(get_icd11_codeinfo("GB61.Z"))

    def test_codeinfo_fails_closed_on_malformed_json(self):
        with patch(
            "app.services.who_icd_api.proxy_who_icd_request",
            return_value=_response(200, b"not-json"),
        ):
            with self.assertRaises(WhoIcdApiUnavailable):
                get_icd11_codeinfo("GB61.Z")
