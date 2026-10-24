"""Machine drafts of missing questionnaire translations (digitva-m2ve)."""
from datetime import UTC, datetime
from unittest import mock

import requests

from app import db
from app.models.map_instrument_translation_suggestions import (
    MapInstrumentTranslationSuggestions as Suggestion,
)
from app.models.mas_instrument_locales import MapInstrumentTranslations, MasInstrumentLocales
from app.services import instrument_translation_machine_job as job
from app.services import instrument_translation_service as svc
from app.services import machine_translation_service as azure
from tests.base import BaseTestCase

INSTRUMENT = "WHO_2022_VA"
Q = "question"
REFERENCE = {
    (Q, "a_new", "label"): "What is the name?",
    (Q, "b_held", "label"): "Held label",
    (Q, "c_sugg", "label"): "Suggested label",
    (Q, "d_ref", "label"): "Hello ${name}",
    (Q, "e_tag", "guidance_hint"): 'Note <span style="color:red">careful</span>',
    (Q, "f_empty", "label"): "  ",
}


class FakeRedis:
    def __init__(self):
        self.data = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)

    def exists(self, key):
        return key in self.data


def echo(texts, target):
    return [f"[{target}] {t}" for t in texts]


class Base(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.app.config.update(AZURE_TRANSLATOR_KEY="k", AZURE_TRANSLATOR_REGION="r")
        self.redis = FakeRedis()
        for patcher in (
            mock.patch.object(job.ui_job, "_redis", return_value=self.redis),
            mock.patch.object(job, "reference_items", return_value=REFERENCE),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        for code in ("hi", "ta"):
            if db.session.get(MasInstrumentLocales, (INSTRUMENT, code)) is None:
                db.session.add(MasInstrumentLocales(
                    instrument_code=INSTRUMENT, locale_code=code, language_name=code,
                    version=3, updated_at=datetime.now(UTC),
                ))
        db.session.add(MapInstrumentTranslations(
            instrument_code=INSTRUMENT, locale_code="hi", item_kind=Q, item_key="b_held",
            field="label", text="मौजूद", source="edited", updated_at=datetime.now(UTC),
        ))
        db.session.add(Suggestion(
            instrument_code=INSTRUMENT, locale_code="hi", item_kind=Q, item_key="c_sugg",
            field="label", proposed_text="सुझाव", reason="r",
            project_id=self.BASE_PROJECT_ID, suggested_by=self.base_coder_user.user_id,
        ))
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        super().tearDown()

    def run_job(self, fake=echo, **kw):
        with mock.patch.object(azure, "translate_batch", side_effect=fake) as m:
            status = job.run(**kw)
        self.mock = m
        return status

    def row(self, locale, key, field="label"):
        return db.session.get(MapInstrumentTranslations, (INSTRUMENT, locale, Q, key, field))


class JobTests(Base):
    def test_only_missing_items_are_drafted_and_the_rest_untouched(self):
        status = self.run_job(locales=["hi"])
        self.assertEqual(status["results"]["hi"]["created"], 3)
        self.assertEqual(self.row("hi", "a_new").source, "machine")
        self.assertEqual(self.row("hi", "b_held").text, "मौजूद")
        self.assertEqual(self.row("hi", "b_held").source, "edited")
        self.assertIsNone(self.row("hi", "c_sugg"))  # pending suggestion
        self.assertIsNone(self.row("hi", "f_empty"))  # empty English
        sent = self.mock.call_args.args[0]
        self.assertEqual(sorted(sent), sorted([
            "What is the name?", "Hello ${name}", 'Note <span style="color:red">careful</span>',
        ]))

    def test_second_run_creates_nothing_and_default_uses_existing_locales(self):
        status = self.run_job()
        self.assertEqual(sorted(status["results"]), ["hi", "ta"])
        again = self.run_job()
        self.assertEqual(again["results"]["hi"]["created"], 0)

    def test_placeholder_or_markup_mismatch_is_rejected(self):
        def bad(texts, target):
            return [t.replace("${name}", "${other}").replace("<span", "<b").replace("</span>", "</b>")
                    for t in texts]
        status = self.run_job(fake=bad, locales=["hi"])
        counts = status["results"]["hi"]
        self.assertEqual((counts["created"], counts["rejected"]), (1, 2))
        self.assertIsNone(self.row("hi", "d_ref"))
        self.assertIsNone(self.row("hi", "e_tag", "guidance_hint"))

    def test_dropped_placeholder_is_rejected(self):
        status = self.run_job(fake=lambda t, _: [x.replace("${name}", "") for x in t], locales=["hi"])
        self.assertIsNone(self.row("hi", "d_ref"))
        self.assertEqual(status["results"]["hi"]["rejected"], 1)

    def test_dry_run_calls_no_provider_and_writes_nothing(self):
        self.app.config["AZURE_TRANSLATOR_KEY"] = ""
        with mock.patch.object(azure, "translate_batch") as m:
            status = job.run(locales=["hi"], dry_run=True)
        m.assert_not_called()
        self.assertEqual(status["results"]["hi"]["would_create"], 3)
        self.assertIsNone(self.row("hi", "a_new"))

    def test_not_configured_is_a_clear_error(self):
        self.app.config["AZURE_TRANSLATOR_KEY"] = ""
        with self.assertRaisesRegex(azure.NotConfigured, "not configured"):
            job.run(locales=["hi"])

    def test_lock_prevents_a_concurrent_run(self):
        self.redis.set(job.LOCK_KEY, "x")
        with self.assertRaises(job.AlreadyRunning):
            self.run_job(locales=["hi"])

    def test_lock_released_and_last_run_recorded(self):
        self.run_job(locales=["hi"])
        self.assertFalse(job.is_running())
        self.assertEqual(job.last_run()["results"]["hi"]["created"], 3)

    def test_limit_and_provider_failure(self):
        self.assertEqual(self.run_job(locales=["hi"], limit=1)["results"]["hi"]["created"], 1)

        def boom(texts, target):
            raise azure.MachineTranslationError("down")
        status = self.run_job(fake=boom, locales=["hi"])
        self.assertEqual(status["results"]["hi"]["errors"], 1)

    def test_unknown_locale_and_unseeded_locale(self):
        with self.assertRaises(svc.InstrumentTranslationError):
            job.run(locales=["fr"])
        status = self.run_job(locales=["kn"])  # machine language, no locale row
        self.assertEqual(status["results"]["kn"]["errors"], 1)

    def test_batching_splits_big_requests(self):
        posted = []

        def fake_post(url, headers, body):
            posted.append(len(body))
            return [{"translations": [{"text": b["Text"]}]} for b in body]
        with mock.patch.object(azure, "MAX_ITEMS", 2), mock.patch.object(azure, "_post", side_effect=fake_post):
            job.run(locales=["hi"])
        self.assertEqual(posted, [2, 1])

    def test_retry_on_429(self):
        calls = []

        def post(*a, **k):
            calls.append(1)
            r = mock.Mock(status_code=429 if len(calls) == 1 else 200, headers={})
            r.json.return_value = [{"translations": [{"text": "x"}]}]
            return r
        with mock.patch.object(azure.requests, "post", side_effect=post), \
                mock.patch.object(azure, "_sleep"):
            self.assertEqual(azure.translate_batch(["a"], "hi"), ["x"])
        self.assertEqual(len(calls), 2)

    def test_tags_are_shielded(self):
        masked = azure.mask('A <span style="x">b</span> ${n}')
        self.assertEqual(azure.unmask(masked), 'A <span style="x">b</span> ${n}')
        self.assertIn('<span class="notranslate"><span style="x"></span>', masked)


class ServingAndRoutesTests(Base):
    def test_drafts_not_served_until_accepted(self):
        self.run_job(locales=["hi"])
        db.session.commit()
        self.assertNotIn("a_new", svc.export_translations(INSTRUMENT, "hi")["questions"])
        self._login(self.base_admin_id)
        r = self.client.post(
            f"/admin/api/instrument-translations/{INSTRUMENT}/hi/strings/accept",
            json={"item_kind": Q, "item_key": "a_new", "field": "label"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(r.status_code, 200)
        served = svc.export_translations(INSTRUMENT, "hi")["questions"]
        self.assertEqual(served["a_new"]["label"], "[hi] What is the name?")

    def test_admin_only_csrf_and_status(self):
        url = "/admin/api/instrument-translations/machine-translate"
        self._login(self.base_coder_id)
        self.assertEqual(self.client.post(url, json={}, headers=self._csrf_headers()).status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 403)
        self._login(self.base_admin_id)
        self.assertEqual(self.client.post(url, json={}).status_code, 400)  # no CSRF token
        status = self.client.get(url).get_json()
        self.assertTrue(status["configured"])
        self.assertFalse(status["running"])

    def test_queue_and_refusals(self):
        url = "/admin/api/instrument-translations/machine-translate"
        self._login(self.base_admin_id)
        h = self._csrf_headers()
        with mock.patch("app.tasks.instrument_translation_tasks.machine_translate_instrument.delay") as delay:
            r = self.client.post(url, json={"locales": ["hi"]}, headers=h)
        self.assertEqual(r.status_code, 202)
        delay.assert_called_once_with(["hi"])
        self.assertEqual(self.client.post(url, json={"locales": ["fr"]}, headers=h).status_code, 400)
        self.redis.set(job.LOCK_KEY, "x")
        self.assertEqual(self.client.post(url, json={}, headers=h).status_code, 409)
        self.redis.delete(job.LOCK_KEY)
        self.app.config["AZURE_TRANSLATOR_KEY"] = ""
        r = self.client.post(url, json={}, headers=h)
        self.assertEqual(r.status_code, 409)
        self.assertIn("not configured", r.get_json()["error"])

    def test_panel_carries_the_clinician_caution(self):
        self._login(self.base_admin_id)
        body = self.client.get("/admin/panels/instrument-translations").get_data(as_text=True)
        self.assertIn("must be checked by a clinician-translator before accepting", body)
