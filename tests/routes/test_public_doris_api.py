"""Contract tests for the isolated, database-free public DORIS service."""

from __future__ import annotations

import re
from concurrent.futures import TimeoutError
from pathlib import Path
from unittest.mock import Mock, patch

from flask import current_app
from requests import Response

from app.public_doris import create_public_doris_app
from app.services.doris_certificate import DorisCertificateError, DorisFieldError


def _upstream(payload: bytes) -> Response:
    response = Response()
    response.status_code = 200
    response._content = payload
    return response


class TestPublicDorisApi:
    def setup_method(self):
        self.app = create_public_doris_app(
            {
                "TESTING": True,
                "SECRET_KEY": "public-doris-test-secret",
                "SESSION_COOKIE_SECURE": False,
            }
        )
        self.client = self.app.test_client()

    def _csrf(self):
        response = self.client.get("/help/doris-demo")
        assert response.status_code == 200
        match = re.search(rb'data-csrf="([^"]+)"', response.data)
        assert match
        return match.group(1).decode()

    def test_page_and_config_are_public_and_use_separate_session_cookie(self):
        response = self.client.get("/help/doris-demo")
        assert response.status_code == 200
        assert "digitva_doris_public_session=" in response.headers["Set-Cookie"]

        config = self.client.get("/api/v1/doris-demo/config")
        assert config.status_code == 200
        payload = config.get_json()
        assert payload["schema_version"] == 1
        assert payload["icd_release"] == "2026-01"
        assert len(payload["examples"]) == 6
        assert set(payload["examples"][0]) == {"id", "label", "purpose", "certificate"}

    def test_custom_posts_require_csrf_but_read_only_ect_proxy_does_not(self):
        denied = self.client.post(
            "/api/v1/doris-demo/codeinfo",
            json={"schema_version": 1, "code": "1B10.Z"},
        )
        assert denied.status_code == 400
        assert denied.get_json()["error"]["code"] == "CSRF_FAILED"

        with patch(
            "app.public_doris.routes.proxy_who_icd_request",
            return_value=_upstream(b"{}"),
        ):
            allowed = self.client.post(
                "/api/v1/doris-demo/who-api/icd/release/11/2026-01/mms/search",
                json={"q": "diabetes"},
            )
        assert allowed.status_code == 200

    def test_codeinfo_and_selection_check_return_normalized_items(self):
        token = self._csrf()
        item = {
            "code": "1B10.Z",
            "title": "Respiratory tuberculosis",
            "uri": "http://id.who.int/icd/release/11/2026-01/mms/882244568/unspecified",
            "release": "2026-01",
            "postcoordination": False,
        }
        headers = {"X-CSRFToken": token}
        with patch("app.public_doris.routes._codeinfo_item", return_value=item):
            response = self.client.post(
                "/api/v1/doris-demo/codeinfo",
                json={"schema_version": 1, "code": "1B10.Z"},
                headers=headers,
            )
            selected = self.client.post(
                "/api/v1/doris-demo/selection-check",
                json={"schema_version": 1, "code": item["code"], "uri": item["uri"]},
                headers=headers,
            )
        assert response.get_json() == {"schema_version": 1, "item": item}
        assert selected.get_json() == {"schema_version": 1, "item": item}

    def test_terms_normalizes_and_strips_upstream_markup(self):
        token = self._csrf()
        upstream = _upstream(
            b'{"destinationEntities":[{"theCode":"5A11","id":"http://id.who.int/x",'
            b'"title":"<em>Type 2</em> diabetes","matchingPVs":["diabetes"]}],'
            b'"resultChopped":false}'
        )
        with patch("app.public_doris.routes.proxy_who_icd_request", return_value=upstream):
            response = self.client.post(
                "/api/v1/doris-demo/terms",
                json={"schema_version": 1, "query": "diabetes", "limit": 20, "cursor": None},
                headers={"X-CSRFToken": token},
            )
        assert response.status_code == 200
        assert response.get_json()["items"][0]["title"] == "Type 2 diabetes"
        assert response.get_json()["items"][0]["matching_text"] == "diabetes"

    def test_process_maps_validation_dual_failure_capacity_and_deadline(self):
        token = self._csrf()
        headers = {"X-CSRFToken": token}
        request_payload = {"schema_version": 1, "client_revision": 2, "certificate": {}}
        invalid = DorisCertificateError(
            [DorisFieldError("certificate.Part1", "Enter at least one Part I line.")]
        )
        with patch("app.public_doris.routes.process_certificate", side_effect=invalid):
            response = self.client.post(
                "/api/v1/doris-demo/process", json=request_payload, headers=headers
            )
        assert response.status_code == 422
        assert response.get_json()["error"]["fields"] == [
            {
                "path": "certificate.Part1",
                "message": "Enter at least one Part I line.",
            }
        ]

        dual_failure = {
            "doris": {"status": "unavailable", "result": None},
            "codedit": {"status": "timeout", "result": None},
        }
        with patch("app.public_doris.routes.process_certificate", return_value=dual_failure):
            response = self.client.post(
                "/api/v1/doris-demo/process", json=request_payload, headers=headers
            )
        assert response.status_code == 503

        with patch("app.public_doris.routes._capacity.acquire", return_value=False):
            busy = self.client.post(
                "/api/v1/doris-demo/process", json=request_payload, headers=headers
            )
        assert busy.status_code == 429
        assert busy.get_json()["error"]["code"] == "PROCESS_BUSY"

        future = Mock()
        future.result.side_effect = TimeoutError
        with patch("app.public_doris.routes._executor.submit", return_value=future):
            timed_out = self.client.post(
                "/api/v1/doris-demo/process", json=request_payload, headers=headers
            )
        assert timed_out.status_code == 503
        assert timed_out.get_json()["error"]["code"] == "PROCESS_TIMEOUT"

    def test_process_worker_has_public_flask_app_context(self):
        token = self._csrf()
        result = {
            "doris": {"status": "completed", "result": {}},
            "codedit": {"status": "completed", "result": {}},
        }

        def process_in_context(*_args, **_kwargs):
            assert current_app.name == "digitva_public_doris"
            return result

        with patch("app.public_doris.routes.process_certificate", side_effect=process_in_context):
            response = self.client.post(
                "/api/v1/doris-demo/process",
                json={"schema_version": 1, "client_revision": 1, "certificate": {}},
                headers={"X-CSRFToken": token},
            )
        assert response.status_code == 200

    def test_runtime_split_and_access_log_exclude_query_strings(self):
        root = Path(__file__).resolve().parents[2]
        nginx = (root / "deploy/doris-public-nginx.conf").read_text()
        boot = (root / "boot-public-doris.sh").read_text()
        assert "location = /help/doris-demo" in nginx
        assert "location ^~ /api/v1/doris-demo/" in nginx
        assert "doris_public_service:5001" in nginx
        assert "--threads 6" in boot
        assert "%(U)s" in boot
        assert "%(q)s" not in boot
        assert "$uri" in nginx
        assert "$request_uri" not in nginx
