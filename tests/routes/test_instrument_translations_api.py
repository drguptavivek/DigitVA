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
    LIFECYCLE_APPROVED,
    MapInstrumentTranslations,
    MasInstrumentLocales,
)
from app.routes import admin_translations as svc_routes
from app.services import instrument_translation_service as svc
from tests.base import BaseTestCase

INSTRUMENT = "WHO_2022_VA"


def _locale(code, *, active, version=1, name="Hindi", lifecycle_state=None):
    # An active row must be 'approved' (ck_mas_instrument_locales_active_
    # requires_approved, decided 2026-09-20): a fixture building an active
    # locale directly stands in for a locale that has already cleared review.
    if lifecycle_state is None:
        lifecycle_state = LIFECYCLE_APPROVED if active else "draft"
    row = db.session.get(MasInstrumentLocales, (INSTRUMENT, code))
    if row is None:
        row = MasInstrumentLocales(
            instrument_code=INSTRUMENT, locale_code=code, language_name=name,
            version=version, is_active=active, updated_at=datetime.now(UTC),
            lifecycle_state=lifecycle_state,
        )
        db.session.add(row)
    row.is_active = active
    row.version = version
    row.lifecycle_state = lifecycle_state
    db.session.flush()
    return row


def _string(code, item_key, text, *, field="label", kind="question", source="imported"):
    row = MapInstrumentTranslations(
        instrument_code=INSTRUMENT, locale_code=code, item_kind=kind,
        item_key=item_key, field=field, text=text, source=source,
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

    def _editor_url(self, locale="hi", code=INSTRUMENT):
        return f"/admin/instrument-translations/{code}/{locale}"

    def test_anonymous_is_refused_everywhere(self):
        for url in (
            "/admin/panels/instrument-translations",
            self._editor_url(),
            self.LOCALES_URL,
            self._api("/strings"),
            self._api("/questions"),
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
        self.assertIn(self.client.get(self._editor_url()).status_code, (302, 403))

    def test_a_coder_is_refused(self):
        self._login(self.base_coder_id)
        self.assertIn(self.client.get(self.LOCALES_URL).status_code, (302, 403))
        self.assertIn(self.client.get(self._editor_url()).status_code, (302, 403))

    def test_the_panel_renders_for_an_admin(self):
        self._login(self.base_admin_id)
        response = self.client.get("/admin/panels/instrument-translations")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("panel-instrument-translations", body)
        self.assertIn("/admin/api/instrument-translations", body)

    def test_the_editor_page_renders_for_an_admin(self):
        self._login(self.base_admin_id)
        response = self.client.get(self._editor_url("hi"))
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('id="ite-root"', body)
        self.assertIn('data-instrument-code="WHO_2022_VA"', body)
        self.assertIn('data-locale="hi"', body)
        self.assertIn("/admin/api/instrument-translations", body)

    def test_the_editor_page_uppercases_and_strips_the_instrument_code(self):
        self._login(self.base_admin_id)
        response = self.client.get(f"/admin/instrument-translations/{INSTRUMENT.lower()}/hi")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'data-instrument-code="WHO_2022_VA"', response.get_data(as_text=True)
        )

    # -- locales ------------------------------------------------------------

    def test_the_locale_list_carries_coverage_version_and_its_own_source(self):
        self._login(self.base_admin_id)
        payload = self.client.get(self.LOCALES_URL).get_json()
        self.assertNotIn("coverage_threshold", payload)
        self.assertNotIn("documented_locales", payload)
        by_code = {row["locale_code"]: row for row in payload["locales"]}

        self.assertEqual(payload["locales"][0]["locale_code"], "en")
        self.assertTrue(by_code["en"]["is_base"])
        self.assertEqual(by_code["hi"]["version"], 4)
        self.assertTrue(by_code["hi"]["is_active"])
        self.assertGreaterEqual(by_code["hi"]["reference_labels"], 400)
        # A row reports its own recorded source, never a policy-doc lookup:
        # the fixture set up "hi" without one, and none is invented here.
        self.assertNotIn("documented_source", by_code["hi"])
        self.assertIsNone(by_code["hi"]["source_document"])
        # Coverage is still reported, purely informational: one string out of
        # 400-odd labels is a low percentage, but nothing about the response
        # depends on where it sits relative to any threshold.
        self.assertLess(by_code["hi"]["coverage"], 1.0)
        self.assertIn("extension_coverage", by_code["hi"])

    def test_activation_is_explicit_and_independent_of_coverage(self):
        """Decided 2026-09-19: activation is never gated on coverage."""
        self._login(self.base_admin_id)
        headers = self._csrf_headers()

        response = self.client.post(self._api("/deactivate"), json={}, headers=headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(response.get_json()["is_active"])

        # Coverage is still low (the fixture guard)...
        locales = self.client.get(self.LOCALES_URL).get_json()["locales"]
        by_code = {row["locale_code"]: row for row in locales}
        self.assertLess(by_code["hi"]["coverage"], 1.0)

        # ...but a plain activation succeeds anyway: there is no gate to pass
        # or bypass, and no 'force' parameter left to bypass it with.
        activated = self.client.post(self._api("/activate"), json={}, headers=headers)
        self.assertEqual(activated.status_code, 200, activated.get_json())
        self.assertTrue(activated.get_json()["is_active"])
        self.assertLess(activated.get_json()["coverage"], 1.0)

    def test_an_unexpected_force_parameter_is_simply_ignored(self):
        """'force' has no meaning left; the route does not special-case it."""
        self._login(self.base_admin_id)
        headers = self._csrf_headers()
        response = self.client.post(
            self._api("/activate"), json={"force": True}, headers=headers
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["is_active"])

    # -- lifecycle: only 'approved' may be activated (decided 2026-09-20) ---

    def test_activating_a_draft_locale_is_refused_over_the_api(self):
        _locale("zz", active=False, version=1, name="Zulu")  # defaults to draft
        db.session.commit()
        self._login(self.base_admin_id)
        response = self.client.post(
            self._api("/activate", "zz"), json={}, headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("draft", response.get_json()["error"])

    def test_the_lifecycle_route_moves_a_locale_to_approved_and_then_activates(self):
        _locale("zz", active=False, version=1, name="Zulu")
        db.session.commit()
        self._login(self.base_admin_id)
        headers = self._csrf_headers()

        review = self.client.post(
            self._api("/lifecycle", "zz"), json={"state": "in_review"}, headers=headers,
        )
        self.assertEqual(review.status_code, 200, review.get_json())
        self.assertEqual(review.get_json()["lifecycle_state"], "in_review")

        approve = self.client.post(
            self._api("/lifecycle", "zz"), json={"state": "approved"}, headers=headers,
        )
        self.assertEqual(approve.status_code, 200, approve.get_json())
        self.assertEqual(approve.get_json()["lifecycle_state"], "approved")
        self.assertIsNotNone(approve.get_json()["approved_at"])

        activated = self.client.post(
            self._api("/activate", "zz"), json={}, headers=headers,
        )
        self.assertEqual(activated.status_code, 200, activated.get_json())
        self.assertTrue(activated.get_json()["is_active"])

    def test_leaving_approved_while_active_is_refused_over_the_api(self):
        # setUp's "hi" is active and approved (see the _locale helper).
        self._login(self.base_admin_id)
        response = self.client.post(
            self._api("/lifecycle"), json={"state": "in_review"}, headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("deactivate", response.get_json()["error"].lower())

    def test_lifecycle_route_requires_csrf_and_admin(self):
        _locale("zz", active=False, version=1, name="Zulu")
        db.session.commit()
        anon = self.client.post(self._api("/lifecycle", "zz"), json={"state": "in_review"})
        # CSRF is checked ahead of login, so an anonymous POST with no token
        # can surface as 400 rather than a redirect/401 (see the XLIFF route's
        # own anonymous-POST test above for the same shape).
        self.assertIn(anon.status_code, (302, 400, 401))

        self._login(self.base_admin_id)
        no_csrf = self.client.post(self._api("/lifecycle", "zz"), json={"state": "in_review"})
        self.assertEqual(no_csrf.status_code, 400)

        self._login(str(self.plain_user.user_id))
        as_plain = self.client.post(
            self._api("/lifecycle", "zz"), json={"state": "in_review"},
            headers=self._csrf_headers(),
        )
        self.assertIn(as_plain.status_code, (302, 403))

    def test_lifecycle_route_refuses_an_unknown_state(self):
        _locale("zz", active=False, version=1, name="Zulu")
        db.session.commit()
        self._login(self.base_admin_id)
        response = self.client.post(
            self._api("/lifecycle", "zz"), json={"state": "whatever"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)

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

    # -- questions (digitva-8go) -----------------------------------------

    def test_questions_are_ordered_by_form_position_not_alphabetically(self):
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/questions?page_size=5")).get_json()
        names = [item["name"] for item in payload["items"]]
        # Id10010 (order 2) comes before Id10010a (order 3) comes before
        # Id10010b (order 4) -- alphabetical order would put Id10010a first.
        self.assertEqual(names[:3], ["Id10010", "Id10010a", "Id10010b"])
        orders = [item["order"] for item in payload["items"]]
        self.assertEqual(orders, sorted(orders))

    def test_questions_are_paginated_by_question_not_by_string(self):
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/questions?page_size=1")).get_json()
        self.assertEqual(len(payload["items"]), 1)
        # 536: the 446 base-instrument questions (449 minus the 3 with no
        # display text: the audit trail, two calculated-only fields) plus the
        # DigitVA layer's 80 questions/sections and 10 choice lists that no
        # question can be linked to as owner (digitva-8go follow-up).
        self.assertEqual(payload["total"], 536)

    def test_layer_questions_appear_after_every_base_question(self):
        """digitva-8go follow-up: the layers were missing entirely at first,
        which made their machine-drafted strings unreachable for Accept."""
        self._login(self.base_admin_id)
        all_items = []
        for page in (1, 2, 3):
            payload = self.client.get(
                self._api(f"/questions?page_size=200&page={page}")
            ).get_json()
            all_items.extend(payload["items"])
        self.assertEqual(len(all_items), 536)

        by_name = {item["name"]: item for item in all_items}
        for name in ("consent_mode", "abha_number", "socialautopsy", "sa01"):
            self.assertIn(name, by_name, name)

        base_names = {q["name"] for q in svc._generated_questions(INSTRUMENT)}
        base_orders = [item["order"] for item in all_items if item["name"] in base_names]
        layer_orders = [
            item["order"] for item in all_items if item["name"] not in base_names
        ]
        self.assertTrue(layer_orders, "fixture guard: some layer rows present")
        self.assertGreater(min(layer_orders), max(base_orders))

        orders = [item["order"] for item in all_items]
        self.assertEqual(orders, sorted(orders))

        # A layer question is not universal: it only exists in a project with
        # that extension enabled, so it carries which one(s).
        self.assertEqual(by_name["consent_mode"]["extensions"], ["digitva_core"])
        self.assertNotIn("extensions", by_name["Id10010"])

    def test_a_machine_drafted_layer_row_carries_its_source_for_accept(self):
        """The layers file arrives with 'machine' rows awaiting a human
        Accept; the per-question view must not hide that, or the Accept
        workflow the old flat list offered becomes unreachable."""
        _string("hi", "consent_mode", "सहमति किस माध्यम से ली गई", source="machine")
        db.session.commit()
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/questions?q=consent_mode")).get_json()
        item = next(i for i in payload["items"] if i["name"] == "consent_mode")
        self.assertEqual(item["source"], "machine")
        self.assertEqual(item["translated_label"], "सहमति किस माध्यम से ली गई")

    def test_a_layer_choice_list_with_no_known_question_owner_gets_its_own_row(self):
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/questions?q=CONSENT_MODE")).get_json()
        item = next(i for i in payload["items"] if i["name"] == "CONSENT_MODE")
        self.assertTrue(item["is_choice_list"])
        self.assertEqual(item["list_name"], "CONSENT_MODE")
        self.assertEqual(item["extensions"], ["digitva_core"])
        values = {choice["value"] for choice in item["choices"]}
        self.assertEqual(values, {"in_person", "telephonic"})
        self.assertNotIn("english_label", item)

    def test_a_layer_extends_a_base_choice_list_on_the_same_row(self):
        """"language" is a base list (used by the base "language" question)
        that narration_language adds more values to -- it must stay one row,
        not a second one for the same list (digitva-8go)."""
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/questions?q=Interview+language")).get_json()
        rows = [i for i in payload["items"] if i.get("list_name") == "language"]
        self.assertEqual(len(rows), 1)
        item = rows[0]
        self.assertEqual(item["name"], "language")
        values = {choice["value"] for choice in item["choices"]}
        self.assertIn("en", values)
        self.assertIn("bangla", values)
        added = next(c for c in item["choices"] if c["value"] == "bangla")
        self.assertEqual(added["extensions"], ["narration_language"])
        base_choice = next(c for c in item["choices"] if c["value"] == "en")
        self.assertNotIn("extensions", base_choice)

    def test_a_shared_choice_list_reports_how_many_questions_use_it(self):
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/questions?q=Id10002")).get_json()
        item = next(i for i in payload["items"] if i["name"] == "Id10002")
        self.assertEqual(item["list_name"], "HIGH_LOW_VERY")
        self.assertEqual(item["shared_with"], 2)
        values = {choice["value"] for choice in item["choices"]}
        self.assertEqual(values, {"high", "low", "veryl"})

    def test_search_matches_question_code_or_english_text(self):
        self._login(self.base_admin_id)
        by_code = self.client.get(self._api("/questions?q=Id10002")).get_json()
        self.assertTrue(any(i["name"] == "Id10002" for i in by_code["items"]))

        by_text = self.client.get(
            self._api("/questions?q=Age+of+VA+interviewer")
        ).get_json()
        self.assertTrue(any(i["name"] == "Id10010a" for i in by_text["items"]))

        no_match = self.client.get(self._api("/questions?q=NoSuchThingAtAll")).get_json()
        self.assertEqual(no_match["total"], 0)

    def test_a_question_with_no_hint_or_choices_is_handled(self):
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/questions?q=Id10012")).get_json()
        item = next(i for i in payload["items"] if i["name"] == "Id10012")
        self.assertNotIn("hint", item)
        self.assertNotIn("list_name", item)
        self.assertNotIn("choices", item)
        self.assertTrue(item["english_label"])

    def test_a_page_size_above_the_cap_is_clamped_on_questions_too(self):
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/questions?page_size=100000")).get_json()
        self.assertEqual(payload["page_size"], svc.MAX_STRING_PAGE_SIZE)
        self.assertLessEqual(len(payload["items"]), svc.MAX_STRING_PAGE_SIZE)

    def test_questions_route_requires_admin(self):
        self.assertIn(
            self.client.get(self._api("/questions")).status_code, (302, 401)
        )
        self._login(self.base_coder_id)
        self.assertIn(self.client.get(self._api("/questions")).status_code, (302, 403))

    def test_saving_a_choice_option_reports_how_many_questions_share_it(self):
        """The choice edit stays global (keyed by list_name/value); the
        response carries ``shared_with`` so the UI can warn about it."""
        self._login(self.base_admin_id)
        response = self.client.put(
            self._api("/strings"),
            json={
                "item_kind": "choice", "item_key": "HIGH_LOW_VERY/high",
                "field": "label", "text": "ऊँचा",
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["shared_with"], 2)

    def test_saving_a_label_carries_no_shared_with(self):
        self._login(self.base_admin_id)
        response = self.client.put(
            self._api("/strings"),
            json={
                "item_kind": "question", "item_key": self.item_key,
                "field": "label", "text": "बदला हुआ",
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertNotIn("shared_with", response.get_json())

    # -- accept-as-is (digitva-4kj) -------------------------------------

    def test_accept_promotes_a_machine_row_to_edited(self):
        _string("hi", "machine_q", "मशीन अनुवाद", source="machine")
        db.session.commit()
        self._login(self.base_admin_id)

        response = self.client.post(
            self._api("/strings/accept"),
            json={"item_kind": "question", "item_key": "machine_q", "field": "label"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual(body["source"], "edited")
        self.assertEqual(body["text"], "मशीन अनुवाद")

        db.session.expire_all()
        row = db.session.get(
            MapInstrumentTranslations,
            (INSTRUMENT, "hi", "question", "machine_q", "label"),
        )
        self.assertEqual(row.source, "edited")

    def test_accept_on_a_non_machine_row_is_refused(self):
        self._login(self.base_admin_id)
        response = self.client.post(
            self._api("/strings/accept"),
            json={"item_kind": "question", "item_key": self.item_key, "field": "label"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_accept_requires_csrf_and_admin(self):
        _string("hi", "machine_q", "मशीन अनुवाद", source="machine")
        db.session.commit()
        payload = {"item_kind": "question", "item_key": "machine_q", "field": "label"}

        anon = self.client.post(self._api("/strings/accept"), json=payload)
        self.assertIn(anon.status_code, (302, 400, 401))

        self._login(self.base_admin_id)
        no_csrf = self.client.post(self._api("/strings/accept"), json=payload)
        self.assertEqual(no_csrf.status_code, 400)

        self._login(str(self.plain_user.user_id))
        as_plain = self.client.post(
            self._api("/strings/accept"), json=payload, headers=self._csrf_headers(),
        )
        self.assertIn(as_plain.status_code, (302, 403))

    # -- export and import --------------------------------------------------

    def test_export_returns_the_serving_payload(self):
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/export")).get_json()
        self.assertEqual(payload["locale"], "hi")
        self.assertEqual(payload["questions"][self.item_key]["label"], "पहला प्रश्न")

    def test_export_excludes_a_machine_row(self):
        """digitva-4kj: export_translations must omit 'machine' rows so the
        client falls back to English for exactly those strings."""
        _string("hi", "machine_q", "मशीन अनुवाद", source="machine")
        db.session.commit()
        self._login(self.base_admin_id)
        payload = self.client.get(self._api("/export")).get_json()
        self.assertIn(self.item_key, payload["questions"])
        self.assertNotIn("machine_q", payload["questions"])

    # -- XLIFF 2.0 interchange ---------------------------------------------

    def _xliff_document(self, trg="hi"):
        """A one-unit XLIFF 2.0 document for a real reference item."""
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<xliff xmlns="{svc.XLIFF_NAMESPACE}" version="2.0" '
            f'srcLang="en" trgLang="{trg}">'
            f'<file id="{INSTRUMENT}">'
            f'<unit id="{svc.resource_id("question", self.item_key, "label")}">'
            '<segment state="translated"><source>First</source>'
            "<target>एक्सलिफ़ से</target></segment></unit></file></xliff>"
        )

    def _upload(self, document, filename="hi.xlf", **form):
        import io

        data = {"file": (io.BytesIO(document.encode("utf-8")), filename)}
        data.update(form)
        return data

    def test_the_xliff_routes_refuse_anonymous_non_admin_and_coder(self):
        get_url, post_url = self._api("/xliff"), self._api("/xliff")
        self.assertIn(self.client.get(get_url).status_code, (302, 401))
        self.assertIn(self.client.post(post_url).status_code, (302, 400, 401))

        for user_id in (str(self.plain_user.user_id), self.base_coder_id):
            with self.subTest(user_id=user_id):
                self._login(user_id)
                self.assertIn(self.client.get(get_url).status_code, (302, 403))
                self.assertIn(
                    self.client.post(
                        post_url,
                        data=self._upload(self._xliff_document()),
                        content_type="multipart/form-data",
                        headers=self._csrf_headers(),
                    ).status_code,
                    (302, 403),
                )

    def test_export_serves_an_xliff_document_as_a_download(self):
        self._login(self.base_admin_id)
        response = self.client.get(self._api("/xliff"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, svc.XLIFF_MEDIA_TYPE)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn(
            f"{INSTRUMENT}-hi.xlf", response.headers["Content-Disposition"]
        )
        body = response.get_data(as_text=True)
        self.assertIn(svc.XLIFF_NAMESPACE, body)
        self.assertIn('trgLang="hi"', body)

    def test_export_of_an_unknown_locale_is_404(self):
        self._login(self.base_admin_id)
        self.assertEqual(self.client.get(self._api("/xliff", "zz")).status_code, 404)

    def test_an_upload_writes_the_target_and_reports_it(self):
        self._login(self.base_admin_id)
        before = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).version
        response = self.client.post(
            self._api("/xliff"),
            data=self._upload(
                self._xliff_document(), **{"as": "edited", "acknowledge_demotion": "1"}
            ),
            content_type="multipart/form-data",
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        report = response.get_json()["report"]
        self.assertEqual(report["units"], 1)
        self.assertEqual(report["written"], 1)
        # setUp's "hi" is approved+active (digitva-dqh): a bulk hand-back
        # demoted it, and that bumps the version too.
        self.assertTrue(report["demoted"])
        self.assertEqual(report["version"], before + 1)

        db.session.expire_all()
        row = db.session.get(
            MapInstrumentTranslations,
            (INSTRUMENT, "hi", "question", self.item_key, "label"),
        )
        self.assertEqual(row.text, "एक्सलिफ़ से")
        self.assertEqual(row.source, "edited")

    def test_an_upload_without_a_csrf_token_is_refused(self):
        self._login(self.base_admin_id)
        response = self.client.post(
            self._api("/xliff"),
            data=self._upload(self._xliff_document()),
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        # Present first: the same upload with a token is accepted. setUp's
        # "hi" is approved+active, so this also needs the demotion
        # acknowledgement (digitva-dqh) to reach 200 rather than the
        # approval refusal.
        accepted = self.client.post(
            self._api("/xliff"),
            data=self._upload(self._xliff_document(), acknowledge_demotion="1"),
            content_type="multipart/form-data",
            headers=self._csrf_headers(),
        )
        self.assertEqual(accepted.status_code, 200, accepted.get_json())

    def test_an_oversized_upload_is_refused(self):
        self._login(self.base_admin_id)
        oversized = self._xliff_document().replace(
            "एक्सलिफ़ से", "x" * (svc_routes.MAX_UPLOAD_BYTES + 1)
        )
        response = self.client.post(
            self._api("/xliff"),
            data=self._upload(oversized),
            content_type="multipart/form-data",
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("MB", response.get_json()["error"])

    def test_an_upload_that_is_not_an_xlf_or_a_bad_mark_as_is_refused(self):
        self._login(self.base_admin_id)
        wrong_suffix = self.client.post(
            self._api("/xliff"),
            data=self._upload(self._xliff_document(), filename="hi.xml"),
            content_type="multipart/form-data",
            headers=self._csrf_headers(),
        )
        self.assertEqual(wrong_suffix.status_code, 400)

        bad_mark = self.client.post(
            self._api("/xliff"),
            data=self._upload(self._xliff_document(), **{"as": "whatever"}),
            content_type="multipart/form-data",
            headers=self._csrf_headers(),
        )
        self.assertEqual(bad_mark.status_code, 400)

    def test_an_xliff_upload_into_an_approved_locale_is_refused_without_acknowledgement(self):
        """digitva-dqh: same refusal, named for the locale and the consequence,
        for the XLIFF route as for the workbook import route."""
        self._login(self.base_admin_id)
        before = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).version
        response = self.client.post(
            self._api("/xliff"),
            data=self._upload(self._xliff_document()),
            content_type="multipart/form-data",
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        error = response.get_json()["error"]
        self.assertIn("hi", error)
        self.assertIn("approved", error)
        db.session.expire_all()
        row = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))
        self.assertEqual(row.lifecycle_state, LIFECYCLE_APPROVED)
        self.assertEqual(row.version, before)

    def test_an_upload_for_another_language_is_refused(self):
        self._login(self.base_admin_id)
        response = self.client.post(
            self._api("/xliff"),
            data=self._upload(self._xliff_document(trg="ta")),
            content_type="multipart/form-data",
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("target language", response.get_json()["error"])

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

    def test_an_import_for_a_different_language_still_succeeds(self):
        """Any readable workbook is accepted for any locale (decided 2026-09-20).

        KA01_DS_WHOVA2022.xlsx is Kannada's source, not Hindi's, but it is
        uploaded here as an import *for* "hi": the old refusal is gone, so
        whatever Hindi strings that workbook happens to carry (its layer over
        the same reference structure) are written.
        """
        self._login(self.base_admin_id)
        path = svc.WORKBOOK_DIR / "KA01_DS_WHOVA2022.xlsx"
        with path.open("rb") as handle:
            response = self.client.post(
                self._api("/import"),
                # setUp's "hi" is approved+active: this bulk re-import needs
                # the demotion acknowledgement (digitva-dqh).
                data={"file": (handle, "KA01_DS_WHOVA2022.xlsx"), "acknowledge_demotion": "1"},
                content_type="multipart/form-data",
                headers=self._csrf_headers(),
            )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["report"]["workbook"], "KA01_DS_WHOVA2022.xlsx")

    def test_an_import_into_an_approved_locale_is_refused_without_acknowledgement(self):
        """digitva-dqh: refused, naming the locale and the consequence,
        without the acknowledgement field -- and nothing is written."""
        self._login(self.base_admin_id)
        before = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).version
        path = svc.WORKBOOK_DIR / "KA01_DS_WHOVA2022.xlsx"
        with path.open("rb") as handle:
            response = self.client.post(
                self._api("/import"),
                data={"file": (handle, "KA01_DS_WHOVA2022.xlsx")},
                content_type="multipart/form-data",
                headers=self._csrf_headers(),
            )
        self.assertEqual(response.status_code, 400)
        error = response.get_json()["error"]
        self.assertIn("hi", error)
        self.assertIn("approved", error)
        db.session.expire_all()
        row = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))
        self.assertEqual(row.lifecycle_state, LIFECYCLE_APPROVED)
        self.assertTrue(row.is_active)
        self.assertEqual(row.version, before)

    def test_import_of_a_workbook_writes_but_does_not_activate(self):
        """The whole path: upload, parse, write, then an explicit approve,
        activate, serve -- against a locale nobody has approved yet, so this
        is not the approved-locale demotion path (digitva-dqh), which has its
        own tests above."""
        self._login(self.base_admin_id)
        row = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))
        row.lifecycle_state = "draft"
        row.is_active = False
        db.session.commit()
        workbook_name = "ND01_ICMRVA_WHOVA2022.xlsx"
        path = svc.WORKBOOK_DIR / workbook_name
        with path.open("rb") as handle:
            response = self.client.post(
                self._api("/import"),
                data={"file": (handle, workbook_name)},
                content_type="multipart/form-data",
                headers=self._csrf_headers(),
            )
        self.assertEqual(response.status_code, 200, response.get_json())
        report = response.get_json()["report"]
        self.assertGreaterEqual(report["label_coverage"], 0.95)
        self.assertFalse(report["demoted"])
        self.assertNotIn("activated", report)
        self.assertGreater(report["written"], 400)
        self.assertIn("extension_coverage", report)

        # The import alone does not activate...
        locales = self.client.get(self.LOCALES_URL).get_json()["locales"]
        by_code = {row["locale_code"]: row for row in locales}
        self.assertFalse(by_code["hi"]["is_active"])

        # ...approval and activation are the separate, explicit steps.
        approved = self.client.post(
            self._api("/lifecycle"), json={"state": "approved"}, headers=self._csrf_headers()
        )
        self.assertEqual(approved.status_code, 200, approved.get_json())
        activated = self.client.post(
            self._api("/activate"), json={}, headers=self._csrf_headers()
        )
        self.assertEqual(activated.status_code, 200, activated.get_json())
        self.assertTrue(activated.get_json()["is_active"])

        payload = self.client.get(self._api("/export")).get_json()
        self.assertGreater(len(payload["questions"]), 400)
