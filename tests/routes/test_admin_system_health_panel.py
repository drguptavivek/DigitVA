"""The admin System health panel and the banner on the admin index.

Both read the certificate cache or the configured certificate file only; the
network checks are not configured in tests, so nothing dials out here.
"""

import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest import mock

from tests.base import BaseTestCase
from tests.services.test_tls_health_service import make_cert, pem


class _MemoryCache:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, timeout=None):
        self.values[key] = value


class AdminSystemHealthPanelTests(BaseTestCase):
    PANEL_URL = "/admin/panels/system-health"
    CN = "tls-health.test.invalid"

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cert_path = os.path.join(tmp.name, "server.crt")
        cert = make_cert(self.CN, datetime.now(UTC) + timedelta(days=90), sans=[self.CN])
        with open(cert_path, "wb") as fh:
            fh.write(pem(cert))
        config = mock.patch.dict(
            self.app.config, {"APP_TLS_CERT_FILE": cert_path, "PUBLIC_BASE_URL": ""}
        )
        config.start()
        self.addCleanup(config.stop)
        self.cache = _MemoryCache()
        cache = mock.patch("app.cache", self.cache)
        cache.start()
        self.addCleanup(cache.stop)

    def test_panel_shows_the_certificate_table_to_an_admin(self):
        self._login(str(self.base_admin_id))

        response = self.client.get(self.PANEL_URL)

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('id="tls-health-table"', body)
        self.assertIn(self.CN, body)
        self.assertIn("App HTTPS certificate", body)
        self.assertIn("not configured", body)

    def test_panel_shows_an_s3_credentials_error_row_without_an_expiry(self):
        s3_row = {
            "key": "s3_access",
            "label": "S3 bucket access",
            "source": "s3://example-bucket/staging/",
            "subject_cn": "",
            "sans": [],
            "not_after": None,
            "days_left": None,
            "status": "error",
            "detail": "credentials rejected",
        }
        self._login(str(self.base_admin_id))

        with mock.patch("app.services.tls_health_service._s3_rows", return_value=[s3_row]):
            response = self.client.get(self.PANEL_URL)

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('data-cert-key="s3_access"', body)
        self.assertIn("S3 bucket access", body)
        self.assertIn("credentials rejected", body)
        self.assertIn("s3://example-bucket/staging/", body)

    def test_panel_refreshes_the_cached_report(self):
        self._login(str(self.base_admin_id))

        self.client.get(self.PANEL_URL)

        self.assertIn("tls_health:last", self.cache.values)

    def test_panel_is_refused_to_a_non_admin(self):
        self._login(str(self.base_coder_id))

        response = self.client.get(self.PANEL_URL)

        self.assertIn(response.status_code, (302, 403))
        self.assertNotIn(self.CN, response.get_data(as_text=True))

    def test_banner_is_shown_on_the_admin_index_from_the_cache(self):
        self.cache.values["tls_health:last"] = [
            {
                "key": "public_https",
                "label": "Public HTTPS certificate",
                "source": "h:443",
                "subject_cn": "",
                "sans": [],
                "not_after": None,
                "days_left": 5,
                "status": "urgent",
                "detail": "",
            }
        ]
        self._login(str(self.base_admin_id))

        body = self.client.get("/admin/").get_data(as_text=True)

        self.assertIn('id="tls-expiry-banner"', body)
        self.assertIn("Public HTTPS certificate", body)
        self.assertIn("5 days left", body)

    def test_banner_is_absent_without_a_cached_report(self):
        self._login(str(self.base_admin_id))

        body = self.client.get("/admin/").get_data(as_text=True)

        self.assertIn('data-panel="/admin/panels/sync"', body)
        self.assertNotIn('id="tls-expiry-banner"', body)
