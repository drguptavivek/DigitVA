"""Serving and administering instrument translations over HTTP.

The serving endpoint is the one delivery contract every frontend reads
(docs/policy/va-web-form-options.md): a signed-in client fetches a locale,
caches it by version and revalidates with ``If-None-Match``. The admin routes
behind ``/admin/api/instrument-translations/`` are admin-only and are how a
language is imported, activated and corrected.
"""
from datetime import UTC, datetime

from app import db
from app.models.mas_instrument_locales import (
    MapInstrumentTranslations,
    MasInstrumentLocales,
)
from app.services import instrument_translation_service as svc
from tests.base import BaseTestCase

INSTRUMENT = "WHO_2022_VA"


def _locale(code, *, active, version=1, name="Hindi"):
    row = db.session.get(MasInstrumentLocales, (INSTRUMENT, code))
    if row is None:
        row = MasInstrumentLocales(
            instrument_code=INSTRUMENT, locale_code=code, language_name=name,
            version=version, is_active=active, updated_at=datetime.now(UTC),
        )
        db.session.add(row)
    row.is_active = active
    row.version = version
    db.session.flush()
    return row


def _string(code, item_key, text, *, field="label", kind="question"):
    row = MapInstrumentTranslations(
        instrument_code=INSTRUMENT, locale_code=code, item_kind=kind,
        item_key=item_key, field=field, text=text, source="imported",
        updated_at=datetime.now(UTC),
    )
    db.session.add(row)
    db.session.flush()
    return row


