"""app/services/served_form_service.py filters the composed definition
(app/data/who-va-2022.composed.json, tooling/who-va-2022/
build-composed-instrument.mjs) by a project's enabled extensions. The build
itself proves the filter equals the package's composer for all 32 subsets; this
pins the Python half of the rule against the committed file. No database.
"""
import hashlib
import json
import unittest

from app.services import served_form_service as svc

CONDITIONAL = {"social_autopsy", "narration_language", "death_summary", "medical_records", "abha"}


def _names(items):
    return [item["name"] for item in items]


class ComposedFileTests(unittest.TestCase):
    def test_version_and_engine_version(self):
        composed = svc.composed_definition()
        self.assertRegex(composed["version"], r"^\d+-[0-9a-f]{10}$")
        self.assertEqual(svc.composed_version(), composed["version"])
        self.assertEqual(composed["engineVersion"], 1)

    def test_every_tag_is_a_known_conditional_extension(self):
        composed = svc.composed_definition()
        tags = {t for kind in ("sections", "questions") for i in composed[kind] for t in i.get("extensions", ())}
        # Present first: all five layers contribute something.
        self.assertEqual(tags, CONDITIONAL)
        self.assertEqual(svc._tag_vocabulary(), frozenset(CONDITIONAL))


class FilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.composed = svc.composed_definition()

    def _filter(self, *enabled):
        return svc.filter_definition(self.composed, enabled)

    def test_nothing_enabled_drops_every_tagged_item_and_keeps_the_rest_in_order(self):
        tagged = {i["name"] for k in ("sections", "questions") for i in self.composed[k] if "extensions" in i}
        self.assertGreater(len(tagged), 0)
        out = self._filter()
        for kind in ("sections", "questions"):
            expected = [i["name"] for i in self.composed[kind] if "extensions" not in i]
            self.assertEqual(_names(out[kind]), expected)
        self.assertNotIn("md_available", _names(out["questions"]))
        # Always-on content stays.
        self.assertIn("consent_mode", _names(out["questions"]))
        self.assertIn("interview_outcome", _names(out["questions"]))

    def test_one_layer_adds_exactly_its_own_items(self):
        base = set(_names(self._filter()["questions"]))
        social = set(_names(self._filter("social_autopsy")["questions"]))
        added = social - base
        self.assertEqual(
            added,
            {q["name"] for q in self.composed["questions"] if q.get("extensions") == ["social_autopsy"]},
        )
        self.assertGreater(len(added), 0)
        self.assertNotIn("md_available", social)

    def test_the_shared_documents_section_follows_either_of_its_layers(self):
        has = lambda *e: "digitva_documents" in _names(self._filter(*e)["sections"])  # noqa: E731
        self.assertFalse(has())
        self.assertTrue(has("medical_records"))
        self.assertTrue(has("death_summary"))
        self.assertTrue(has("medical_records", "death_summary"))
        self.assertTrue(has("abha", "death_summary"))
        self.assertFalse(has("abha", "narration_language"))

    def test_a_combination_keeps_composed_order(self):
        out = self._filter("abha", "medical_records")
        composed_pos = {n: i for i, n in enumerate(_names(self.composed["questions"]))}
        positions = [composed_pos[n] for n in _names(out["questions"])]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("abha_number", _names(out["questions"]))
        self.assertIn("md_im30", _names(out["questions"]))
        self.assertNotIn("ds_available", _names(out["questions"]))

    def test_tags_are_not_in_the_served_items(self):
        out = self._filter("social_autopsy", "abha")
        self.assertTrue(all("extensions" not in i for k in ("sections", "questions") for i in out[k]))


class ServedDefinitionTests(unittest.TestCase):
    def test_bytes_match_the_filter_and_the_sha_is_of_the_bytes(self):
        served = svc.served_definition(["digitva_core", "abha"])
        self.assertEqual(hashlib.sha256(served.body).hexdigest(), served.sha256)
        body = json.loads(served.body)
        self.assertEqual(body["version"], svc.composed_version())
        self.assertEqual(body["engineVersion"], 1)
        self.assertNotIn("sha256", body)
        expected = svc.filter_definition(svc.composed_definition(), {"abha"})
        self.assertEqual(body, json.loads(json.dumps(expected)))

    def test_one_serialization_per_distinct_set_of_conditional_extensions(self):
        a = svc.served_definition(["digitva_core", "abha", "geography"])
        b = svc.served_definition(["abha", "intake_screen", "doris_support_whova_2022"])
        self.assertIs(a, b)
        self.assertIsNot(a, svc.served_definition(["abha", "social_autopsy"]))
        self.assertNotEqual(a.sha256, svc.served_definition([]).sha256)

    def test_version_is_the_same_for_every_slice_and_the_sha_differs(self):
        self.assertEqual(svc.served_definition([]).version, svc.served_definition(CONDITIONAL).version)
        self.assertEqual(svc.served_definition(CONDITIONAL).version, svc.composed_version())
        self.assertNotEqual(svc.served_definition([]).sha256, svc.served_definition(CONDITIONAL).sha256)


if __name__ == "__main__":
    unittest.main()
