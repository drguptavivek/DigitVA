"""Every top-level Expo route must be served by /app/ on a hard load."""

import os
import re
import tempfile
import unittest
from pathlib import Path

from flask import Flask, send_file

from app.routes.expo_client import _SPA_ROUTE_ROOTS, expo_client

_APP_DIR = Path(__file__).resolve().parent.parent / "mobile" / "digitva-collect" / "app"


class ExpoClientRouteTests(unittest.TestCase):
    def test_fixed_mtime_equal_size_release_entries_never_return_stale_304(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = Flask(__name__)
            app.config["EXPO_CLIENT_DIST"] = directory
            app.register_blueprint(expo_client)
            client = app.test_client()
            for filename in ("index.html", "asset-worker.js", "asset-manifest.json",
                             "cache-register.js", "assets/logo.png"):
                path = root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"release-one")
                os.utime(path, (1767225600, 1767225600))
                # A browser may still send validators from the previous hosting behavior.
                with app.test_request_context():
                    legacy = send_file(path)
                    validators = {
                        "If-None-Match": legacy.headers["ETag"],
                        "If-Modified-Since": legacy.headers["Last-Modified"],
                    }
                    legacy.close()
                path.write_bytes(b"release-two")
                os.utime(path, (1767225600, 1767225600))
                with app.test_request_context():
                    unchanged_validator = send_file(path)
                    self.assertEqual(unchanged_validator.headers["ETag"], validators["If-None-Match"])
                    unchanged_validator.close()
                routes = [f"/app/{filename}"]
                if filename == "index.html":
                    routes.extend(["/app/", "/app/workspace"])
                for route in routes:
                    for headers in (validators, {"If-None-Match": validators["If-None-Match"]},
                                    {"If-Modified-Since": validators["If-Modified-Since"]}):
                        with self.subTest(route=route, headers=headers):
                            response = client.get(route, headers=headers)
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(response.data, b"release-two")
                            self.assertNotIn("ETag", response.headers)
                            self.assertNotIn("Last-Modified", response.headers)
                            response.close()

    def test_release_entries_revalidate_and_only_hashed_assets_are_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "index.html", "asset-worker.js", "asset-manifest.json", "cache-register.js",
                "_expo/static/js/web/entry-" + "a" * 32 + ".js", "assets/logo.png",
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test", encoding="utf-8")
            app = Flask(__name__)
            app.config["EXPO_CLIENT_DIST"] = directory
            app.register_blueprint(expo_client)
            client = app.test_client()
            for route in ("/app/", "/app/workspace", "/app/index.html", "/app/asset-worker.js",
                          "/app/asset-manifest.json", "/app/cache-register.js", "/app/assets/logo.png"):
                with self.subTest(route=route):
                    response = client.get(route)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["Cache-Control"], "no-cache")
                    response.close()
            response = client.get("/app/_expo/static/js/web/entry-" + "a" * 32 + ".js")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "public, max-age=31536000, immutable")
            etag = response.headers["ETag"]
            response.close()
            cached = client.get("/app/_expo/static/js/web/entry-" + "a" * 32 + ".js",
                                headers={"If-None-Match": etag})
            self.assertEqual(cached.status_code, 304)
            cached.close()
            self.assertEqual(client.get("/app/assets/missing.js").status_code, 404)

    def test_every_expo_route_file_is_in_the_spa_allowlist(self):
        routes = {
            re.sub(r"\.(web|native)$", "", path.stem)
            for path in _APP_DIR.glob("*.tsx")
            if not path.stem.startswith("_") and path.stem != "index"
        }
        self.assertIn("supervision", routes)  # the directory was actually read
        missing = sorted(routes - _SPA_ROUTE_ROOTS)
        self.assertEqual(missing, [], f"/app/ would 404 on reload for: {missing}")


if __name__ == "__main__":
    unittest.main()
