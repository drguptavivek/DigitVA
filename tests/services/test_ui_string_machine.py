"""Machine candidates for missing UI strings (digitva-cqw9): client, job, serving, routes."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from app import db
from app.models.mas_ui_string_override import MasUiStringOverride
from app.services import machine_translation_service as azure
from app.services import ui_string_machine_job as job
from app.services import ui_string_service as svc
from tests.base import BaseTestCase
from tests.ui_string_fixtures import EN, HI, write_export


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


def fake_translate(texts, target):
    """Stand-in for Azure: prefix every text, keeping placeholders."""
    return [f"[{target}] {t}" for t in texts]


class Base(BaseTestCase):
    def setUp(self):
        super().setUp()
        self._old_dist = self.app.config.get("EXPO_CLIENT_DIST")
        self._tempdir = tempfile.TemporaryDirectory()
        self.app.config["EXPO_CLIENT_DIST"] = self._tempdir.name
        write_export(Path(self._tempdir.name), {"en": EN, "hi": HI})
        self.app.config.update(AZURE_TRANSLATOR_KEY="k", AZURE_TRANSLATOR_REGION="r")
        self.redis = FakeRedis()
        p = mock.patch.object(job, "_redis", return_value=self.redis)
        p.start()
        self.addCleanup(p.stop)
        self.actor = self.base_admin_user.user_id

    def tearDown(self):
        if self._old_dist is None:
            self.app.config.pop("EXPO_CLIENT_DIST", None)
        else:
            self.app.config["EXPO_CLIENT_DIST"] = self._old_dist
        self._tempdir.cleanup()
        db.session.rollback()
        super().tearDown()

    def run_job(self, **kw):
        with mock.patch.object(azure, "translate_batch", side_effect=fake_translate):
            return job.run(**kw)

    def row(self, locale, key):
        return db.session.get(MasUiStringOverride, (locale, key))


class JobTests(Base):
    def test_creates_machine_rows_only_for_missing_keys(self):
        status = self.run_job(locales=["hi"])
        self.assertEqual(status["results"]["hi"]["created"], 1)  # loginHelp only
        self.assertEqual(self.row("hi", "loginHelp").source, "machine")
        self.assertIsNone(self.row("hi", "navCoding"))

    def test_unshipped_allowed_locale_gets_every_key(self):
        status = self.run_job(locales=["pa"])
        self.assertEqual(status["results"]["pa"]["created"], len(EN))

    def test_never_overwrites_edited_or_existing_machine_rows(self):
        svc.set_override("hi", "loginHelp", "मेरा पाठ", self.actor)
        db.session.commit()
        self.run_job(locales=["hi"])
        self.assertEqual(self.row("hi", "loginHelp").text, "मेरा पाठ")
        self.assertEqual(self.row("hi", "loginHelp").source, "edited")

        db.session.delete(self.row("hi", "loginHelp"))
        db.session.add(MasUiStringOverride(
            locale_code="hi", string_key="loginHelp", text="पुराना", source="machine"))
        db.session.commit()
        second = self.run_job(locales=["hi"])
        self.assertEqual(second["results"]["hi"]["created"], 0)
        self.assertEqual(self.row("hi", "loginHelp").text, "पुराना")

    def test_rejects_candidates_that_change_placeholders(self):
        with mock.patch.object(azure, "translate_batch", return_value=["a", "b", "c", "भेजे {sent}"]):
            status = job.run(locales=["pa"])
        counts = status["results"]["pa"]
        self.assertEqual(counts["rejected"], 1)  # syncResult lost {failed}
        self.assertIsNone(self.row("pa", "syncResult"))

    def test_dry_run_calls_no_provider_and_writes_nothing(self):
        with mock.patch.object(azure, "translate_batch") as call:
            status = job.run(locales=["pa"], dry_run=True)
        call.assert_not_called()
        self.assertEqual(status["results"]["pa"]["would_create"], len(EN))
        self.assertIsNone(self.row("pa", "loginTitle"))

    def test_limit(self):
        status = self.run_job(locales=["pa"], limit=2)
        self.assertEqual(status["results"]["pa"]["created"], 2)

    def test_lock_refuses_a_second_run_and_is_released(self):
        self.redis.set(job.LOCK_KEY, "someone", nx=True)
        with self.assertRaises(job.AlreadyRunning):
            self.run_job(locales=["hi"])
        self.redis.delete(job.LOCK_KEY)
        self.run_job(locales=["hi"])
        self.assertFalse(self.redis.exists(job.LOCK_KEY))
        self.assertEqual(job.last_run()["state"], "done")

    def test_not_configured(self):
        self.app.config["AZURE_TRANSLATOR_KEY"] = ""
        with self.assertRaises(azure.NotConfigured):
            job.run(locales=["hi"])

    def test_provider_error_is_counted_per_locale(self):
        with mock.patch.object(azure, "translate_batch", side_effect=azure.MachineTranslationError("down")):
            status = job.run(locales=["hi"])
        self.assertEqual(status["results"]["hi"]["errors"], 1)

    def test_locale_outside_allow_list_refused(self):
        with self.assertRaises(svc.UiStringError):
            job.run(locales=["fr"])


class ServingTests(Base):
    def test_machine_rows_are_not_served_or_exported_until_accepted(self):
        self.run_job(locales=["hi"])
        self.assertEqual(svc.overrides("hi")["strings"], {})
        self.assertNotIn("loginHelp", svc.export("hi"))
        before = svc.overrides("hi")["version"]

        svc.accept("hi", "loginHelp", self.actor)
        self.assertIn("loginHelp", svc.overrides("hi")["strings"])
        self.assertIn("loginHelp", svc.export("hi"))
        self.assertNotEqual(svc.overrides("hi")["version"], before)
        self.assertEqual(self.row("hi", "loginHelp").updated_by, self.actor)

    def test_accept_refuses_a_non_machine_row(self):
        with self.assertRaises(svc.UiStringError):
            svc.accept("hi", "navCoding", self.actor)

    def test_status_and_edit(self):
        self.run_job(locales=["hi"])
        data = svc.strings_for_admin("hi", "machine")
        self.assertEqual([r["key"] for r in data["rows"]], ["loginHelp"])
        self.assertEqual(data["counts"]["machine"], 1)
        svc.set_override("hi", "loginHelp", "संपादित", self.actor)
        self.assertEqual(self.row("hi", "loginHelp").source, "edited")

    def test_unshipped_allowed_locale_is_editable_but_others_are_not(self):
        svc.set_override("pa", "loginTitle", "ਸਾਈਨ ਇਨ", self.actor)
        with self.assertRaises(svc.UiStringError):
            svc.set_override("fr", "loginTitle", "x", self.actor)


class ClientTests(Base):
    def test_mask_round_trip(self):
        text = "Sent {sent} of ${total} & {failed} <ok>"
        masked = azure.mask(text)
        self.assertEqual(masked.count("notranslate"), 3)
        self.assertEqual(azure.unmask(masked), text)

    def test_translate_batch_masks_and_restores(self):
        seen = {}

        def post(url, headers, json, timeout):
            seen.update(url=url, headers=headers, body=json)
            return mock.Mock(status_code=200, json=lambda: [
                {"translations": [{"text": t["Text"]}]} for t in json])

        with mock.patch.object(requests, "post", side_effect=post):
            out = azure.translate_batch(["Sent {sent}, {failed}.", "{count} items"], "hi")
        self.assertEqual(out, ["Sent {sent}, {failed}.", "{count} items"])
        self.assertIn("to=hi", seen["url"])
        self.assertEqual(seen["headers"]["Ocp-Apim-Subscription-Key"], "k")
        self.assertIn('class="notranslate"', seen["body"][0]["Text"])

    def test_batches_by_item_count(self):
        calls = []

        def post(url, headers, json, timeout):
            calls.append(len(json))
            return mock.Mock(status_code=200, json=lambda: [
                {"translations": [{"text": "x"}]} for _ in json])

        with mock.patch.object(requests, "post", side_effect=post):
            azure.translate_batch(["a"] * 1001, "hi")
        self.assertEqual(calls, [1000, 1])

    def test_batches_by_characters(self):
        chunks = list(azure._chunks(["a" * 30_000, "b" * 30_000]))
        self.assertEqual(len(chunks), 2)

    def test_retries_429_then_succeeds(self):
        responses = [
            mock.Mock(status_code=429, headers={"Retry-After": "2"}),
            requests.ConnectionError("boom"),
            mock.Mock(status_code=200, json=lambda: [{"translations": [{"text": "ok"}]}]),
        ]
        sleeps = []
        with mock.patch.object(requests, "post", side_effect=responses), \
                mock.patch.object(azure, "_sleep", sleeps.append):
            self.assertEqual(azure.translate_batch(["a"], "hi"), ["ok"])
        self.assertEqual(sleeps, [2.0, 2])

    def test_gives_up_and_does_not_leak_the_key(self):
        with mock.patch.object(requests, "post", return_value=mock.Mock(status_code=503, headers={})), \
                mock.patch.object(azure, "_sleep"):
            with self.assertRaises(azure.MachineTranslationError) as ctx:
                azure.translate_batch(["a"], "hi")
        self.assertNotIn("Subscription", str(ctx.exception))

    def test_client_error_is_not_retried(self):
        with mock.patch.object(requests, "post", return_value=mock.Mock(status_code=401, headers={})) as post:
            with self.assertRaises(azure.MachineTranslationError):
                azure.translate_batch(["a"], "hi")
        self.assertEqual(post.call_count, 1)

    def test_not_configured(self):
        self.app.config["AZURE_TRANSLATOR_REGION"] = ""
        with self.assertRaises(azure.NotConfigured):
            azure.translate_batch(["a"], "hi")


class RouteTests(Base):
    RUN = "/admin/api/ui-strings/machine-translate"
    ACCEPT = "/admin/api/ui-strings/hi/accept"

    def test_admin_only_and_csrf(self):
        self._login(self.base_coder_id)
        h = self._csrf_headers()
        self.assertEqual(self.client.post(self.RUN, json={}, headers=h).status_code, 403)
        self.assertEqual(self.client.post(self.ACCEPT, json={"key": "k"}, headers=h).status_code, 403)
        self._login(self.base_admin_id)
        self.assertEqual(self.client.post(self.RUN, json={}).status_code, 400)
        self.assertEqual(self.client.post(self.ACCEPT, json={"key": "loginHelp"}).status_code, 400)

    def test_run_queues_the_task(self):
        self._login(self.base_admin_id)
        with mock.patch("app.tasks.ui_string_tasks.machine_translate_ui_strings.delay") as delay:
            r = self.client.post(self.RUN, json={"locales": ["hi"]}, headers=self._csrf_headers())
        self.assertEqual(r.status_code, 202)
        delay.assert_called_once_with(["hi"])

    def test_run_refusals(self):
        self._login(self.base_admin_id)
        h = self._csrf_headers()
        self.assertEqual(self.client.post(self.RUN, json={"locales": ["fr"]}, headers=h).status_code, 400)
        self.redis.set(job.LOCK_KEY, "x")
        self.assertEqual(self.client.post(self.RUN, json={}, headers=h).status_code, 409)
        self.redis.delete(job.LOCK_KEY)
        self.app.config["AZURE_TRANSLATOR_KEY"] = ""
        r = self.client.post(self.RUN, json={}, headers=h)
        self.assertEqual(r.status_code, 409)
        self.assertIn("not configured", r.get_json()["error"])

    def test_accept_route_and_panel(self):
        self.run_job(locales=["hi"])
        db.session.commit()
        self._login(self.base_admin_id)
        panel = self.client.get("/admin/panels/ui-strings", query_string={"locale": "hi", "status": "machine"})
        body = panel.get_data(as_text=True)
        self.assertIn("uis-accept-btn", body)
        self.assertIn("[hi] Use the existing sign-in.", body)
        r = self.client.post(self.ACCEPT, json={"key": "loginHelp"}, headers=self._csrf_headers())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "corrected")
        self.assertEqual(self.client.post(
            self.ACCEPT, json={"key": "loginHelp"}, headers=self._csrf_headers()).status_code, 400)

    def test_panel_says_not_configured(self):
        self.app.config["AZURE_TRANSLATOR_KEY"] = ""
        self._login(self.base_admin_id)
        body = self.client.get("/admin/panels/ui-strings", query_string={"locale": "hi"}).get_data(as_text=True)
        self.assertIn("Not configured", body)

    def test_public_api_serves_edited_rows_of_allowed_unshipped_locale_only(self):
        svc.set_override("pa", "loginTitle", "ਸਾਈਨ ਇਨ", self.actor)
        self.run_job(locales=["pa"])
        db.session.commit()
        r = self.client.get("/api/v1/ui-strings/pa")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(r.get_json()["strings"]), ["loginTitle"])
        self.assertEqual(self.client.get("/api/v1/ui-strings/fr").status_code, 404)


if __name__ == "__main__":
    unittest.main()
