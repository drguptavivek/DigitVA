"""Public ICD-10 catalogue projection and tree behaviour."""

import uuid

from app import db
from app.models import MasIcd1020192
from app.services import va_code_mapping_public_service as service
from tests.base import BaseTestCase


class Icd10PublicCatalogueTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.prefix = "QX" + uuid.uuid4().hex[:1].upper()
        self.parent = self.prefix
        self.detail = self.prefix + ".1"
        self.second_detail = self.prefix + ".2"
        shared = {
            "node_type": "category",
            "chapter_code": "TST",
            "chapter_title": "Test chapter",
            "block_code": "TST-BLOCK",
            "block_title": "Test block",
            "source_version": "test",
            "is_active": True,
        }
        db.session.add_all([
            MasIcd1020192(
                **shared,
                code=self.parent,
                title="Test parent category",
                semantic_level="three_character",
                sort_order=990001,
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                policy_status="reviewed",
                restriction_note="",
            ),
            MasIcd1020192(
                **shared,
                code=self.detail,
                title="Infant test condition",
                semantic_level="detailed_code",
                sort_order=990002,
                parent_code=self.parent,
                is_coding_selectable=False,
                sex_selectable="female",
                age_group_selectable="infant",
                policy_status="unreviewed",
                restriction_note="Infants only",
            ),
            MasIcd1020192(
                **shared,
                code=self.second_detail,
                title="Other test condition",
                semantic_level="detailed_code",
                sort_order=990003,
                parent_code=self.parent,
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                policy_status="reviewed",
                restriction_note="",
            ),
        ])
        db.session.flush()

    def test_catalogue_reads_active_code_levels_and_policy_fields(self):
        catalogue = service.get_icd10_catalogue()
        self.assertIn(self.parent, catalogue)
        self.assertIn(self.detail, catalogue)
        self.assertEqual(catalogue[self.detail]["parent_code"], self.parent)
        self.assertEqual(catalogue[self.detail]["chapter"], ("TST", "Test chapter"))
        self.assertEqual(catalogue[self.detail]["block"], ("TST-BLOCK", "Test block"))
        self.assertFalse(catalogue[self.detail]["selectable"])
        self.assertEqual(catalogue[self.detail]["sex_selectable"], "female")
        self.assertEqual(catalogue[self.detail]["age_group_selectable"], "infant")
        self.assertEqual(catalogue[self.detail]["policy_status"], "unreviewed")
        self.assertEqual(catalogue[self.detail]["restriction_note"], "Infants only")
        self.assertNotIn("TST-BLOCK", catalogue)

    def test_search_policy_origin_alias_and_unmapped_filters(self):
        catalogue = service.get_icd10_catalogue()
        rows = [
            {"classification": "icd10", "code": self.parent, "origin": service.ORIGIN_DIFFERS},
            {"classification": "icd10", "code": self.detail, "origin": service.ORIGIN_WHO},
        ]
        self.assertIn(
            self.detail,
            service.filter_icd10_catalogue(catalogue, q="infant test condition"),
        )
        self.assertEqual(
            service.filter_icd10_catalogue(catalogue, selectable="no", policy_status="unreviewed"),
            [self.detail],
        )
        self.assertEqual(
            service.filter_icd10_catalogue(catalogue, rows, origin="digitva"),
            [self.parent],
        )
        self.assertEqual(
            service.filter_icd10_catalogue(catalogue, rows, origin="unmapped"),
            [self.second_detail],
        )
        self.assertEqual(
            service.filter_icd10_catalogue(
                catalogue, sex_filter="female", age_filter="infant"
            ),
            [self.detail],
        )

    def test_tree_adds_parent_and_keeps_internal_note_out_of_cells(self):
        catalogue = service.get_icd10_catalogue()
        rows = [{
            "classification": "icd10",
            "code": self.parent,
            "va_code": "VAs-01.01",
            "va_title": "Sepsis",
            "origin": service.ORIGIN_NOT_IN_WHO,
            "rule": "Not in WHO's list; placed by clinical review (test)",
            "note": "Owner decision 5a (2026-09-25): internal crosswalk override",
        }]
        states = service.icd10_code_states([self.detail], catalogue, rows)
        nodes = service.icd10_state_nodes(states, catalogue, rows)
        by_id = {node["id"]: node for node in nodes}
        block_id = "b:TST:TST-BLOCK"
        self.assertEqual(by_id[self.parent]["parent_id"], block_id)
        self.assertEqual(by_id[self.detail]["parent_id"], self.parent)
        self.assertEqual(by_id[self.parent]["cells"]["va_cause"], "VAs-01.01 Sepsis")
        self.assertEqual(
            by_id[self.parent]["cells"]["origin"]["title"],
            "Expert review decision 5a (2026-09-25)",
        )
        self.assertNotIn("Owner decision", repr(nodes))
        self.assertNotIn("crosswalk", repr(nodes))

    def test_csv_contains_public_state_but_not_internal_note(self):
        catalogue = service.get_icd10_catalogue()
        rows = [{
            "classification": "icd10",
            "code": self.parent,
            "va_code": "VAs-01.01",
            "va_title": "Sepsis",
            "origin": service.ORIGIN_WHO,
            "rule": "",
            "note": "Owner decision 5a (2026-09-25): internal note",
        }]
        state = service.icd10_code_states([self.parent], catalogue, rows)[0]
        csv_row = dict(zip(service.ICD10_CSV_HEADERS, service.icd10_state_csv_row(state)))
        self.assertNotIn("note", service.ICD10_CSV_HEADERS)
        self.assertEqual(csv_row["classification"], "ICD-10")
        self.assertEqual(csv_row["origin"], service.ORIGIN_WHO)
        self.assertNotIn("Owner decision", repr(csv_row))

    def test_block_aligned_pages_keep_oversized_block_whole(self):
        catalogue = {
            "A00": {"chapter": ("I", "Infections"), "block": ("A00-A09", "Intestinal infections")},
            "A01": {"chapter": ("I", "Infections"), "block": ("A00-A09", "Intestinal infections")},
            "B00": {"chapter": ("I", "Infections"), "block": ("B00-B09", "Other infections")},
        }
        self.assertEqual(
            service.block_aligned_pages(list(catalogue), catalogue, 1),
            [["A00", "A01"], ["B00"]],
        )
