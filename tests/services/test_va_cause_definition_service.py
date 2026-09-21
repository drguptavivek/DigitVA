"""app/services/va_cause_definition_service.py: parse, import, listing, ICD lookup."""
import json
import unittest

import sqlalchemy as sa

from app import db
from app.models import (
    MapIcdCodBucket,
    MasCodBucketNode,
    MasCodBucketScheme,
    MasIcd11Mms,
    MasVaCauseDefinition,
)
from app.services import va_cause_definition_service as svc
from app.utils.rich_text import sanitize_rich_text
from tests.base import BaseTestCase


def _source_rows():
    return svc.parse_va_definitions_html(svc.DEFAULT_SOURCE_HTML_PATH.read_text(encoding="utf-8"))


class ParseVaDefinitionsHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _source_rows()
        cls.by_code = {row["va_code"]: row for row in cls.rows}

    def test_parses_only_cause_codes_in_code_order(self):
        codes = [r["va_code"] for r in self.rows]
        self.assertEqual(len([c for c in codes if "." in c]), 62)
        self.assertEqual(len(codes), 63)
        self.assertEqual(codes, sorted(codes))
        self.assertEqual((codes[0], codes[-1]), ("VAs-01.01", "VAs-99"))
        # Section headings are not codes; VAs-98 is treated as a group.
        self.assertIn("VAs-01.01", codes)
        for not_a_cause in ("VAs-01", "VAs-12", "VAs-98"):
            self.assertNotIn(not_a_cause, codes)

    def test_titles(self):
        self.assertEqual(self.by_code["VAs-01.01"]["title"], "Sepsis")
        self.assertEqual(
            self.by_code["VAs-12.07"]["title"],
            "Accidental poisoning and exposure to noxious substances",
        )
        self.assertEqual(self.by_code["VAs-99"]["title"], "Cause of death unknown")

    def test_definition_keeps_lists_notes_and_numbering(self):
        sepsis = self.by_code["VAs-01.01"]["definition_html"]
        self.assertTrue(sepsis.startswith("1. Fever AND mental confusion"))
        self.assertIn(
            "<li>Inability to stand up (information needs to come from the open narrative)</li>",
            sepsis,
        )
        self.assertIn("<p><em>NOTE: If there is a more specific cause", sepsis)
        self.assertNotIn("class=", sepsis)
        hiv = self.by_code["VAs-01.03"]["definition_html"]
        self.assertIn("<p>OR</p>", hiv)
        self.assertIn("2. H/O severe weight loss", hiv)
        self.assertEqual(hiv.count("<li>"), 7)
        self.assertIn("&lt; 2 weeks", self.by_code["VAs-01.04"]["definition_html"])
        self.assertIn("<b>Oesophageal cancer</b>", self.by_code["VAs-02.02"]["definition_html"])

    def test_stored_html_round_trips_the_sanitizer(self):
        for row in self.rows:
            self.assertEqual(sanitize_rich_text(row["definition_html"]), row["definition_html"], row["va_code"])

    def test_seed_json_matches_the_source(self):
        self.assertEqual(svc.load_seed_rows(), json.loads(json.dumps(self.rows)))

    def test_rejects_a_bad_code(self):
        with self.assertRaises(ValueError):
            svc.parse_va_definitions_html("<table><tr><td>X-1</td><td>t</td><td>d</td></tr></table>")


class ImportVaDefinitionsTests(BaseTestCase):
    def _row(self, code):
        return db.session.scalar(sa.select(MasVaCauseDefinition).where(MasVaCauseDefinition.va_code == code))

    def test_import_is_idempotent(self):
        rows = _source_rows()
        first = svc.import_va_definitions(rows)
        self.assertEqual(first.inserted, 63)
        second = svc.import_va_definitions(rows)
        self.assertEqual((second.inserted, second.updated, second.unchanged), (0, 0, 63))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(MasVaCauseDefinition)), 63)

    def test_admin_edited_row_survives_reimport_unless_forced(self):
        rows = _source_rows()
        svc.import_va_definitions(rows)
        sepsis = self._row("VAs-01.01")
        svc.update_va_definition(sepsis.id, {"title": "Sepsis (local)"}, user_id=self.base_admin_id)

        result = svc.import_va_definitions(rows)
        self.assertEqual(result.skipped_edited, 1)
        self.assertEqual(self._row("VAs-01.01").title, "Sepsis (local)")

        forced = svc.import_va_definitions(rows, force=True)
        self.assertEqual(forced.updated, 1)
        row = self._row("VAs-01.01")
        self.assertEqual(row.title, "Sepsis")
        self.assertIsNone(row.updated_by)

    def test_update_sanitizes_and_records_the_editor(self):
        svc.import_va_definitions(_source_rows())
        row = self._row("VAs-01.02")
        payload, changed = svc.update_va_definition(
            row.id,
            {"definition_html": '<p onclick="x">a<script>alert(1)</script></p>'},
            user_id=self.base_admin_id,
        )
        self.assertEqual(payload["definition_html"], "<p>a</p>")
        self.assertEqual(changed, ["definition_html"])
        self.assertTrue(payload["edited"])

    def test_coder_listing_filters(self):
        svc.import_va_definitions(_source_rows())
        everything = svc.list_coder_va_definitions()
        self.assertEqual(everything["total"], 63)
        self.assertEqual(everything["definitions"][0]["va_code"], "VAs-01.01")

        codes = [d["va_code"] for d in svc.list_coder_va_definitions("SEPSIS")["definitions"]]
        self.assertIn("VAs-01.01", codes)
        self.assertNotIn("VAs-02.01", codes)

        by_code = svc.list_coder_va_definitions("vas-12.")
        self.assertEqual(by_code["total"], 11)

        by_text = [d["va_code"] for d in svc.list_coder_va_definitions("fontanelle")["definitions"]]
        self.assertIn("VAs-01.07", by_text)

        self.assertEqual(svc.list_coder_va_definitions("zzzz-no-such")["definitions"], [])

    def test_inactive_rows_are_hidden_from_coders(self):
        svc.import_va_definitions(_source_rows())
        row = self._row("VAs-01.01")
        svc.update_va_definition(row.id, {"is_active": False}, user_id=self.base_admin_id)
        codes = [d["va_code"] for d in svc.list_coder_va_definitions()["definitions"]]
        self.assertIn("VAs-01.02", codes)
        self.assertNotIn("VAs-01.01", codes)

    def test_create_refuses_group_codes(self):
        for code in ("VAs-01", "VAs-98"):
            with self.assertRaises(ValueError):
                svc.create_va_definition({"va_code": code, "title": "x"}, user_id=self.base_admin_id)