class InstrumentTranslationServingTests(BaseTestCase):
    """GET /api/v1/instruments/<code>/translations/<locale>."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A real reference item, so the fixture cannot drift from the form.
        cls.item_key = sorted(
            key[1] for key in svc.reference_label_keys(INSTRUMENT)
        )[0]

    def setUp(self):
        super().setUp()
        _locale("hi", active=True, version=4)
        _string("hi", self.item_key, "पहला प्रश्न")
        _string("hi", "yes_no/yes", "हाँ", kind="choice")
        _locale("kn", active=False, version=2, name="Kannada")
        _string("kn", self.item_key, "ಮೊದಲ ಪ್ರಶ್ನೆ")
        db.session.commit()

    def _url(self, locale, code=INSTRUMENT):
        return f"/api/v1/instruments/{code}/translations/{locale}"

    def test_anonymous_is_refused(self):
        response = self.client.get(self._url("hi"))
        self.assertIn(response.status_code, (302, 401))

    def test_a_signed_in_user_gets_the_documented_shape(self):
        self._login(self.base_coder_id)
        response = self.client.get(self._url("hi"))
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["locale"], "hi")
        self.assertEqual(payload["version"], 4)
        self.assertEqual(payload["questions"][self.item_key]["label"], "पहला प्रश्न")
        self.assertEqual(payload["choices"]["yes_no/yes"]["label"], "हाँ")

    def test_the_base_locale_is_always_served_and_carries_no_strings(self):
        self._login(self.base_coder_id)
        payload = self.client.get(self._url("en")).get_json()
        self.assertEqual(payload["version"], 0)
        self.assertEqual(payload["questions"], {})

    def test_an_inactive_locale_is_not_served(self):
        """Present first: the strings exist; they are still withheld."""
        self.assertIsNotNone(
            db.session.get(
                MapInstrumentTranslations,
                (INSTRUMENT, "kn", "question", self.item_key, "label"),
            ),
            "fixture guard: kn has strings to withhold",
        )
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get(self._url("kn")).status_code, 404)

        _locale("kn", active=True, version=2)
        db.session.commit()
        self.assertEqual(self.client.get(self._url("kn")).status_code, 200)

    def test_an_unknown_locale_or_instrument_is_404(self):
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get(self._url("zz")).status_code, 404)
        self.assertEqual(self.client.get(self._url("hi", "NOPE")).status_code, 404)

    def test_an_unchanged_version_revalidates_to_304(self):
        self._login(self.base_coder_id)
        first = self.client.get(self._url("hi"))
        self.assertEqual(first.status_code, 200)
        etag = first.headers["ETag"]

        again = self.client.get(self._url("hi"), headers={"If-None-Match": etag})
        self.assertEqual(again.status_code, 304)

    def test_a_moved_version_is_served_in_full(self):
        self._login(self.base_coder_id)
        etag = self.client.get(self._url("hi")).headers["ETag"]
        _locale("hi", active=True, version=5)
        db.session.commit()

        response = self.client.get(self._url("hi"), headers={"If-None-Match": etag})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["version"], 5)


class InstrumentTranslationAdminTests(BaseTestCase):
    """/admin/api/instrument-translations/... and its panel."""

    LOCALES_URL = "/admin/api/instrument-translations/locales"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.item_key = sorted(
            key[1] for key in svc.reference_label_keys(INSTRUMENT)
        )[0]
        cls.plain_user = cls._get_or_make_user("itr.plain@test.local", "Plain123")
        db.session.commit()

    def setUp(self):
        super().setUp()
        _locale("hi", active=True, version=4)
        _string("hi", self.item_key, "पहला प्रश्न")
        db.session.commit()

    def _api(self, suffix, locale="hi"):
        return f"/admin/api/instrument-translations/{INSTRUMENT}/{locale}{suffix}"

    # -- auth ---------------------------------------------------------------

    def test_anonymous_is_refused_everywhere(self):
        for url in (
            "/admin/panels/instrument-translations",
            self.LOCALES_URL,
            self._api("/strings"),
            self._api("/export"),
        ):
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, (302, 401))

    def test_a_non_admin_is_refused(self):
        self._login(str(self.plain_user.user_id))
        self.assertIn(self.client.get(self.LOCALES_URL).status_code, (302, 403))
        self.assertIn(
            self.client.get("/admin/panels/instrument-translations").status_code,
            (302, 403),
        )

    def test_a_coder_is_refused(self):
        self._login(self.base_coder_id)
        self.assertIn(self.client.get(self.LOCALES_URL).status_code, (302, 403))

    def test_the_panel_renders_for_an_admin(self):
        self._login(self.base_admin_id)
        response = self.client.get("/admin/panels/instrument-translations")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("panel-instrument-translations", body)
        self.assertIn("/admin/api/instrument-translations", body)

    # -- locales ------------------------------------------------------------

    def test_the_locale_list_carries_coverage_version_source_and_documented(self):
        self._login(self.base_admin_id)
        payload = self.client.get(self.LOCALES_URL).get_json()
        self.assertEqual(payload["coverage_threshold"], svc.TRANSLATION_COVERAGE_THRESHOLD)
        by_code = {row["locale_code"]: row for row in payload["locales"]}

        self.assertEqual(payload["locales"][0]["locale_code"], "en")
        self.assertTrue(by_code["en"]["is_base"])
        self.assertEqual(by_code["hi"]["version"], 4)
        self.assertTrue(by_code["hi"]["is_active"])
        self.assertGreaterEqual(by_code["hi"]["reference_labels"], 400)
        self.assertEqual(
            by_code["hi"]["documented_source"], "RJ01_ICMRVA_WHOVA2022.xlsx"
        )
        # One string out of 400-odd labels: far below the gate.
        self.assertLess(by_code["hi"]["coverage"], svc.TRANSLATION_COVERAGE_THRESHOLD)

    def test_deactivate_and_reactivate(self):
        self._login(self.base_admin_id)
        headers = self._csrf_headers()

        response = self.client.post(self._api("/deactivate"), json={}, headers=headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(response.get_json()["is_active"])

        # Below the coverage gate, so plain activation is refused...
        refused = self.client.post(self._api("/activate"), json={}, headers=headers)
        self.assertEqual(refused.status_code, 400)
        # ...and forcing it is the documented way through.
        forced = self.client.post(
            self._api("/activate"), json={"force": True}, headers=headers
        )
        self.assertEqual(forced.status_code, 200, forced.get_json())
        self.assertTrue(forced.get_json()["is_active"])

    # -- strings ------------------------------------------------------------

    def test_strings_are_paginated_with_the_english_reference(self):
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/strings?page_size=5")).get_json()
        self.assertEqual(payload["page_size"], 5)
        self.assertEqual(len(payload["items"]), 5)
        self.assertGreater(payload["total"], 5)
        for item in payload["items"]:
            self.assertTrue(item["english"])

    def test_a_page_size_above_the_cap_is_clamped_server_side(self):
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/strings?page_size=100000")).get_json()
        self.assertEqual(payload["page_size"], svc.MAX_STRING_PAGE_SIZE)
        self.assertLessEqual(len(payload["items"]), svc.MAX_STRING_PAGE_SIZE)

    def test_search_narrows_to_a_matching_item(self):
        self._login(self.base_admin_id)
        payload = self.client.get(
            self._api(f"/strings?q={self.item_key}")
        ).get_json()
        self.assertGreaterEqual(payload["total"], 1)
        self.assertTrue(
            any(item["item_key"] == self.item_key for item in payload["items"])
        )

    def test_an_edit_marks_it_edited_and_bumps_the_version(self):
        self._login(self.base_admin_id)
        before = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).version

        response = self.client.put(
            self._api("/strings"),
            json={
                "item_kind": "question", "item_key": self.item_key,
                "field": "label", "text": "बदला हुआ",
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual(body["old_text"], "पहला प्रश्न")
        self.assertEqual(body["text"], "बदला हुआ")
        self.assertEqual(body["version"], before + 1)

        db.session.expire_all()
        row = db.session.get(
            MapInstrumentTranslations,
            (INSTRUMENT, "hi", "question", self.item_key, "label"),
        )
        self.assertEqual(row.source, "edited")
        self.assertEqual(row.updated_by, self.base_admin_user.user_id)

    def test_an_edit_without_a_csrf_token_is_refused(self):
        self._login(self.base_admin_id)
        response = self.client.put(
            self._api("/strings"),
            json={"item_kind": "question", "item_key": self.item_key,
                  "field": "label", "text": "बदला हुआ"},
        )
        self.assertEqual(response.status_code, 400)

    def test_an_over_long_edit_is_refused_and_a_long_one_is_kept(self):
        from app.services.instrument_translation_service import (
            MAX_TRANSLATION_TEXT_CHARS,
        )

        self._login(self.base_admin_id)
        long_text = "क" * MAX_TRANSLATION_TEXT_CHARS
        response = self.client.put(
            self._api("/strings"),
            json={"item_kind": "question", "item_key": self.item_key,
                  "field": "label", "text": long_text},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        response = self.client.put(
            self._api("/strings"),
            json={"item_kind": "question", "item_key": self.item_key,
                  "field": "label", "text": long_text + "क"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_an_edit_of_an_unknown_item_is_refused(self):
        self._login(self.base_admin_id)
        response = self.client.put(
            self._api("/strings"),
            json={"item_kind": "question", "item_key": "NoSuchQuestion",
                  "field": "label", "text": "कुछ"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_an_edit_missing_a_field_is_refused(self):
        self._login(self.base_admin_id)
        response = self.client.put(
            self._api("/strings"),
            json={"item_kind": "question", "item_key": self.item_key, "field": "label"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)

    # -- export and import --------------------------------------------------

    def test_export_returns_the_serving_payload(self):
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/export")).get_json()
        self.assertEqual(payload["locale"], "hi")
        self.assertEqual(payload["questions"][self.item_key]["label"], "पहला प्रश्न")

    def test_import_refuses_anything_but_an_xlsx(self):
        self._login(self.base_admin_id)
        response = self.client.post(
            self._api("/import"),
            data={"file": (__import__("io").BytesIO(b"nope"), "source.csv")},
            content_type="multipart/form-data",
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("xlsx", response.get_json()["error"])

    def test_import_refuses_an_undocumented_workbook(self):
        self._login(self.base_admin_id)
        path = svc.WORKBOOK_DIR / "KA01_DS_WHOVA2022.xlsx"
        with path.open("rb") as handle:
            response = self.client.post(
                self._api("/import"),
                data={"file": (handle, "KA01_DS_WHOVA2022.xlsx")},
                content_type="multipart/form-data",
                headers=self._csrf_headers(),
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("RJ01_ICMRVA_WHOVA2022.xlsx", response.get_json()["error"])

    def test_import_of_the_documented_workbook_covers_and_activates(self):
        """The whole path: upload, parse, write, activate, serve."""
        self._login(self.base_admin_id)
        path = svc.WORKBOOK_DIR / "RJ01_ICMRVA_WHOVA2022.xlsx"
        with path.open("rb") as handle:
            response = self.client.post(
                self._api("/import"),
                data={"file": (handle, "RJ01_ICMRVA_WHOVA2022.xlsx")},
                content_type="multipart/form-data",
                headers=self._csrf_headers(),
            )
        self.assertEqual(response.status_code, 200, response.get_json())
        report = response.get_json()["report"]
        self.assertGreaterEqual(report["coverage"], svc.TRANSLATION_COVERAGE_THRESHOLD)
        self.assertTrue(report["activated"])
        self.assertGreater(report["written"], 400)

        payload = self.client.get(self._api("/export")).get_json()
        self.assertGreater(len(payload["questions"]), 400)
