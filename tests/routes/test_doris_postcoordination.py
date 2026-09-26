"""Public and clinical guidance routes retain their respective access gates."""

import re
from unittest.mock import patch

from requests import Response

from app.public_doris import create_public_doris_app
from app.routes.api.doris_clinical import clinical_postcoordination
from tests.base import BaseTestCase


def test_public_guidance_requires_csrf_and_returns_normalized_result():
    app = create_public_doris_app({
        "TESTING": True, "SECRET_KEY": "guidance-test", "SESSION_COOKIE_SECURE": False,
    })
    client = app.test_client()
    path = "/api/v1/doris-demo/postcoordination"
    body = {"schema_version": 1, "code": "1B12.2"}
    denied = client.post(path, json=body)
    assert denied.status_code == 400
    match = re.search(rb'data-csrf="([^"]+)"', client.get("/help/doris-demo").data)
    assert match
    with patch(
        "app.public_doris.routes.get_postcoordination",
        return_value={"schema_version": 1, "release": "2026-01", "axes": []},
    ) as service:
        allowed = client.post(path, json=body, headers={"X-CSRFToken": match[1].decode()})
    assert allowed.status_code == 200
    assert allowed.get_json()["release"] == "2026-01"
    service.assert_called_once_with("1B12.2")


def test_public_terms_uses_who_availability_even_for_leaf():
    app = create_public_doris_app({
        "TESTING": True, "SECRET_KEY": "guidance-search-test", "SESSION_COOKIE_SECURE": False,
    })
    client = app.test_client()
    match = re.search(rb'data-csrf="([^"]+)"', client.get("/help/doris-demo").data)
    assert match
    upstream = Response()
    upstream.status_code = 200
    upstream._content = (
        b'{"destinationEntities":[{"theCode":"1B12.2","id":"http://id.who.int/x",'
        b'"title":"Tuberculosis of ear","isLeaf":true,'
        b'"postcoordinationAvailability":1}],"resultChopped":false}'
    )
    with patch("app.public_doris.routes.proxy_who_icd_request", return_value=upstream):
        response = client.post(
            "/api/v1/doris-demo/terms",
            json={"schema_version": 1, "query": "tuberculosis"},
            headers={"X-CSRFToken": match[1].decode()},
        )
    assert response.status_code == 200
    item = response.get_json()["items"][0]
    assert item["postcoordination"] is True
    assert item["postcoordination_availability"] == 1


class TestClinicalGuidanceAccess(BaseTestCase):
    def test_context_gate_runs_before_guidance_service(self):
        with self.app.test_request_context(json={"schema_version": 1, "code": "1B12.2"}):
            with (
                patch(
                    "app.routes.api.doris_clinical._require_terminology_context",
                    return_value=(None, ({"error": "ACTIVE_ALLOCATION_REQUIRED"}, 403)),
                ),
                patch("app.routes.api.doris_clinical.get_postcoordination") as service,
            ):
                result = clinical_postcoordination.__wrapped__("SID-1")
        assert result[1] == 403
        service.assert_not_called()

    def test_valid_context_and_schema_call_guidance_service(self):
        with self.app.test_request_context(json={"schema_version": 1, "code": "1B12.2"}):
            with (
                patch(
                    "app.routes.api.doris_clinical._require_terminology_context",
                    return_value=(object(), None),
                ),
                patch(
                    "app.routes.api.doris_clinical.get_postcoordination",
                    return_value={"schema_version": 1, "release": "2026-01", "axes": []},
                ) as service,
            ):
                result = clinical_postcoordination.__wrapped__("SID-1")
        assert result.get_json()["release"] == "2026-01"
        service.assert_called_once_with("1B12.2")