def seed_icd_lookup_fixtures():
    """Minimal WHO_2022_VA (ICD-10) and WHO_2022_VA_2026 (ICD-11) mappings.

    ICD-10 A04 -> vas_01_04; ICD-10 Z99 -> a non-VA node. ICD-11 1A00 ->
    vas_01_04, reached from 1A00.1 through the mas_icd11_mms parent chain.
    Shared with tests/routes/test_va_definitions_routes.py.
    """
    svc.import_va_definitions(svc.load_seed_rows())
    nodes = {}
    for scheme_code in ("WHO_2022_VA", "WHO_2022_VA_2026"):
        scheme = db.session.scalar(
            sa.select(MasCodBucketScheme).where(MasCodBucketScheme.scheme_code == scheme_code)
        )
        if scheme is None:
            scheme = MasCodBucketScheme(scheme_code=scheme_code, scheme_name=scheme_code)
            db.session.add(scheme)
            db.session.flush()
        for node_code in ("vas_01_04", "other_gastrointestinal_diseases"):
            node = MasCodBucketNode(
                scheme_id=scheme.scheme_id, node_type="field", node_code=node_code,
                node_label=node_code, age_scope="vadef_test",
            )
            db.session.add(node)
            db.session.flush()
            nodes[(scheme_code, node_code)] = node

    def _map(scheme_code, node_code, icd_code, classification):
        node = nodes[(scheme_code, node_code)]
        db.session.add(MapIcdCodBucket(
            scheme_id=node.scheme_id, node_id=node.node_id, icd_code=icd_code,
            icd_classification=classification, age_scope="vadef_test",
        ))

    _map("WHO_2022_VA", "vas_01_04", "A04", "icd10")
    _map("WHO_2022_VA", "other_gastrointestinal_diseases", "Z99", "icd10")
    _map("WHO_2022_VA_2026", "vas_01_04", "1A00", "icd11")
    # The ICD-10 code in the wrong scheme must not be found.
    _map("WHO_2022_VA_2026", "vas_01_04", "B99", "icd10")

    release = svc.DEFAULT_ICD11_RELEASE
    for uri, code, parent in (
        ("vadef-test/1A00", "1A00", None),
        ("vadef-test/1A00.1", "1A00.1", "vadef-test/1A00"),
    ):
        if db.session.scalar(
            sa.select(MasIcd11Mms.id).where(MasIcd11Mms.release == release, MasIcd11Mms.code == code)
        ):
            continue
        db.session.add(MasIcd11Mms(
            release=release, linearization_uri=uri, code=code, title=code,
            class_kind="category", source_version="test", parent_linearization_uri=parent,
        ))
    db.session.commit()


class FindVaDefinitionForIcdTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        seed_icd_lookup_fixtures()

    def _va(self, value, classification=None):
        found = svc.find_va_definition_for_icd(value, classification)
        return found and found["va_code"]

    def test_icd10_exact_and_three_character_parent(self):
        self.assertEqual(self._va("A04"), "VAs-01.04")
        found = svc.find_va_definition_for_icd("A04.0-Other bacterial intestinal infections")
        self.assertEqual((found["icd_code"], found["classification"], found["va_code"]), ("A04.0", "icd10", "VAs-01.04"))
        self.assertEqual(found["title"], "Diarrhoeal diseases")

    def test_icd11_exact_and_parent_chain(self):
        self.assertEqual(self._va("1A00"), "VAs-01.04")
        self.assertEqual(self._va("1A00.1 - child", "icd11"), "VAs-01.04")

    def test_no_definition(self):
        self.assertIsNone(self._va("Z99"))  # mapped, but not to a vas_* cause
        self.assertIsNone(self._va("B99"))  # mapped only in the other scheme
        self.assertIsNone(self._va("C00"))  # not mapped
        self.assertIsNone(self._va("1A00", "icd10"))  # wrong classification
        self.assertIsNone(self._va("not a code"))
        self.assertIsNone(self._va(""))

    def test_inactive_definition_is_not_returned(self):
        row = db.session.scalar(sa.select(MasVaCauseDefinition).where(MasVaCauseDefinition.va_code == "VAs-01.04"))
        svc.update_va_definition(row.id, {"is_active": False}, user_id=self.base_admin_id)
        self.assertIsNone(self._va("A04"))
