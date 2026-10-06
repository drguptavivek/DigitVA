"""District suggestions for instrument translations (digitva-5op).

/api/v1/translations/...: any grant holder reads the served locales of the
project beside the English and suggests a wording; an administrator or that
project's PI accepts (through ``update_string``, source ``edited``) or rejects.
Policy: docs/policy/va-form-project-configuration.md.
"""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.models.map_instrument_translation_suggestions import (
    SUGGESTION_ACCEPTED,
    SUGGESTION_PENDING,
    SUGGESTION_REJECTED,
    MapInstrumentTranslationSuggestions as Suggestion,
)
from app.models.mas_instrument_locales import MapInstrumentTranslations, MasInstrumentLocales
from app.services import instrument_translation_service as svc
from tests.base import BaseTestCase
from tests.routes.test_instrument_translations_api import INSTRUMENT, _locale, _string

OTHER_PROJECT = "TSG002"
API = "/api/v1/translations"


class TranslationSuggestionTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=OTHER_PROJECT, project_code=OTHER_PROJECT, project_name="Other",
            project_nickname="Other", project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now,
        ))
        db.session.flush()
        cls.other_pi = cls._make_user("ts.other.pi@test.local", "OtherPi123")
        cls.outsider = cls._make_user("ts.outsider@test.local", "Outsider123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.other_pi.user_id, role=VaAccessRoles.project_pi,
            scope_type=VaAccessScopeTypes.project, project_id=OTHER_PROJECT,
            notes="ts other pi", grant_status=VaStatuses.active,
        ))
        db.session.commit()
        # A real reference item, so the fixture cannot drift from the form.
        cls.item_key = sorted(key[1] for key in svc.reference_label_keys(INSTRUMENT))[0]

    def setUp(self):
        super().setUp()
        # hi: served by both projects. ur: active but offered by neither list.
        # kn: a draft, never servable.
        _locale("hi", active=True, version=3)
        _locale("ur", active=True, name="Urdu")
        _locale("kn", active=False, name="Kannada")
        self.hi_label = _string("hi", self.item_key, "पहला प्रश्न")
        _string("ur", self.item_key, "اردو")
        _string("kn", self.item_key, "ಮೊದಲ")
        for project_id, offered in (
            (self.BASE_PROJECT_ID, ["hi", "kn"]), (OTHER_PROJECT, ["hi"]),
        ):
            db.session.get(VaProjectMaster, project_id).web_intake_available_locales = offered
        db.session.commit()

    # -- helpers -------------------------------------------------------------

    def _post(self, url, body=None):
        return self.client.post(url, json=body or {}, headers=self._csrf_headers())

    def _suggest(self, user_id=None, *, text="बेहतर शब्द", reason="clearer", project=None,
                 locale="hi", key=None, field="label", kind="question"):
        self._login(user_id or self.base_coder_id)
        return self._post(
            f"{API}/{project or self.BASE_PROJECT_ID}/{locale}/suggestions",
            {"item_kind": kind, "item_key": key or self.item_key, "field": field,
             "proposed_text": text, "reason": reason},
        )

    def _pending_row(self, **overrides):
        """A pending suggestion written directly, to set up a decision."""
        values = dict(
            instrument_code=INSTRUMENT, locale_code="hi", item_kind="question",
            item_key=self.item_key, field="label", proposed_text="बेहतर शब्द",
            seen_text="पहला प्रश्न", reason="clearer", project_id=self.BASE_PROJECT_ID,
            suggested_by=uuid.UUID(self.base_coder_id),
        )
        values.update(overrides)
        row = Suggestion(**values)
        db.session.add(row)
        db.session.commit()
        return row

    def _stored(self, locale="hi"):
        db.session.expire_all()
        return db.session.get(
            MapInstrumentTranslations, (INSTRUMENT, locale, "question", self.item_key, "label")
        )

    def _question_row(self, locale="hi"):
        response = self.client.get(
            f"{API}/{self.BASE_PROJECT_ID}/{locale}/questions", query_string={"q": self.item_key}
        )
        self.assertEqual(response.status_code, 200)
        rows = [r for r in response.get_json()["items"] if r["name"] == self.item_key]
        self.assertEqual(len(rows), 1, "present first: the question is on the page")
        return rows[0]

    # -- reading -------------------------------------------------------------

    def test_reader_sees_only_the_locales_the_project_serves(self):
        self._login(self.base_coder_id)
        body = self.client.get(f"{API}/{self.BASE_PROJECT_ID}").get_json()
        # kn is offered by the project but is a draft; ur is active but not
        # offered; en is the instrument's own language.
        self.assertEqual([l["code"] for l in body["locales"]], ["hi"])
        self.assertFalse(body["can_decide"])
        for locale in ("ur", "kn", "en"):
            with self.subTest(locale=locale):
                response = self.client.get(f"{API}/{self.BASE_PROJECT_ID}/{locale}/questions")
                self.assertEqual(response.status_code, 404)
        # Present first: the served locale does read.
        self.assertEqual(self._question_row()["translated_label"], "पहला प्रश्न")

    def test_reading_pairs_the_english_with_the_translation(self):
        self._login(self.base_coder_id)
        row = self._question_row()
        self.assertTrue(row["english_label"])
        self.assertEqual(row["translated_label"], "पहला प्रश्न")

    def test_a_machine_draft_is_never_shown(self):
        self.hi_label.source = "machine"
        db.session.commit()
        self._login(self.base_coder_id)
        row = self._question_row()
        self.assertTrue(row["english_label"])  # present first: the row is there
        self.assertIsNone(row["translated_label"])
        self.assertNotIn("पहला प्रश्न", self.client.get(
            f"{API}/{self.BASE_PROJECT_ID}/hi/questions", query_string={"q": self.item_key}
        ).get_data(as_text=True))

    def test_the_page_size_is_clamped(self):
        self._login(self.base_coder_id)
        body = self.client.get(
            f"{API}/{self.BASE_PROJECT_ID}/hi/questions", query_string={"page_size": 100000}
        ).get_json()
        self.assertEqual(body["page_size"], 50)
        self.assertLessEqual(len(body["items"]), 50)

    def test_a_user_with_no_grant_in_the_project_gets_404(self):
        self._login(str(self.outsider.user_id))
        for url in (f"{API}/{self.BASE_PROJECT_ID}", f"{API}/{self.BASE_PROJECT_ID}/hi/questions"):
            self.assertEqual(self.client.get(url).status_code, 404)
        response = self._suggest(str(self.outsider.user_id))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Suggestion)), 0)
        # The other project's PI holds no grant in BASE01 either.
        self._login(str(self.other_pi.user_id))
        self.assertEqual(self.client.get(f"{API}/{self.BASE_PROJECT_ID}").status_code, 404)

    # -- suggesting ----------------------------------------------------------

    def test_a_suggestion_stores_what_the_suggester_saw(self):
        response = self._suggest()
        self.assertEqual(response.status_code, 201)
        row = db.session.get(Suggestion, response.get_json()["id"])
        self.assertEqual(
            (row.seen_text, row.proposed_text, row.reason, row.status, row.project_id),
            ("पहला प्रश्न", "बेहतर शब्द", "clearer", SUGGESTION_PENDING, self.BASE_PROJECT_ID),
        )
        self.assertEqual(str(row.suggested_by), self.base_coder_id)
        # The translation itself is untouched.
        self.assertEqual(self._stored().text, "पहला प्रश्न")

    def test_a_suggestion_over_a_machine_draft_saw_nothing(self):
        self.hi_label.source = "machine"
        db.session.commit()
        response = self._suggest()
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(db.session.get(Suggestion, response.get_json()["id"]).seen_text)

    def test_a_suggestion_is_validated(self):
        cases = {
            "unknown key": dict(key="no_such_question"),
            "empty text": dict(text="  "),
            "no reason": dict(reason=""),
            "over the length cap": dict(text="x" * (svc.MAX_TRANSLATION_TEXT_CHARS + 1)),
            "reason too long": dict(reason="x" * 1001),
            "same as current": dict(text="पहला प्रश्न"),
            "bad kind": dict(kind="section"),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                response = self._suggest(**kwargs)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["code"], "invalid_request")
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Suggestion)), 0)

    def test_a_second_pending_suggestion_for_the_string_is_refused(self):
        self.assertEqual(self._suggest().status_code, 201)
        response = self._suggest(text="एक और")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "already_pending")

    def test_suggesting_needs_the_csrf_token(self):
        self._login(self.base_coder_id)
        response = self.client.post(
            f"{API}/{self.BASE_PROJECT_ID}/hi/suggestions",
            json={"item_kind": "question", "item_key": self.item_key, "field": "label",
                  "proposed_text": "x", "reason": "y"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Suggestion)), 0)

    def test_suggesting_is_rate_limited_per_user(self):
        user = self._make_user("ts.rate@test.local", "Rate12345")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=VaAccessRoles.coder, scope_type=VaAccessScopeTypes.project,
            project_id=self.BASE_PROJECT_ID, notes="rate", grant_status=VaStatuses.active,
        ))
        db.session.commit()
        statuses = [self._suggest(str(user.user_id), reason="").status_code for _ in range(31)]
        self.assertEqual(set(statuses[:30]), {400})  # present first: counted, refused by validation
        self.assertEqual(statuses[30], 429)

    # -- deciding ------------------------------------------------------------

    def test_who_may_decide(self):
        for user_id, expected in (
            (self.base_coder_id, False), (self.base_project_pi_id, True), (self.base_admin_id, True),
        ):
            self._login(user_id)
            body = self.client.get(f"{API}/{self.BASE_PROJECT_ID}").get_json()
            self.assertEqual(body["can_decide"], expected, user_id)
        self._login(self.base_coder_id)
        row = self._pending_row()
        self.assertEqual(self.client.get(f"{API}/suggestions").status_code, 403)
        self.assertEqual(self._post(f"{API}/suggestions/{row.id}/accept").status_code, 403)
        self.assertEqual(self._stored().text, "पहला प्रश्न")

    def test_a_pi_of_another_project_cannot_decide(self):
        row = self._pending_row()
        self._login(str(self.other_pi.user_id))
        self.assertEqual(self.client.get(f"{API}/suggestions").get_json()["total"], 0)
        for verb in ("accept", "reject"):
            self.assertEqual(self._post(f"{API}/suggestions/{row.id}/{verb}").status_code, 404)
        db.session.expire_all()
        self.assertEqual(db.session.get(Suggestion, row.id).status, SUGGESTION_PENDING)
        self.assertEqual(self._stored().text, "पहला प्रश्न")

    def test_a_pi_cannot_decide_a_locale_their_project_does_not_serve(self):
        # Made in OTHER01, for ur, which OTHER01 does not offer.
        row = self._pending_row(
            project_id=OTHER_PROJECT, locale_code="ur", seen_text="اردو", proposed_text="نیا",
        )
        self._login(str(self.other_pi.user_id))
        self.assertEqual(self.client.get(f"{API}/suggestions").get_json()["total"], 0)
        self.assertEqual(self._post(f"{API}/suggestions/{row.id}/accept").status_code, 403)
        self.assertEqual(self._stored("ur").text, "اردو")
        # An administrator is not limited to a project's locales.
        self._login(self.base_admin_id)
        self.assertEqual(self._post(f"{API}/suggestions/{row.id}/accept").status_code, 200)
        self.assertEqual(self._stored("ur").text, "نیا")

    def test_accept_writes_an_edited_translation_and_audits_both_users(self):
        suggested = self._suggest()
        self.assertEqual(suggested.status_code, 201)
        sid = suggested.get_json()["id"]
        before = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).version

        self._login(self.base_project_pi_id)
        with self.assertLogs("app.services.instrument_translation_suggestion_service", "INFO") as logs, \
                self.assertLogs("app.services.instrument_translation_service", "INFO") as edit_logs:
            response = self._post(f"{API}/suggestions/{sid}/accept", {"note": "agreed"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["changes_all_projects"])

        stored = self._stored()
        self.assertEqual((stored.text, stored.source), ("बेहतर शब्द", "edited"))
        self.assertEqual(str(stored.updated_by), self.base_project_pi_id)
        self.assertEqual(db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).version, before + 1)
        row = db.session.get(Suggestion, sid)
        self.assertEqual(
            (row.status, str(row.decided_by), row.decision_note),
            (SUGGESTION_ACCEPTED, self.base_project_pi_id, "agreed"),
        )
        self.assertIsNotNone(row.decided_at)
        line = " ".join(logs.output)
        self.assertIn(self.base_coder_id, line)
        self.assertIn(self.base_project_pi_id, line)
        self.assertIn(self.base_project_pi_id, " ".join(edit_logs.output))
        # Decided: a second decision is refused.
        self.assertEqual(self._post(f"{API}/suggestions/{sid}/reject").status_code, 409)

    def test_accept_after_the_string_changed_is_409(self):
        row = self._pending_row()
        self.hi_label.text = "बदला हुआ"
        db.session.commit()
        self._login(self.base_project_pi_id)
        listed = self.client.get(f"{API}/suggestions").get_json()["items"][0]
        self.assertTrue(listed["stale"])
        response = self._post(f"{API}/suggestions/{row.id}/accept")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "stale")
        self.assertEqual(self._stored().text, "बदला हुआ")
        self.assertEqual(db.session.get(Suggestion, row.id).status, SUGGESTION_PENDING)

    def test_accept_over_a_string_a_draft_became_a_real_translation_is_409(self):
        self.hi_label.source = "machine"
        db.session.commit()
        row = self._pending_row(seen_text=None)
        self.hi_label.source = "edited"  # a speaker accepted the draft meanwhile
        db.session.commit()
        self._login(self.base_admin_id)
        self.assertEqual(self._post(f"{API}/suggestions/{row.id}/accept").status_code, 409)

    def test_reject_leaves_the_translation(self):
        row = self._pending_row()
        self._login(self.base_project_pi_id)
        response = self._post(f"{API}/suggestions/{row.id}/reject", {"note": "no"})
        self.assertEqual(response.status_code, 200)
        stored = self._stored()
        self.assertEqual((stored.text, stored.source), ("पहला प्रश्न", "imported"))
        db.session.expire_all()
        decided = db.session.get(Suggestion, row.id)
        self.assertEqual(
            (decided.status, str(decided.decided_by), decided.decision_note),
            (SUGGESTION_REJECTED, self.base_project_pi_id, "no"),
        )

    def test_the_pending_count_follows_what_the_viewer_may_decide(self):
        first = self._pending_row()
        self._pending_row(item_key="another", seen_text=None)
        self._pending_row(project_id=OTHER_PROJECT, item_key="third", seen_text=None)
        self._login(self.base_admin_id)
        self.assertEqual(self.client.get(f"{API}/suggestions").get_json()["total"], 3)
        self._login(self.base_project_pi_id)
        queue = self.client.get(f"{API}/suggestions").get_json()
        self.assertEqual(queue["total"], 2)
        self.assertEqual({i["project_id"] for i in queue["items"]}, {self.BASE_PROJECT_ID})
        self.assertEqual(self.client.get(f"{API}/suggestions?limit=1").get_json()["limit"], 1)
        self.assertEqual(self._post(f"{API}/suggestions/{first.id}/reject").status_code, 200)
        self.assertEqual(self.client.get(f"{API}/suggestions").get_json()["total"], 1)

    # -- text safety, own suggestions, caps, locks ---------------------------

    def test_unsafe_text_is_refused_when_suggesting(self):
        english = svc.reference_items(INSTRUMENT)[("question", self.item_key, "label")]
        cases = {
            "unknown reference": "नाम ${not_in_english}",
            "malformed reference": "नाम ${oops",
            "foreign tag": "नाम <script>alert(1)</script>",
            "stray tag": "नाम <img src=x>",
            "javascript link": "[click](javascript:alert(1))",
            "NUL": "नाम\x00",
            "control character": "नाम\x07",
        }
        self.assertNotIn("<", english)  # fixture guard: the English has no markup
        for name, text in cases.items():
            with self.subTest(name):
                response = self._suggest(text=text)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.get_json()["code"], "invalid_translation")
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Suggestion)), 0)
        # Present first: ordinary text, a tab, a newline and an https link pass.
        ok = self._suggest(text="नाम\tदूसरा\nतीसरा [देखें](https://example.org/x)")
        self.assertEqual(ok.status_code, 201)

    def test_update_string_applies_the_same_checks(self):
        reference = svc.reference_items(INSTRUMENT)
        tagged = next(k for k, v in reference.items() if "<span" in v and k[0] == "question")
        _string("hi", tagged[1], "पुराना", field=tagged[2])
        db.session.commit()
        tag = svc._TAG_RE.findall(reference[tagged])[0]
        kwargs = dict(item_kind=tagged[0], item_key=tagged[1], field=tagged[2])
        with self.assertRaises(svc.InvalidTranslationText):
            svc.update_string(INSTRUMENT, "hi", text="<b>x</b>", **kwargs)
        with self.assertRaises(svc.InvalidTranslationText):
            svc.update_string(INSTRUMENT, "hi", text="${x}", **kwargs)
        # The English's own tag is allowed.
        result = svc.update_string(INSTRUMENT, "hi", text=f"{tag}नया</span>", **kwargs)
        self.assertEqual(result["source"], "edited")

    def test_the_admin_editor_answers_422_for_unsafe_text(self):
        self._login(self.base_admin_id)
        response = self.client.put(
            f"/admin/api/instrument-translations/{INSTRUMENT}/hi/strings",
            json={"item_kind": "question", "item_key": self.item_key, "field": "label",
                  "text": "[x](javascript:1)"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["code"], "invalid_translation")
        self.assertEqual(self._stored().text, "पहला प्रश्न")

    def test_a_pi_cannot_accept_their_own_suggestion_but_an_admin_can(self):
        pi_id = uuid.UUID(self.base_project_pi_id)
        mine = self._pending_row(suggested_by=pi_id)
        self._login(self.base_project_pi_id)
        response = self._post(f"{API}/suggestions/{mine.id}/accept")
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "own_suggestion"))
        self.assertEqual(self._stored().text, "पहला प्रश्न")
        # Present first: the same PI may still reject (withdraw) it.
        self.assertEqual(self._post(f"{API}/suggestions/{mine.id}/reject").status_code, 200)
        admin_id = uuid.UUID(self.base_admin_id)
        own = self._pending_row(suggested_by=admin_id)
        self._login(self.base_admin_id)
        self.assertEqual(self._post(f"{API}/suggestions/{own.id}/accept").status_code, 200)

    def test_pending_suggestions_are_capped_per_user(self):
        user = self.base_coder_id
        for i in range(50):
            db.session.add(Suggestion(
                instrument_code=INSTRUMENT, locale_code="hi", item_kind="question",
                item_key=f"cap{i}", field="label", proposed_text="x", reason="r",
                project_id=self.BASE_PROJECT_ID, suggested_by=uuid.UUID(user),
            ))
        db.session.commit()
        response = self._suggest(user)
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "too_many_pending"))
        # A decided suggestion frees a slot.
        first = db.session.scalars(sa.select(Suggestion).order_by(Suggestion.id)).first()
        self._login(self.base_admin_id)
        self.assertEqual(self._post(f"{API}/suggestions/{first.id}/reject").status_code, 200)
        self.assertEqual(self._suggest(user).status_code, 201)

    def test_an_instrument_without_a_reference_is_a_404(self):
        from unittest.mock import patch

        boom = svc.InstrumentTranslationError("no reference")
        self._login(self.base_coder_id)
        with patch.object(svc, "reference_items", side_effect=boom):
            self.assertEqual(
                self.client.get(f"{API}/{self.BASE_PROJECT_ID}/hi/questions").status_code, 404
            )
            self.assertEqual(self._suggest().status_code, 404)

    def test_accept_locks_the_string_before_checking_it(self):
        from unittest.mock import patch

        row = self._pending_row()
        self._login(self.base_admin_id)
        seen = []
        real_get = db.session.get

        def spy(model, ident, **kwargs):
            if model in (MapInstrumentTranslations, MasInstrumentLocales):
                seen.append((model.__name__, kwargs.get("with_for_update")))
            return real_get(model, ident, **kwargs)

        with patch.object(db.session, "get", side_effect=spy):
            self.assertEqual(self._post(f"{API}/suggestions/{row.id}/accept").status_code, 200)
        self.assertIn(("MapInstrumentTranslations", True), seen)
        self.assertIn(("MasInstrumentLocales", True), seen)
        # The lock is taken before update_string reads the same row unlocked.
        unlocked = [n for n, (m, lock) in enumerate(seen) if m == "MapInstrumentTranslations" and not lock]
        self.assertTrue(unlocked)  # present first: update_string did read it
        self.assertLess(seen.index(("MapInstrumentTranslations", True)), unlocked[0])

    # -- pages ---------------------------------------------------------------

    def test_the_page_and_the_admin_panel_carry_the_queue(self):
        self._login(self.base_coder_id)
        page = self.client.get("/questionnaire-translations")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Review suggestions", html)
        self.assertIn("Translations", self.client.get("/people-roles").get_data(as_text=True))
        self._login(self.base_admin_id)
        panel = self.client.get("/admin/panels/instrument-translations")
        self.assertEqual(panel.status_code, 200)
        self.assertIn("data-review-queue", panel.get_data(as_text=True))

    def test_the_page_needs_a_session(self):
        self.assertIn(self.client.get("/questionnaire-translations").status_code, (302, 401))
