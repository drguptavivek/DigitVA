"""UI string corrections over HTTP: the public read, the admin page and its JSON calls."""
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

from app.services import ui_string_service as svc
from tests.base import BaseTestCase
from tests.ui_string_fixtures import EN, HI, write_export

PUBLIC = "/api/v1/ui-strings/{}"
PANEL = "/admin/panels/ui-strings"
API = "/admin/api/ui-strings/{}/{}"


class UiStringRouteTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self._old_dist = self.app.config.get("EXPO_CLIENT_DIST")
        self._tempdir = tempfile.TemporaryDirectory()
        self.app.config["EXPO_CLIENT_DIST"] = self._tempdir.name
        write_export(Path(self._tempdir.name), {"en": EN, "hi": HI})

    def tearDown(self):
        if self._old_dist is None:
            self.app.config.pop("EXPO_CLIENT_DIST", None)
        else:
            self.app.config["EXPO_CLIENT_DIST"] = self._old_dist
        self._tempdir.cleanup()
        super().tearDown()

    def _set(self, key, text):
        from app import db

        self._login(self.base_admin_id)
        response = self.client.put(
            API.format("hi", key), json={"text": text}, headers=self._csrf_headers()
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        db.session.commit()
        return response

    # -- public read -------------------------------------------------------

    def test_public_read_needs_no_login_and_returns_overrides_only(self):
        response = self.client.get(PUBLIC.format("hi"))
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(set(payload), {"version", "strings"})
        self.assertEqual(payload["strings"], {})

    def test_public_read_serves_a_set_correction(self):
        self._set("navCoding", "कोडिंग (सुधार)")
        anonymous = self.app.test_client()  # a fresh client: no session cookie
        payload = anonymous.get(PUBLIC.format("hi")).get_json()
        self.assertEqual(payload["strings"], {"navCoding": "कोडिंग (सुधार)"})

    def test_en_and_unknown_locales_are_not_found(self):
        for locale in ("en", "xx"):
            with self.subTest(locale=locale):
                response = self.client.get(PUBLIC.format(locale))
                self.assertEqual(response.status_code, 404)

    def test_etag_is_the_version_and_a_match_gets_304(self):
        first = self.client.get(PUBLIC.format("hi"))
        etag = first.headers["ETag"]
        self.assertEqual(etag.strip('"'), first.get_json()["version"])
        self.assertIn("public", first.headers["Cache-Control"])

        again = self.client.get(PUBLIC.format("hi"), headers={"If-None-Match": etag})
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.get_data(), b"")

    def test_a_new_correction_changes_the_etag(self):
        etag = self.client.get(PUBLIC.format("hi")).headers["ETag"]
        self._set("navCoding", "सुधार")
        stale = self.client.get(PUBLIC.format("hi"), headers={"If-None-Match": etag})
        self.assertEqual(stale.status_code, 200)
        self.assertNotEqual(stale.headers["ETag"], etag)


class UiStringAdminRouteTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self._old_dist = self.app.config.get("EXPO_CLIENT_DIST")
        self._tempdir = tempfile.TemporaryDirectory()
        self.app.config["EXPO_CLIENT_DIST"] = self._tempdir.name
        write_export(Path(self._tempdir.name), {"en": EN, "hi": HI})

    def tearDown(self):
        if self._old_dist is None:
            self.app.config.pop("EXPO_CLIENT_DIST", None)
        else:
            self.app.config["EXPO_CLIENT_DIST"] = self._old_dist
        self._tempdir.cleanup()
        super().tearDown()

    def test_a_non_admin_is_refused_on_every_admin_endpoint(self):
        self._login(self.base_coder_id)
        headers = self._csrf_headers()
        responses = [
            self.client.get(PANEL, query_string={"locale": "hi"}),
            self.client.get(API.format("hi", "export")),
            self.client.put(API.format("hi", "navCoding"), json={"text": "x"}, headers=headers),
            self.client.delete(API.format("hi", "navCoding"), headers=headers),
        ]
        for response in responses:
            with self.subTest(status=response.status_code):
                self.assertEqual(response.status_code, 403)

    def test_put_and_delete_require_the_csrf_token(self):
        self._login(self.base_admin_id)
        put = self.client.put(API.format("hi", "navCoding"), json={"text": "सुधार"})
        delete = self.client.delete(API.format("hi", "navCoding"))
        self.assertEqual(put.status_code, 400)
        self.assertIn("CSRF", put.get_json()["error"])
        self.assertEqual(delete.status_code, 400)
        self.assertIn("CSRF", delete.get_json()["error"])

    def test_put_then_delete_with_the_token(self):
        self._login(self.base_admin_id)
        headers = self._csrf_headers()
        put = self.client.put(API.format("hi", "navCoding"), json={"text": "सुधार"}, headers=headers)
        self.assertEqual(put.status_code, 200)
        self.assertEqual(put.get_json()["status"], svc.STATUS_CORRECTED)

        delete = self.client.delete(API.format("hi", "navCoding"), headers=headers)
        self.assertEqual(delete.status_code, 200)
        self.assertEqual(delete.get_json()["status"], svc.STATUS_BUNDLED)

    def test_put_refusals_map_to_400_and_422(self):
        self._login(self.base_admin_id)
        headers = self._csrf_headers()
        unknown = self.client.put(API.format("hi", "noSuchKey"), json={"text": "x"}, headers=headers)
        self.assertEqual(unknown.status_code, 400)
        markup = self.client.put(
            API.format("hi", "loginTitle"), json={"text": "<b>x</b>"}, headers=headers
        )
        self.assertEqual(markup.status_code, 422)
        self.assertEqual(markup.get_json()["code"], "invalid_translation")
        blank = self.client.put(API.format("hi", "loginTitle"), json={"text": "  "}, headers=headers)
        self.assertEqual(blank.status_code, 400)

    def test_export_applies_corrections_and_downloads(self):
        self._login(self.base_admin_id)
        self.client.put(
            API.format("hi", "navCoding"), json={"text": "सुधार"}, headers=self._csrf_headers()
        )
        response = self.client.get(API.format("hi", "export"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        self.assertIn('filename="hi.json"', response.headers["Content-Disposition"])
        self.assertEqual(response.get_json()["navCoding"], "सुधार")

    def test_panel_link_carries_only_the_english_text(self):
        self._login(self.base_admin_id)
        self.client.put(
            API.format("hi", "navCoding"),
            json={"text": "SECRET-CORRECTION-TEXT"},
            headers=self._csrf_headers(),
        )
        html = self.client.get(PANEL, query_string={"locale": "hi", "status": "all"}).get_data(
            as_text=True
        )
        self.assertIn("SECRET-CORRECTION-TEXT", html)  # shown in the table...
        hrefs = [unquote(h) for h in re.findall(r'href="(https://translate\.google\.com/[^"]*)"', html)]
        self.assertTrue(hrefs)
        navcoding = [h for h in hrefs if "text=Coding" in h]
        self.assertEqual(len(navcoding), 1)
        self.assertIn("sl=en&tl=hi&text=Coding&op=translate", navcoding[0].replace("&amp;", "&"))
        self.assertTrue(all("SECRET-CORRECTION-TEXT" not in h for h in hrefs))  # ...never in a link
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_panel_renders_the_admin_table(self):
        self._login(self.base_admin_id)
        response = self.client.get(PANEL, query_string={"locale": "hi", "status": "missing"})
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("<code>loginHelp</code>", html)  # the missing key is listed...
        self.assertNotIn("<code>navCoding</code>", html)  # ...a bundled one is filtered out

    def test_panel_with_no_export_shows_the_hint(self):
        self.app.config["EXPO_CLIENT_DIST"] = str(Path(self._tempdir.name) / "absent")
        self._login(self.base_admin_id)
        html = self.client.get(PANEL).get_data(as_text=True)
        self.assertIn("npm run export:web", html)


if __name__ == "__main__":
    unittest.main()
