"""UI string corrections over HTTP: the public read, the admin page and its JSON calls."""
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

from app.routes.api import ui_strings as api_module
from app.services import ui_string_service as svc
from tests.base import BaseTestCase
from tests.ui_string_fixtures import EN, FORM_EN, FORM_HI, HI, write_export

PUBLIC = "/api/v1/ui-strings/{}"
LIST = "/api/v1/ui-strings"
LANGUAGE_API = "/admin/api/ui-languages/{}"
PANEL = "/admin/panels/ui-strings"
API = "/admin/api/ui-strings/{}/{}"


class UiStringRouteTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self._old_dist = self.app.config.get("EXPO_CLIENT_DIST")
        self._tempdir = tempfile.TemporaryDirectory()
        self.app.config["EXPO_CLIENT_DIST"] = self._tempdir.name
        write_export(
            Path(self._tempdir.name),
            {"en": EN, "hi": HI, "form-en": FORM_EN, "form-hi": FORM_HI},
        )
        svc._pack_cache.clear()
        self._publish("hi", "हिन्दी", "hi-IN")

    def tearDown(self):
        if self._old_dist is None:
            self.app.config.pop("EXPO_CLIENT_DIST", None)
        else:
            self.app.config["EXPO_CLIENT_DIST"] = self._old_dist
        self._tempdir.cleanup()
        super().tearDown()

    def _publish(self, locale, name, tag, direction="ltr", published=True):
        from app import db

        svc.set_ui_language(locale, name, tag, direction, published, self.base_admin_user.user_id)
        db.session.commit()

    def _set(self, key, text, locale="hi"):
        from app import db

        self._login(self.base_admin_id)
        response = self.client.put(
            API.format(locale, key), json={"text": text}, headers=self._csrf_headers()
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        db.session.commit()
        return response

    # -- public read -------------------------------------------------------

    def test_public_read_needs_no_login_and_returns_the_full_pack(self):
        response = self.app.test_client().get(PUBLIC.format("hi"))  # no session cookie
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            set(payload),
            {"version", "locale", "native_name", "bcp47_tag", "direction", "reviewed", "strings", "form"},
        )
        self.assertEqual(payload["strings"], HI)  # the bundled text, not only corrections
        self.assertEqual(payload["form"], FORM_HI)
        self.assertEqual((payload["bcp47_tag"], payload["direction"]), ("hi-IN", "ltr"))
        self.assertEqual(payload["reviewed"], 0.0)

    def test_public_read_lays_a_correction_over_the_bundle(self):
        self._set("navCoding", "कोडिंग (सुधार)")
        self._set("form:next", "अगला")
        payload = self.app.test_client().get(PUBLIC.format("hi")).get_json()
        self.assertEqual(payload["strings"]["navCoding"], "कोडिंग (सुधार)")
        self.assertEqual(payload["strings"]["loginTitle"], HI["loginTitle"])
        self.assertEqual(payload["form"], {"next": "अगला"})
        self.assertEqual(payload["reviewed"], round(2 / (len(EN) + len(FORM_EN)), 3))

    def test_machine_drafts_are_never_served(self):
        from app import db
        from app.models.mas_ui_string_override import MasUiStringOverride

        db.session.add(MasUiStringOverride(
            locale_code="hi", string_key="loginHelp", text="मशीन", source=svc.SOURCE_MACHINE,
        ))
        db.session.commit()
        payload = self.client.get(PUBLIC.format("hi")).get_json()
        self.assertIn("loginTitle", payload["strings"])
        self.assertNotIn("loginHelp", payload["strings"])

    def test_a_language_with_no_bundle_serves_accepted_rows_alone(self):
        self._set("navCoding", "ਕੋਡਿੰਗ", locale="pa")  # pa is on the machine list: editable
        self._publish("pa", "ਪੰਜਾਬੀ", "pa-IN")
        payload = self.client.get(PUBLIC.format("pa")).get_json()
        self.assertEqual(payload["strings"], {"navCoding": "ਕੋਡਿੰਗ"})
        self.assertEqual(payload["form"], {})

    def test_an_unpublished_language_is_not_found_and_not_listed(self):
        self._publish("pa", "ਪੰਜਾਬੀ", "pa-IN", published=False)
        self._set("navCoding", "ਕੋਡਿੰਗ", locale="pa")  # editable before publishing...
        self.assertEqual(self.client.get(PUBLIC.format("pa")).status_code, 404)  # ...never served
        codes = [lang["locale"] for lang in self.client.get(LIST).get_json()["languages"]]
        self.assertIn("hi", codes)
        self.assertNotIn("pa", codes)

    def test_list_names_each_published_language(self):
        write_export(Path(self._tempdir.name), {"ur": {"navCoding": "کوڈنگ"}})
        self._publish("ur", "اردو", "ur-IN", direction="rtl")
        response = self.app.test_client().get(LIST)
        self.assertEqual(response.status_code, 200)
        languages = {lang["locale"]: lang for lang in response.get_json()["languages"]}
        self.assertEqual(set(languages), {"hi", "ur"})
        self.assertEqual(languages["ur"]["direction"], "rtl")
        self.assertEqual(languages["ur"]["native_name"], "اردو")
        self.assertEqual(
            languages["hi"]["version"], self.client.get(PUBLIC.format("hi")).get_json()["version"]
        )
        again = self.client.get(LIST, headers={"If-None-Match": response.headers["ETag"]})
        self.assertEqual(again.status_code, 304)

    def test_en_and_unknown_locales_are_not_found(self):
        for locale in ("en", "xx"):
            with self.subTest(locale=locale):
                response = self.client.get(PUBLIC.format(locale))
                self.assertEqual(response.status_code, 404)

    def test_etag_is_the_version_and_a_match_gets_304(self):
        first = self.client.get(PUBLIC.format("hi"))
        etag = first.headers["ETag"]
        self.assertEqual(etag.strip('"'), first.get_json()["version"])
        # The app's If-None-Match check accepts only a quoted SHA-256 (src/api.ts requestRaw).
        self.assertRegex(etag, r'^"[0-9a-f]{64}"$')
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

    # -- the built pack is cached (digitva-s028 review) ---------------------

    def _counting(self):
        return (
            mock.patch.object(svc, "_read_bundle", wraps=svc._read_bundle),
            mock.patch.object(svc, "_corrections", wraps=svc._corrections),
        )

    def test_a_repeat_or_revalidating_read_does_not_rebuild_the_pack(self):
        first = self.client.get(PUBLIC.format("hi"))
        self.assertEqual(first.status_code, 200)
        self.client.get(LIST)
        read_patch, corrections_patch = self._counting()
        jsonify_patch = mock.patch.object(api_module, "jsonify", wraps=api_module.jsonify)
        with read_patch as reads, corrections_patch as corrections, jsonify_patch as serialised:
            again = self.client.get(PUBLIC.format("hi"))
            revalidated = self.client.get(PUBLIC.format("hi"), headers={"If-None-Match": first.headers["ETag"]})
            listed = self.client.get(LIST)
        self.assertEqual((again.status_code, revalidated.status_code, listed.status_code), (200, 304, 200))
        self.assertEqual(again.get_json(), first.get_json())
        self.assertEqual(reads.call_count, 0)
        self.assertEqual(corrections.call_count, 0)
        self.assertEqual(serialised.call_count, 2)  # the two 200s; the 304 serialises nothing
        self.assertEqual(revalidated.headers["ETag"], first.headers["ETag"])
        self.assertIn("public", revalidated.headers["Cache-Control"])

    def _bump(self, name):
        path = Path(self._tempdir.name) / "ui-strings" / name
        if not path.exists():
            path.write_text("{}", encoding="utf-8")
        stat = path.stat()
        # Two writes inside one tick can share an mtime: move it on explicitly.
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

    def test_a_file_a_correction_or_a_rename_invalidates_the_cached_pack(self):
        etag = self.client.get(PUBLIC.format("hi")).headers["ETag"]
        write_export(Path(self._tempdir.name), {"form-hi": {"next": "अगला"}})
        self._bump("form-hi.json")
        fresh = self.client.get(PUBLIC.format("hi"), headers={"If-None-Match": etag})
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(fresh.get_json()["form"], {"next": "अगला"})

        etag = fresh.headers["ETag"]
        write_export(Path(self._tempdir.name), {"theme-en": {"passwordShow": "Show password"},
                                                "theme-hi": {"passwordShow": "पासवर्ड दिखाएँ"}})
        self._bump("theme-hi.json")
        fresh = self.client.get(PUBLIC.format("hi"), headers={"If-None-Match": etag})
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(fresh.get_json()["strings"]["passwordShow"], "पासवर्ड दिखाएँ")

        etag = fresh.headers["ETag"]
        self._set("loginTitle", "साइन इन")
        fresh = self.client.get(PUBLIC.format("hi"), headers={"If-None-Match": etag})
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(fresh.get_json()["strings"]["loginTitle"], "साइन इन")

        etag = fresh.headers["ETag"]
        self._publish("hi", "हिंदी", "hi-IN")
        fresh = self.client.get(PUBLIC.format("hi"), headers={"If-None-Match": etag})
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(fresh.get_json()["native_name"], "हिंदी")

    # -- an export fault is a 503, never a short list ------------------------

    def test_an_unreadable_reference_is_503_on_the_list_and_the_pack(self):
        path = Path(self._tempdir.name) / "ui-strings" / "en.json"
        path.write_bytes(b'{"navCoding": "\xa3"}')
        self._bump("en.json")
        with self.assertLogs("app.services.ui_string_service", "WARNING"):
            listed = self.client.get(LIST)
        self.assertEqual(listed.status_code, 503)
        self.assertEqual(listed.get_json()["code"], "unavailable")
        self.assertEqual(self.client.get(PUBLIC.format("hi")).status_code, 503)
        self.assertEqual(self.client.get(PUBLIC.format("xx")).status_code, 404)  # still not found

    def test_a_missing_export_folder_is_503_not_an_empty_list(self):
        self.assertEqual(self.client.get(LIST).status_code, 200)
        self.app.config["EXPO_CLIENT_DIST"] = str(Path(self._tempdir.name) / "absent")
        listed = self.client.get(LIST)
        self.assertEqual(listed.status_code, 503)
        self.assertNotIn("languages", listed.get_json())


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

    def test_language_put_is_admin_only_csrf_checked_and_validated(self):
        body = {"native_name": "ਪੰਜਾਬੀ", "bcp47_tag": "pa-IN", "direction": "ltr", "published": True}
        self._login(self.base_coder_id)
        refused = self.client.put(LANGUAGE_API.format("pa"), json=body, headers=self._csrf_headers())
        self.assertEqual(refused.status_code, 403)

        self._login(self.base_admin_id)
        no_token = self.client.put(LANGUAGE_API.format("pa"), json=body)
        self.assertEqual(no_token.status_code, 400)
        headers = self._csrf_headers()
        for bad in (
            {**body, "direction": "up"},
            {**body, "bcp47_tag": "en-IN"},
            {**body, "native_name": "<b>x</b>"},
            {**body, "published": "yes"},
        ):
            with self.subTest(bad=bad):
                self.assertEqual(
                    self.client.put(LANGUAGE_API.format("pa"), json=bad, headers=headers).status_code, 400
                )
        self.assertEqual(self.client.put(LANGUAGE_API.format("en"), json=body, headers=headers).status_code, 400)
        self.assertEqual(self.client.put(LANGUAGE_API.format("PA1"), json=body, headers=headers).status_code, 400)
        self.assertEqual(self.client.get(PUBLIC.format("pa")).status_code, 404)

        # Nothing to serve yet: no pa bundle and no accepted row.
        empty = self.client.put(LANGUAGE_API.format("pa"), json=body, headers=headers)
        self.assertEqual(empty.status_code, 422)
        self.assertEqual(empty.get_json()["code"], "nothing_to_publish")
        self.assertEqual(self.client.get(PUBLIC.format("pa")).status_code, 404)

        self.client.put(API.format("pa", "navCoding"), json={"text": "ਕੋਡਿੰਗ"}, headers=headers)
        ok = self.client.put(LANGUAGE_API.format("pa"), json=body, headers=headers)
        self.assertEqual(ok.status_code, 200, ok.get_data(as_text=True))
        self.assertEqual(self.client.get(PUBLIC.format("pa")).status_code, 200)

    def test_an_edit_without_a_published_flag_keeps_the_state(self):
        self._login(self.base_admin_id)
        headers = self._csrf_headers()
        body = {"native_name": "हिन्दी", "bcp47_tag": "hi-IN", "direction": "ltr"}
        added = self.client.put(LANGUAGE_API.format("hi"), json=body, headers=headers)
        self.assertEqual(added.get_json()["published"], False)  # a new language starts unpublished
        self.client.put(LANGUAGE_API.format("hi"), json={**body, "published": True}, headers=headers)
        renamed = self.client.put(
            LANGUAGE_API.format("hi"), json={**body, "native_name": "हिंदी"}, headers=headers
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.get_json()["published"], True)
        self.assertEqual(self.client.get(PUBLIC.format("hi")).get_json()["native_name"], "हिंदी")
        unpublished = self.client.put(
            LANGUAGE_API.format("hi"), json={**body, "published": False}, headers=headers
        )
        self.assertEqual(unpublished.get_json()["published"], False)
        self.assertEqual(self.client.get(PUBLIC.format("hi")).status_code, 404)

    def test_the_add_form_sends_no_published_flag(self):
        self._login(self.base_admin_id)
        html = self.client.get(PANEL, query_string={"locale": "hi"}).get_data(as_text=True)
        start = html.index("if (target.id === 'uis-lang-save') {")
        save_block = html[start:html.index("} else {", start)]
        self.assertIn("direction:", save_block)
        self.assertNotIn("published:", save_block)

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

    def test_panel_lists_ui_languages_with_their_publish_button(self):
        from app import db

        write_export(Path(self._tempdir.name), {"ur": {"navCoding": "کوڈنگ"}})
        svc.set_ui_language("pa", "ਪੰਜਾਬੀ", "pa-IN", "ltr", False, self.base_admin_user.user_id)
        svc.set_ui_language("ur", "اردو", "ur-IN", "rtl", True, self.base_admin_user.user_id)
        db.session.commit()
        self._login(self.base_admin_id)
        html = self.client.get(PANEL, query_string={"locale": "hi"}).get_data(as_text=True)
        self.assertIn("<code>pa</code>", html)
        self.assertIn(">Publish</button>", html)
        self.assertIn(">Unpublish</button>", html)
        self.assertIn('data-lang="{&#34;', html)  # JSON in an escaped attribute
        self.assertIn('<option value="pa"', html)  # an added language is editable

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

    def test_panel_with_a_non_utf8_bundle_shows_an_error_not_a_500(self):
        # Staging 24 Oct: byte 0xa3 in a bundle raised UnicodeDecodeError.
        path = Path(self._tempdir.name) / "ui-strings" / "hi.json"
        path.write_bytes(b'{"navCoding": "\xa3"}')
        self._login(self.base_admin_id)
        with self.assertLogs("app.services.ui_string_service", "WARNING"):
            response = self.client.get(PANEL, query_string={"locale": "hi"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("hi.json is not valid UTF-8 JSON", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
