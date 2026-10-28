"""Authentication and transport limits for the app telemetry API."""

import io
import uuid
from datetime import UTC, datetime
from unittest.mock import PropertyMock, patch

from flask import Request

from app import db
from app.models import AuthDevice, VaProjectMaster
from app.services import app_telemetry_service as telemetry
from app.services import device_auth_service as devices
from tests.base import BaseTestCase
from tests.authz.fixture import AuthzFixtureMixin


class AppTelemetryApiTests(AuthzFixtureMixin, BaseTestCase):
    def setUp(self):
        super().setUp()
        project = db.session.get(VaProjectMaster, "AZTA01")
        project.web_intake_mode = "both"
        self.device_secret = "telemetry-device-secret"
        self.device = AuthDevice(
            project_id="AZTA01",
            name="Telemetry phone",
            platform="android",
            secret_hash=devices.hash_token(self.device_secret),
        )
        db.session.add(self.device)
        db.session.flush()
        issued, _user = devices._open_authorized_session(self.device, self.users["interviewer_p1"])
        self.headers = {"Authorization": f"Bearer {issued.access_token}"}

    @staticmethod
    def _body(**changes):
        body = {
            "schema": 1,
            "batch_id": str(uuid.uuid4()),
            "day": datetime.now(UTC).date().isoformat(),
            "app_version": "0.3.10",
            "variant": "collect",
            "platform": "android",
            "device_type": "phone",
            "ram_bucket": "unknown",
            "core_bucket": "unknown",
            "manufacturer": "unknown",
            "metrics": {"foreground_ms": 0, "launches": 0, "crashes": 0, "errors": 0},
        }
        body.update(changes)
        return body

    def test_browser_post_is_refused_but_native_bearer_is_accepted(self):
        self._login(self.base_coder_id)
        browser = self.client.post(
            "/api/v1/analytics/app/batches", json=self._body(), headers=self._csrf_headers()
        )
        self.assertEqual((browser.status_code, browser.get_json()["code"]), (403, "device_session_required"))

        with patch.object(telemetry, "ingest", return_value=True) as ingest:
            native = self.client.post(
                "/api/v1/analytics/app/batches", json=self._body(), headers=self.headers
            )
        self.assertEqual(native.status_code, 200)
        self.assertEqual(native.get_json(), {"accepted": True, "duplicate": False})
        ingest.assert_called_once()

    def test_declared_oversize_body_is_refused_without_reading_stream(self):
        with patch.object(Request, "stream", new_callable=PropertyMock) as stream:
            with patch.object(telemetry, "ingest") as ingest:
                response = self.client.post(
                    "/api/v1/analytics/app/batches", data=b"x" * (telemetry.MAX_BODY_BYTES + 1),
                    content_type="application/json", headers=self.headers,
                )
        self.assertEqual((response.status_code, response.get_json()["code"]), (413, "payload_too_large"))
        stream.assert_not_called()
        ingest.assert_not_called()

    def test_unknown_length_oversize_body_is_bounded_before_service(self):
        class CountingStream(io.BytesIO):
            def __init__(self, body):
                super().__init__(body)
                self.read_sizes = []

            def read(self, size=-1):
                self.read_sizes.append(size)
                return super().read(size)

        stream = CountingStream(b"x" * (telemetry.MAX_BODY_BYTES + 2))
        with patch.object(telemetry, "ingest") as ingest:
            response = self.client.open(
                "/api/v1/analytics/app/batches", method="POST", input_stream=stream,
                content_type="application/json", headers=self.headers,
                environ_overrides={"CONTENT_LENGTH": "", "wsgi.input_terminated": True},
            )
        self.assertEqual((response.status_code, response.get_json()["code"]), (413, "payload_too_large"))
        self.assertEqual(stream.read_sizes, [telemetry.MAX_BODY_BYTES + 1])
        ingest.assert_not_called()

    def test_admin_report_is_aggregate_only_and_non_admin_is_refused(self):
        self._login(self.base_coder_id)
        refused = self.client.get("/api/v1/analytics/app/performance")
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (403, "forbidden"))

        self._login(self.base_admin_id)
        result = {"from": "2026-10-28", "to": "2026-10-28", "cells": [],
                  "summary": {"accepted_batches": 0, "foreground_ms": 0, "launches": 0,
                               "crashes": 0, "errors": 0}}
        with patch.object(telemetry, "report", return_value=result):
            response = self.client.get("/api/v1/analytics/app/performance")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), result)
