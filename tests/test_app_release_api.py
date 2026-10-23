"""GET /api/v1/app/android/latest (digitva-2vrs). Policy: docs/policy/expo-client.md."""
import hashlib
import os
import tempfile

from app import limiter
from tests.base import BaseTestCase

URL = "/api/v1/app/android/latest"
ASSET = "digitva-collect-0.3.1-arm64-v8a.apk"


class AppReleaseApiTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        limiter.reset()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.app.config["DIGITVA_ANDROID_APK_DIR"] = self.dir.name

    def _pin(self, name=ASSET, data=b"apk-bytes"):
        with open(os.path.join(self.dir.name, name), "wb") as fh:
            fh.write(data)
        return hashlib.sha256(data).hexdigest()

    def test_payload_from_the_hosted_asset_without_auth(self):
        sha = self._pin()
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["version"], "0.3.1")
        self.assertEqual(body["version_code"], 301)
        self.assertEqual(body["tag"], "android-v0.3.1")
        self.assertEqual(body["asset"], ASSET)
        self.assertEqual(body["sha256"], sha)
        self.assertTrue(body["url"].startswith("http"))
        self.assertTrue(body["url"].endswith("/download/android"))
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=300")

    def test_404_no_release_when_nothing_is_pinned(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["code"], "no_release")

    def test_404_for_an_unrecognised_asset_name(self):
        self._pin("other.apk")
        self.assertEqual(self.client.get(URL).get_json()["code"], "no_release")

    def test_rate_limited(self):
        self._pin()
        codes = [self.client.get(URL).status_code for _ in range(31)]
        self.assertEqual(codes[:30], [200] * 30)
        self.assertEqual(codes[30], 429)
