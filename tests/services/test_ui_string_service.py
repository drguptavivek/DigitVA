"""The UI string corrections service: checks, versions, audit and the loader."""
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from app import db
from app.services import ui_string_service as svc
from tests.base import BaseTestCase
from tests.ui_string_fixtures import EN, FORM_EN, FORM_HI, HI, write_export


class UiStringServiceTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self._old_dist = self.app.config.get("EXPO_CLIENT_DIST")
        self._tempdir = tempfile.TemporaryDirectory()
        self.root = self._tempdir.name
        self.app.config["EXPO_CLIENT_DIST"] = self.root
        write_export(Path(self.root), {"en": EN, "hi": HI})
        svc._pack_cache.clear()
        self.actor = self.base_admin_user.user_id

    def tearDown(self):
        if self._old_dist is None:
            self.app.config.pop("EXPO_CLIENT_DIST", None)
        else:
            self.app.config["EXPO_CLIENT_DIST"] = self._old_dist
        self._tempdir.cleanup()
        db.session.rollback()
        super().tearDown()

    # -- locales and the loader ------------------------------------------

    def test_locales_lists_shipped_files_except_en(self):
        self.assertEqual(svc.locales(), ["hi"])

    def test_macos_metadata_files_are_not_locales(self):
        # A macOS-built tarball carries AppleDouble "._hi.json" files (binary, not JSON).
        folder = Path(self.root) / "ui-strings"
        (folder / "._hi.json").write_bytes(b"\x00\x05\x16\x07\xa3 not json")
        (folder / "._en.json").write_bytes(b"\x00\x05\x16\x07\xa3 not json")
        self.assertEqual(svc.locales(), ["hi"])
        self.assertNotIn("._hi", svc.reviewable_locales())
        self.assertEqual(svc._bundle("hi")["navCoding"], "कोडिंग")

    def test_no_export_means_no_locales(self):
        self.app.config["EXPO_CLIENT_DIST"] = os.path.join(self.root, "absent")
        self.assertEqual(svc.locales(), [])

    def test_loader_picks_up_a_rebuilt_file(self):
        self.assertEqual(svc.overrides("hi")["strings"], {})
        self.assertEqual(svc._bundle("hi")["navCoding"], "कोडिंग")

        path = Path(self.root) / "ui-strings" / "hi.json"
        path.write_text('{"navCoding": "नया"}', encoding="utf-8")
        # Force a different mtime: two writes inside one tick can share it.
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

        self.assertEqual(svc._bundle("hi"), {"navCoding": "नया"})

    def test_unreadable_bundle_is_reported_and_left_as_it_is(self):
        path = Path(self.root) / "ui-strings" / "hi.json"
        raw = b'{"navCoding": "\xa3"}'
        path.write_bytes(raw)
        with self.assertLogs(svc.log, "WARNING") as logs:
            with self.assertRaisesRegex(svc.UiStringError, "hi.json"):
                svc._bundle("hi")
        self.assertIn(str(path), logs.output[0])
        self.assertEqual(path.read_bytes(), raw)  # never rewritten
        self.assertNotIn(str(path), svc._bundle_cache)  # a fixed file is read next time

    # -- set: refusals -----------------------------------------------------

    def test_set_refuses_unknown_key(self):
        with self.assertRaises(svc.UiStringError):
            svc.set_override("hi", "noSuchKey", "कुछ", self.actor)

    def test_set_refuses_empty_and_whitespace(self):
        for text in ("", "   ", None):
            with self.subTest(text=text), self.assertRaises(svc.UiStringError):
                svc.set_override("hi", "loginTitle", text, self.actor)

    def test_set_refuses_text_over_the_cap(self):
        from app.services.instrument_translation_service import MAX_TRANSLATION_TEXT_CHARS

        with self.assertRaises(svc.UiStringError):
            svc.set_override("hi", "loginTitle", "क" * (MAX_TRANSLATION_TEXT_CHARS + 1), self.actor)

    def test_set_accepts_text_at_the_cap(self):
        from app.services.instrument_translation_service import MAX_TRANSLATION_TEXT_CHARS

        result = svc.set_override("hi", "loginTitle", "क" * MAX_TRANSLATION_TEXT_CHARS, self.actor)
        self.assertEqual(len(result["text"]), MAX_TRANSLATION_TEXT_CHARS)

    def test_set_refuses_a_missing_placeholder(self):
        with self.assertRaises(svc.InvalidUiStringText):
            svc.set_override("hi", "syncResult", "भेजे गए। {sent}", self.actor)

    def test_set_refuses_an_extra_placeholder(self):
        with self.assertRaises(svc.InvalidUiStringText):
            svc.set_override("hi", "loginTitle", "DigitVA {name}", self.actor)

    def test_set_refuses_markup_the_english_lacks(self):
        with self.assertRaises(svc.InvalidUiStringText):
            svc.set_override("hi", "loginTitle", "<b>DigitVA</b>", self.actor)

    def test_set_refuses_en_unknown_and_path_like_locales(self):
        for locale in ("en", "xx", "../en"):
            with self.subTest(locale=locale), self.assertRaises(svc.UiStringError):
                svc.set_override(locale, "loginTitle", "x", self.actor)

    def test_refused_locales_and_keys_leave_no_row(self):
        with self.assertRaises(svc.UiStringError):
            svc.set_override("hi", "noSuchKey", "कुछ", self.actor)
        self.assertEqual(svc.overrides("hi")["strings"], {})

    # -- set, read, revert, versions, audit --------------------------------

    def test_set_then_overrides_returns_the_text(self):
        svc.set_override("hi", "navCoding", "कोडिंग (सुधार)", self.actor)
        payload = svc.overrides("hi")
        self.assertEqual(payload["strings"], {"navCoding": "कोडिंग (सुधार)"})
        self.assertIsInstance(payload["version"], str)

    def test_version_moves_on_set_and_on_revert(self):
        v0 = svc.overrides("hi")["version"]
        svc.set_override("hi", "navCoding", "पहला", self.actor)
        v1 = svc.overrides("hi")["version"]
        self.assertNotEqual(v0, v1)

        svc.set_override("hi", "navCoding", "दूसरा", self.actor)
        v2 = svc.overrides("hi")["version"]
        self.assertNotEqual(v1, v2)

        svc.revert("hi", "navCoding", self.actor)
        self.assertNotEqual(v2, svc.overrides("hi")["version"])

    def test_revert_of_an_older_row_still_moves_the_version(self):
        svc.set_override("hi", "navCoding", "पहला", self.actor)
        svc.set_override("hi", "loginTitle", "दूसरा", self.actor)
        before = svc.overrides("hi")["version"]
        svc.revert("hi", "navCoding", self.actor)
        self.assertNotEqual(before, svc.overrides("hi")["version"])

    def test_revert_restores_the_bundled_text(self):
        svc.set_override("hi", "navCoding", "बदला", self.actor)
        result = svc.revert("hi", "navCoding", self.actor)
        self.assertEqual(result["status"], svc.STATUS_BUNDLED)
        self.assertEqual(svc.overrides("hi")["strings"], {})

    def test_set_and_revert_write_an_audit_line(self):
        with self.assertLogs("app.services.ui_string_service", level="INFO") as logs:
            svc.set_override("hi", "navCoding", "सुधार", self.actor)
            svc.revert("hi", "navCoding", self.actor)
        self.assertTrue(any("ui string corrected" in line for line in logs.output))
        self.assertTrue(any("ui string reverted" in line for line in logs.output))

    # -- admin listing -----------------------------------------------------

    def test_strings_for_admin_marks_each_status(self):
        svc.set_override("hi", "navCoding", "सुधार", self.actor)
        data = svc.strings_for_admin("hi")
        by_key = {row["key"]: row for row in data["rows"]}
        self.assertEqual(by_key["navCoding"]["status"], svc.STATUS_CORRECTED)
        self.assertEqual(by_key["navCoding"]["corrected"], "सुधार")
        self.assertEqual(by_key["loginTitle"]["status"], svc.STATUS_BUNDLED)
        self.assertEqual(by_key["loginHelp"]["status"], svc.STATUS_MISSING)
        self.assertEqual(data["counts"], {"all": 4, "corrected": 1, "missing": 1, "machine": 0})

    def test_strings_for_admin_filters_and_pages(self):
        self.assertEqual(
            {r["key"] for r in svc.strings_for_admin("hi", "missing")["rows"]},
            {"loginHelp"},
        )
        self.assertEqual(svc.strings_for_admin("hi", "corrected")["total"], 0)
        paged = svc.strings_for_admin("hi", "all", page=2, page_size=3)
        self.assertEqual(len(paged["rows"]), 1)

    def test_strings_for_admin_refuses_a_bad_filter_and_en(self):
        with self.assertRaises(svc.UiStringError):
            svc.strings_for_admin("hi", "bundled")
        with self.assertRaises(svc.UiStringError):
            svc.strings_for_admin("en")

    # -- export ------------------------------------------------------------

    def test_export_applies_corrections_over_the_bundle(self):
        svc.set_override("hi", "navCoding", "सुधार", self.actor)
        exported = svc.export("hi")
        self.assertEqual(exported["navCoding"], "सुधार")
        self.assertEqual(exported["loginTitle"], HI["loginTitle"])
        self.assertEqual(list(exported), list(HI))


    # -- namespaces (digitva-s028) ---------------------------------------

    def _with_side_files(self):
        write_export(Path(self.root), {
            "theme-en": {"passwordShow": "Show password"},
            "theme-hi": {"passwordShow": "पासवर्ड दिखाएँ"},
            "form-en": FORM_EN,
            "form-hi": FORM_HI,
        })

    def test_bundle_merges_theme_strings_and_prefixes_form_labels(self):
        self._with_side_files()
        english = svc._bundle("en")
        self.assertEqual(english["passwordShow"], "Show password")
        self.assertEqual(english["form:next"], "Next")
        self.assertEqual(svc._bundle("hi")["form:next"], "आगे")
        self.assertEqual(svc.locales(), ["hi"])  # side files are not locales

    def test_form_label_corrections_keep_the_english_placeholders(self):
        self._with_side_files()
        with self.assertRaises(svc.InvalidUiStringText):
            svc.set_override("hi", "form:required", "आवश्यक है", self.actor)
        svc.set_override("hi", "form:required", "{label} आवश्यक है", self.actor)
        self.assertEqual(svc.overrides("hi")["strings"], {"form:required": "{label} आवश्यक है"})

    def test_export_leaves_the_form_labels_out(self):
        self._with_side_files()
        svc.set_override("hi", "form:next", "अगला", self.actor)
        self.assertNotIn("form:next", svc.export("hi"))
        self.assertIn("passwordShow", svc.export("hi"))

    def test_an_added_language_is_editable_before_it_is_published(self):
        with self.assertRaises(svc.UiStringError):
            svc.set_override("ur", "navCoding", "کوڈنگ", self.actor)
        svc.set_ui_language("ur", "اردو", "ur-IN", "rtl", False, self.actor)
        svc.set_override("ur", "navCoding", "کوڈنگ", self.actor)
        self.assertIn("ur", svc.reviewable_locales())
        with self.assertRaises(svc.UiStringError):
            svc.pack("ur")

    def test_pack_version_moves_with_a_rebuilt_bundle(self):
        svc.set_ui_language("hi", "हिन्दी", "hi-IN", "ltr", True, self.actor)
        before = svc.pack("hi")["version"]
        write_export(Path(self.root), {"hi": {**HI, "loginHelp": "नया"}})
        path = Path(self.root) / "ui-strings" / "hi.json"
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        self.assertNotEqual(svc.pack("hi")["version"], before)

    # -- publishing (digitva-s028 review) --------------------------------

    def test_no_published_flag_keeps_the_state_and_a_new_language_starts_unpublished(self):
        self.assertFalse(svc.set_ui_language("hi", "हिन्दी", "hi-IN", "ltr", None, self.actor)["published"])
        svc.set_ui_language("hi", "हिन्दी", "hi-IN", "ltr", True, self.actor)
        kept = svc.set_ui_language("hi", "हिंदी", "hi-IN", "ltr", None, self.actor)
        self.assertTrue(kept["published"])
        self.assertEqual(svc.pack("hi")["native_name"], "हिंदी")

    def test_publishing_needs_a_bundle_or_an_accepted_row(self):
        svc.set_ui_language("pa", "ਪੰਜਾਬੀ", "pa-IN", "ltr", False, self.actor)  # adding is fine
        db.session.add(svc.MasUiStringOverride(
            locale_code="pa", string_key="navCoding", text="ਮਸ਼ੀਨ", source=svc.SOURCE_MACHINE,
        ))
        db.session.flush()
        with self.assertRaises(svc.NothingToPublish):  # a machine draft is not enough
            svc.set_ui_language("pa", "ਪੰਜਾਬੀ", "pa-IN", "ltr", True, self.actor)
        svc.accept("pa", "navCoding", self.actor)
        self.assertTrue(svc.set_ui_language("pa", "ਪੰਜਾਬੀ", "pa-IN", "ltr", True, self.actor)["published"])
        self.assertTrue(svc.set_ui_language("hi", "हिन्दी", "hi-IN", "ltr", True, self.actor)["published"])

    def test_published_languages_raises_instead_of_dropping_an_unreadable_pack(self):
        svc.set_ui_language("hi", "हिन्दी", "hi-IN", "ltr", True, self.actor)
        self.assertEqual([lang["locale"] for lang in svc.published_languages()], ["hi"])
        path = Path(self.root) / "ui-strings" / "hi.json"
        path.write_bytes(b'{"navCoding": "\xa3"}')
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        with self.assertLogs(svc.log, "WARNING"), self.assertRaises(svc.UiStringError):
            svc.published_languages()

    def test_published_languages_reads_versions_in_one_query(self):
        svc.set_ui_language("hi", "हिन्दी", "hi-IN", "ltr", True, self.actor)
        svc.set_override("pa", "navCoding", "ਕੋਡਿੰਗ", self.actor)
        svc.set_ui_language("pa", "ਪੰਜਾਬੀ", "pa-IN", "ltr", True, self.actor)
        with unittest.mock.patch.object(svc, "_versions", wraps=svc._versions) as versions:
            listed = svc.published_languages()
        self.assertEqual([lang["locale"] for lang in listed], ["hi", "pa"])
        self.assertEqual(versions.call_count, 1)
        self.assertEqual(listed[1]["version"], svc.pack("pa")["version"])


if __name__ == "__main__":
    unittest.main()
