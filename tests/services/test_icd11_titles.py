"""ICD-11 title lookups for the one-click coding choices (WHO API only, never mas_icd11_mms)."""

from unittest.mock import patch

from app.services.icd11_titles import (
    icd11_alternatives_label,
    icd11_label,
    icd11_title,
    stored_cod_label,
)
from app.services.who_icd_api import WhoIcdApiUnavailable
from tests.base import BaseTestCase


class _FakeCache:
    """Stands in for the Flask cache so no Redis is needed."""

    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, timeout=None):
        self.values[key] = value


def _codeinfo(titles):
    """A fake get_icd11_codeinfo that answers from ``titles`` and returns None for other codes."""

    def lookup(code, release=None):
        if code not in titles:
            return None
        return {"code": code, "title": titles[code]}

    return lookup


class Icd11TitlesTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.cache = _FakeCache()
        self.cache_patch = patch("app.services.icd11_titles.cache", self.cache)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def _in_request(self):
        # g lives on the app context, so each test gets its own "request".
        return self.app.app_context()

    def test_a_code_gets_its_who_title_with_markup_removed(self):
        with self._in_request(), patch(
            "app.services.icd11_titles.get_icd11_codeinfo",
            side_effect=_codeinfo({"CA40": "<em>Pneumonia</em>"}),
        ):
            self.assertEqual(icd11_title("CA40"), "Pneumonia")
            self.assertEqual(icd11_label("CA40"), "CA40 — Pneumonia")

    def test_codeinfo_without_a_title_takes_the_title_of_its_stem_entity(self):
        """The live codeinfo carries only code and stemId; the title is on the stem entity (as _codeinfo_item reads it)."""
        codeinfo = {"code": "CA40", "stemId": "http://id.who.int/icd/release/11/2026-01/mms/1"}
        entity = patch("app.services.icd11_titles.proxy_who_icd_request")
        with self._in_request(), patch(
            "app.services.icd11_titles.get_icd11_codeinfo", return_value=codeinfo
        ), entity as proxied:
            proxied.return_value.status_code = 200
            proxied.return_value.json.return_value = {"title": "<em>Pneumonia</em>"}
            self.assertEqual(icd11_title("CA40"), "Pneumonia")
            proxied.assert_called_once_with("icd/release/11/2026-01/mms/1")

    def test_a_postcoordinated_expression_joins_stem_then_extension_titles(self):
        titles = {"PA78": "Fall on same level", "XE9H6": "Extension title"}
        with self._in_request(), patch(
            "app.services.icd11_titles.get_icd11_codeinfo", side_effect=_codeinfo(titles)
        ):
            self.assertEqual(icd11_title("PA78&XE9H6"), "Fall on same level + Extension title")

    def test_a_code_WHO_does_not_know_gets_no_title_and_its_code_alone(self):
        with self._in_request(), patch(
            "app.services.icd11_titles.get_icd11_codeinfo", side_effect=_codeinfo({})
        ):
            self.assertIsNone(icd11_title("ZZ99"))
            self.assertEqual(icd11_label("ZZ99"), "ZZ99")

    def test_an_unavailable_WHO_API_shows_codes_only_and_is_asked_once_per_request(self):
        lookup = patch(
            "app.services.icd11_titles.get_icd11_codeinfo",
            side_effect=WhoIcdApiUnavailable("down"),
        )
        with self._in_request(), lookup as mocked:
            self.assertEqual(icd11_label("CA40"), "CA40")
            self.assertEqual(icd11_label("PA78&XE9H6"), "PA78&XE9H6")
            self.assertEqual(mocked.call_count, 1)

    def test_an_outage_is_remembered_across_requests_for_a_minute(self):
        down = patch(
            "app.services.icd11_titles.get_icd11_codeinfo",
            side_effect=WhoIcdApiUnavailable("down"),
        )
        with self._in_request(), down as first:
            self.assertEqual(icd11_label("CA40"), "CA40")
        self.assertEqual(first.call_count, 1)
        # A later request (another worker, same Redis) does not wait on WHO again.
        with self._in_request(), patch(
            "app.services.icd11_titles.get_icd11_codeinfo",
            side_effect=_codeinfo({"CA40": "Pneumonia"}),
        ) as later:
            self.assertEqual(icd11_label("CA40"), "CA40")
        self.assertEqual(later.call_count, 0)

    def test_a_failed_stem_lookup_is_not_cached_as_no_such_code(self):
        codeinfo = {"code": "CA40", "stemId": "http://id.who.int/icd/release/11/2026-01/mms/1"}
        with self._in_request(), patch(
            "app.services.icd11_titles.get_icd11_codeinfo", return_value=codeinfo
        ), patch("app.services.icd11_titles.proxy_who_icd_request") as proxied:
            proxied.return_value.status_code = 400
            self.assertIsNone(icd11_title("CA40"))
        self.assertNotIn("icd11_title:2026-01:CA40", self.cache.values)

    def test_a_title_is_cached_so_a_repeat_costs_no_WHO_call(self):
        with self._in_request(), patch(
            "app.services.icd11_titles.get_icd11_codeinfo",
            side_effect=_codeinfo({"CA40": "Pneumonia"}),
        ) as mocked:
            icd11_title("CA40")
        with self._in_request(), patch(
            "app.services.icd11_titles.get_icd11_codeinfo",
            side_effect=_codeinfo({"CA40": "Pneumonia"}),
        ) as again:
            self.assertEqual(icd11_title("CA40"), "Pneumonia")
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(again.call_count, 0)

    def test_a_stored_cause_shows_its_code_with_title_and_plain_text_is_left_alone(self):
        with self._in_request(), patch(
            "app.services.icd11_titles.get_icd11_codeinfo",
            side_effect=_codeinfo({"CA40": "Pneumonia"}),
        ):
            self.assertEqual(stored_cod_label("CA40 Pneumonia"), "CA40 — Pneumonia")
        with self._in_request(), patch("app.services.icd11_titles.get_icd11_codeinfo") as mocked:
            self.assertEqual(stored_cod_label("Pneumonia"), "Pneumonia")
            self.assertEqual(stored_cod_label(None), "")
            mocked.assert_not_called()

    def test_a_stored_cause_keeps_its_own_title_when_WHO_gives_none(self):
        with self._in_request(), patch(
            "app.services.icd11_titles.get_icd11_codeinfo",
            side_effect=WhoIcdApiUnavailable("down"),
        ):
            self.assertEqual(stored_cod_label("1C62.Z HIV disease"), "1C62.Z HIV disease")

    def test_alternative_targets_are_labelled_one_by_one(self):
        with self._in_request(), patch(
            "app.services.icd11_titles.get_icd11_codeinfo",
            side_effect=_codeinfo({"1B10.1": "Tuberculosis", "1B10.2": "Other TB"}),
        ):
            self.assertEqual(icd11_alternatives_label("1B10.1/1B10.2"), "1B10.1 — Tuberculosis / 1B10.2 — Other TB")
            self.assertIsNone(icd11_alternatives_label(None))


