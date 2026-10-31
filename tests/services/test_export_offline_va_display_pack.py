"""The offline VA display pack and golden renders (scripts/export_offline_va_display_pack.py,
scripts/export_offline_va_display_golden.py) and their drift guards.

Collect Plus offline coding builds the coding workspace from the committed pack and checks its renders against
the committed golden file. These tests fail when either file differs from what the database at head and the
server's render functions produce, and they pin the server rule the phone mirrors: a list answer renders as its
space-joined string would.
"""

import json

from app.services.category_rendering_service import clear_category_rendering_cache
from app.services.migrations.migrate_who_2022_va import Who2022VaMigrator
from app.utils.va_preprocess.va_preprocess_02_summcatenotification import (
    va_preprocess_summcatenotification,
)
from app.utils.va_render.va_render_06_processcategorydata import va_render_processcategorydata
from scripts.export_offline_va_display_golden import FORM_ID, INPUTS, build_golden, dump_golden
from scripts.export_offline_va_display_golden import OUTPUT as GOLDEN_OUTPUT
from scripts.export_offline_va_display_pack import (
    HASHED_FIELDS,
    OUTPUT,
    SCHEMA,
    build_pack,
    compact_sha256,
)
from tests.base import BaseTestCase


def _committed_pack() -> dict:
    return json.loads(OUTPUT.read_text(encoding="utf-8"))


def _render(answers: dict, field_id: str, choices: dict) -> dict:
    """The rendered subcategory of one field, as ``{label: value}``."""
    datalevel = {"cat": {"sub": {field_id: "Label"}}}
    return va_render_processcategorydata(answers, FORM_ID, datalevel, choices, "cat")["sub"]


class CommittedDisplayPackTests(BaseTestCase):
    def test_committed_pack_is_internally_consistent(self):
        pack = _committed_pack()
        self.assertEqual((pack["schema"], pack["form_type_code"]), (SCHEMA, "WHO_2022_VA"))
        self.assertEqual(pack["content_sha256"], compact_sha256({key: pack[key] for key in HASHED_FIELDS}))
        self.assertEqual(list(pack)[: len(HASHED_FIELDS)], list(HASHED_FIELDS))
        self.assertNotIn("db_revision", HASHED_FIELDS)
        nav = [category["code"] for category in pack["categories"]]
        self.assertEqual(nav[-1], "vacodassessment")
        self.assertTrue({"vanarrationanddocuments", "vahealthhistorydetails"} <= {code for code, _ in pack["datalevel"]})
        self.assertEqual([code for code, _ in pack["datalevel"]], [code for code, _ in pack["subcategories"]])
        # Visibility follows the DB mapping, which differs from the coder datalevel: skin rash is not a general symptom there.
        visibility = dict(pack["visibility"])
        self.assertIn("Id10233", visibility["vaskinmucosalsymptoms"])
        self.assertNotIn("Id10233", visibility["vageneralsymptoms"])
        self.assertIn("Id10233", {field for _, subs in dict(pack["datalevel"])["vageneralsymptoms"] for field, _ in subs})

    def test_committed_golden_names_the_committed_pack_and_every_input_case(self):
        golden = json.loads(GOLDEN_OUTPUT.read_text(encoding="utf-8"))
        inputs = json.loads(INPUTS.read_text(encoding="utf-8"))["cases"]
        self.assertEqual(golden["pack_sha256"], _committed_pack()["content_sha256"])
        self.assertEqual([case["name"] for case in golden["cases"]], [case["name"] for case in inputs])
        self.assertEqual([case["data"] for case in golden["cases"]], [case["data"] for case in inputs])


class DisplayPackDriftTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mapping_loaded = bool(Who2022VaMigrator().run())

    @classmethod
    def tearDownClass(cls):
        # The seeded mapping is rolled back with the class; the process-wide caches must not outlive it.
        clear_category_rendering_cache()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        if not self.mapping_loaded:
            self.skipTest("The WHO_2022_VA field mapping cannot be loaded in this database.")

    def test_committed_pack_equals_the_database(self):
        """Fails after a mapping change until the pack is regenerated:
        docker compose exec -T minerva_app_service uv run --no-sync python scripts/export_offline_va_display_pack.py"""
        built, committed = build_pack(), _committed_pack()
        # The revision differs by checkout; the content hash is what ties the pack to the data.
        built.pop("db_revision"), committed.pop("db_revision")
        self.assertEqual(committed, built)

    def test_committed_golden_equals_a_regeneration(self):
        """Fails after a pack, render or relevance change until the golden file is regenerated:
        docker compose exec -T minerva_app_service uv run --no-sync python scripts/export_offline_va_display_golden.py"""
        self.assertEqual(GOLDEN_OUTPUT.read_text(encoding="utf-8"), dump_golden(build_golden()))

    def test_golden_covers_the_rules_the_phone_mirrors(self):
        cases = {case["name"]: case for case in build_golden()["cases"]}
        self.assertGreaterEqual(len(cases), 12)
        items = {
            case_name: {
                item["label"]: item["value"]
                for payload in case["category_payloads"]
                for sub in payload["subcategories"]
                for item in sub["items"]
            }
            for case_name, case in cases.items()
        }
        # Subject present before absent: the answer is in the input, then stripped by the server's relevance rule.
        neonate = cases["neonate_flip_fields_and_stripped_answer"]
        self.assertEqual(neonate["data"]["Id10105"], "yes")
        self.assertNotIn("(Id10105) Baby cried immediately after birth", items["neonate_flip_fields_and_stripped_answer"])
        self.assertEqual(items["child_multiselects_numeric_flags"]["(Id10478) Narration keywords"], "Fever, Pneumonia, Rash")
        self.assertEqual(items["numeric_json_keys_and_numeric_cleaning"]["Survey state"], "Karnataka")
        self.assertEqual(
            items["adult_attachments_and_narrative"]["(md_im1) Medical Document Image 01"],
            "digitva-local-attachment:md_im1",
        )
        self.assertEqual(cases["no_consent_everything_stripped"]["visible_category_codes"], [])


class ListAnswerRenderTests(BaseTestCase):
    """Collect submits multi-selects as arrays; they must render as the space-joined string does."""

    CHOICES = {
        "Id10199": {"lower_left": "LowerLeft", "dk": "DontKnow", "ref": "Refused"},
        "Id10058": {"home": "Home", "hospital": "Hospital"},
    }

    def test_multiselect_array_renders_as_the_space_joined_string(self):
        for choices in (["lower_left", "dk"], ["lower_left"], []):
            with self.subTest(choices=choices):
                from_array = _render({"Id10199": choices}, "Id10199", self.CHOICES)
                from_string = _render({"Id10199": " ".join(choices)}, "Id10199", self.CHOICES)
                self.assertEqual(from_array, from_string)
        self.assertEqual(_render({"Id10199": ["lower_left", "dk"]}, "Id10199", self.CHOICES), {"Label": "LowerLeft, DontKnow"})

    def test_multiselect_array_labels_each_choice(self):
        choices = {"Id10478": {"fever": "Fever", "rash": "Rash"}}
        self.assertEqual(_render({"Id10478": ["fever", "rash"]}, "Id10478", choices), {"Label": "Fever, Rash"})

    def test_single_choice_array_labels_each_element(self):
        self.assertEqual(
            _render({"Id10058": ["hospital", "home", "unmapped"]}, "Id10058", self.CHOICES),
            {"Label": "Hospital, Home, unmapped"},
        )

    def test_lone_dk_or_ref_array_is_skipped_as_the_string_is(self):
        for skipped in ("dk", "ref", "DK"):
            with self.subTest(skipped=skipped):
                self.assertEqual(va_render_processcategorydata({"Id10199": skipped}, FORM_ID, {"cat": {"sub": {"Id10199": "L"}}}, self.CHOICES, "cat"), {})
                self.assertEqual(va_render_processcategorydata({"Id10199": [skipped]}, FORM_ID, {"cat": {"sub": {"Id10199": "L"}}}, self.CHOICES, "cat"), {})
        # Two elements are "dk ref", not a skip value: rendered, as the string is.
        self.assertEqual(_render({"Id10199": ["dk", "ref"]}, "Id10199", self.CHOICES), {"Label": "DontKnow, Refused"})

    def test_array_on_a_field_without_choices_is_the_joined_text(self):
        self.assertEqual(_render({"Id10476": ["a", 2]}, "Id10476", {}), {"Label": "a 2"})

    def test_array_of_numbers_matches_numeric_choice_keys(self):
        choices = {"survey_state": {"29": "Karnataka", "16": "Tripura"}}
        self.assertEqual(_render({"survey_state": [29, 16]}, "survey_state", choices), {"Label": "Karnataka, Tripura"})

    def test_summary_counts_read_an_array_as_its_joined_string(self):
        data = {"Id10120": ["5"], "Id10411": ["yes"], "Id10436": ["a", "b"]}
        summary, catcount = va_preprocess_summcatenotification(data)
        self.assertIn("Drinks alcohol", summary)
        self.assertIn("Illness duration (in days): 5", summary)
        self.assertIn("Cause of death / comment by the health worker: a b", summary)
        self.assertEqual(catcount["vademographicdetails"]["count"], 1)
        self.assertEqual(va_preprocess_summcatenotification({"Id10411": []})[0], [])
