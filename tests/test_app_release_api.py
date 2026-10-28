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
        self.app.config["DIGITVA_PLUS_ANDROID_APK_TAG"] = ""

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
        self.assertEqual(body["variant"], "normal")
        self.assertEqual(body["size_bytes"], len(b"apk-bytes"))
        self.assertTrue(body["url"].startswith("http"))
        self.assertTrue(body["url"].endswith("/download/android"))
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=300")

    def test_server_version_validates_revision_and_never_caches(self):
        for revision, expected in (("", None), ("a" * 40, "a" * 40), ("A" * 40, None), ("a" * 39, None)):
            with self.subTest(revision=revision):
                self.app.config["DIGITVA_BUILD_REVISION"] = revision
                response = self.client.get("/api/v1/app/version")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"api_compatibility": 1, "build_revision": expected})
                self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_separate_variants_choose_numeric_newest_and_download_own_bytes(self):
        self._pin("digitva-collect-0.3.9-arm64-v8a.apk", b"old")
        normal = "digitva-collect-0.3.10-arm64-v8a.apk"
        plus = "digitva-collect-plus-0.3.10-arm64-v8a.apk"
        normal_sha = self._pin(normal, b"normal")
        self._pin("digitva-collect-plus-0.3.9-arm64-v8a.apk", b"old-plus")
        plus_sha = self._pin(plus, b"plus bytes")
        self.app.config["DIGITVA_PLUS_ANDROID_APK_TAG"] = "collect-plus-v0.3.10-plus.2"
        for variant, asset, data, digest, path, tag in (
            ("normal", normal, b"normal", normal_sha, "/download/android", "android-v0.3.10"),
            ("plus", plus, b"plus bytes", plus_sha, "/download/android/plus", "collect-plus-v0.3.10-plus.2"),
        ):
            with self.subTest(variant=variant):
                body = self.client.get(URL, query_string={"variant": variant}).get_json()
                self.assertEqual((body["asset"], body["version"], body["tag"]), (asset, "0.3.10", tag))
                self.assertEqual((body["variant"], body["size_bytes"], body["sha256"]), (variant, len(data), digest))
                self.assertTrue(body["url"].endswith(path))
                response = self.client.get(path)
                self.assertEqual(response.data, data)
                response.close()
        self.assertEqual(self.client.get(URL).get_json()["asset"], normal)
        page = self.client.get("/help/mobile-app").get_data(as_text=True)
        self.assertIn("DigitVA Collect 0.3.10", page)
        self.assertIn("DigitVA Collect Plus 0.3.10", page)
        self.assertIn("6 bytes", page)
        self.assertIn("10 bytes", page)

    def test_plus_tag_is_null_unless_configured_for_the_selected_version(self):
        plus = "digitva-collect-plus-0.3.10-arm64-v8a.apk"
        self._pin(plus)
        for tag in ("", "collect-plus-v0.3.9-plus.2", "collect-plus-v0.3.10-plus.0", "other"):
            with self.subTest(tag=tag):
                self.app.config["DIGITVA_PLUS_ANDROID_APK_TAG"] = tag
                body = self.client.get(URL, query_string={"variant": "plus"}).get_json()
                self.assertIsNone(body["tag"])
        self.app.config["DIGITVA_PLUS_ANDROID_APK_TAG"] = "collect-plus-v0.3.10-plus.2"
        body = self.client.get(URL, query_string={"variant": "plus"}).get_json()
        self.assertEqual(body["tag"], "collect-plus-v0.3.10-plus.2")

    def test_bad_variant_and_missing_variant(self):
        self._pin("digitva-collect-plus-0.3.1-arm64-v8a.apk")
        self.assertEqual(self.client.get(URL).get_json()["code"], "no_release")
        self.assertEqual(self.client.get("/download/android").status_code, 404)
        for value in ("", "other", "../plus"):
            self.assertEqual(self.client.get(URL, query_string={"variant": value}).status_code, 400)
        self.assertEqual(self.client.get("/download/android/../plus").status_code, 404)

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