class MaskedStep2SmartvaQuickUseTests(BaseTestCase):
    def test_the_smartva_quick_use_carries_the_title_cause_and_likelihood(self):
        from types import SimpleNamespace

        from app.services.doris_context_service import masked_step2_context

        smartva = SimpleNamespace(
            va_smartva_cause1="TB",
            va_smartva_likelihood1="somewhat likely",
            va_smartva_cause1icd="A15",
        )
        cache = _FakeCache()
        with patch("app.services.icd11_titles.cache", cache), patch(
            "app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1B10.1"
        ), patch("app.services.doris_context_service.smartva_icd11_mapping", return_value="1B10.1"), patch(
            "app.services.icd11_titles.get_icd11_codeinfo",
            side_effect=_codeinfo({"1B10.1": "Tuberculosis"}),
        ), self.app.app_context():
            context = masked_step2_context(None, smartva, redact_pii=False)
        self.assertEqual(context["smartva_icd11_alternatives"], ["1B10.1"])
        self.assertEqual(context["smartva_icd11_label"], "1B10.1 — Tuberculosis")
        self.assertEqual(context["smartva_cause_text"], "TB, somewhat likely")

    def test_no_smartva_result_gives_no_quick_use_label(self):
        from app.services.doris_context_service import masked_step2_context

        with self.app.app_context():
            context = masked_step2_context(None, None, redact_pii=False)
        self.assertEqual(context["smartva_icd11_alternatives"], [])
        self.assertIsNone(context["smartva_icd11_label"])
        self.assertIsNone(context["smartva_cause_text"])
