import csv
import tempfile
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import MasIcd1020192
from app.services.icd.icd10_2019_2 import import_icd10_2019_2_from_csv
from tests.base import BaseTestCase


CSV_FIELDS = [
    "code",
    "title",
    "node_type",
    "semantic_level",
    "parent_code",
    "chapter_code",
    "chapter_title",
    "block_code",
    "block_title",
    "three_character_code",
    "three_character_title",
    "has_children",
    "is_leaf",
    "is_three_character_code",
    "is_detailed_code",
    "is_coding_selectable",
    "sex_selectable",
    "age_group_selectable",
    "policy_status",
    "restriction_note",
]


class TestIcd1020192Service(BaseTestCase):
    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MasIcd1020192))
        db.session.flush()

    def _write_csv(self, rows: list[dict[str, str]]) -> Path:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            suffix=".csv",
            delete=False,
        )
        path = Path(handle.name)
        try:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        finally:
            handle.close()
        return path

    def test_import_is_idempotent_and_soft_deactivates_missing_codes(self):
        csv_path = self._write_csv(
            [
                {
                    "code": "I",
                    "title": "Certain infectious and parasitic diseases",
                    "node_type": "chapter",
                    "semantic_level": "chapter",
                    "parent_code": "",
                    "chapter_code": "I",
                    "chapter_title": "Certain infectious and parasitic diseases",
                    "block_code": "",
                    "block_title": "",
                    "three_character_code": "",
                    "three_character_title": "",
                    "has_children": "true",
                    "is_leaf": "false",
                    "is_three_character_code": "false",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                },
                {
                    "code": "A00-A09",
                    "title": "Intestinal infectious diseases",
                    "node_type": "block",
                    "semantic_level": "block",
                    "parent_code": "I",
                    "chapter_code": "I",
                    "chapter_title": "Certain infectious and parasitic diseases",
                    "block_code": "A00-A09",
                    "block_title": "Intestinal infectious diseases",
                    "three_character_code": "",
                    "three_character_title": "",
                    "has_children": "true",
                    "is_leaf": "false",
                    "is_three_character_code": "false",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                },
                {
                    "code": "A00",
                    "title": "Cholera",
                    "node_type": "category",
                    "semantic_level": "three_character",
                    "parent_code": "A00-A09",
                    "chapter_code": "I",
                    "chapter_title": "Certain infectious and parasitic diseases",
                    "block_code": "A00-A09",
                    "block_title": "Intestinal infectious diseases",
                    "three_character_code": "A00",
                    "three_character_title": "Cholera",
                    "has_children": "true",
                    "is_leaf": "false",
                    "is_three_character_code": "true",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                },
                {
                    "code": "A00.0",
                    "title": "Cholera due to Vibrio cholerae 01, biovar cholerae",
                    "node_type": "category",
                    "semantic_level": "detailed_code",
                    "parent_code": "A00",
                    "chapter_code": "I",
                    "chapter_title": "Certain infectious and parasitic diseases",
                    "block_code": "A00-A09",
                    "block_title": "Intestinal infectious diseases",
                    "three_character_code": "A00",
                    "three_character_title": "Cholera",
                    "has_children": "false",
                    "is_leaf": "true",
                    "is_three_character_code": "false",
                    "is_detailed_code": "true",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                },
            ]
        )

        first_result = import_icd10_2019_2_from_csv(csv_path)
        self.assertEqual(first_result.inserted, 4)
        self.assertEqual(first_result.updated, 0)
        self.assertEqual(first_result.deactivated, 0)

        a00 = db.session.get(MasIcd1020192, "A00")
        a00.is_coding_selectable = True
        a00.sex_selectable = "both"
        a00.policy_status = "allowed"
        db.session.commit()

        csv_path = self._write_csv(
            [
                {
                    "code": "I",
                    "title": "Certain infectious and parasitic diseases",
                    "node_type": "chapter",
                    "semantic_level": "chapter",
                    "parent_code": "",
                    "chapter_code": "I",
                    "chapter_title": "Certain infectious and parasitic diseases",
                    "block_code": "",
                    "block_title": "",
                    "three_character_code": "",
                    "three_character_title": "",
                    "has_children": "true",
                    "is_leaf": "false",
                    "is_three_character_code": "false",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                },
                {
                    "code": "A00-A09",
                    "title": "Intestinal infectious diseases",
                    "node_type": "block",
                    "semantic_level": "block",
                    "parent_code": "I",
                    "chapter_code": "I",
                    "chapter_title": "Certain infectious and parasitic diseases",
                    "block_code": "A00-A09",
                    "block_title": "Intestinal infectious diseases",
                    "three_character_code": "",
                    "three_character_title": "",
                    "has_children": "true",
                    "is_leaf": "false",
                    "is_three_character_code": "false",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                },
                {
                    "code": "A00",
                    "title": "Cholera Updated",
                    "node_type": "category",
                    "semantic_level": "three_character",
                    "parent_code": "A00-A09",
                    "chapter_code": "I",
                    "chapter_title": "Certain infectious and parasitic diseases",
                    "block_code": "A00-A09",
                    "block_title": "Intestinal infectious diseases",
                    "three_character_code": "A00",
                    "three_character_title": "Cholera Updated",
                    "has_children": "false",
                    "is_leaf": "true",
                    "is_three_character_code": "true",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "false",
                    "sex_selectable": "female",
                    "age_group_selectable": "adult",
                    "policy_status": "excluded",
                    "restriction_note": "source says excluded",
                },
                {
                    "code": "A01",
                    "title": "Typhoid and paratyphoid fevers",
                    "node_type": "category",
                    "semantic_level": "three_character",
                    "parent_code": "A00-A09",
                    "chapter_code": "I",
                    "chapter_title": "Certain infectious and parasitic diseases",
                    "block_code": "A00-A09",
                    "block_title": "Intestinal infectious diseases",
                    "three_character_code": "A01",
                    "three_character_title": "Typhoid and paratyphoid fevers",
                    "has_children": "false",
                    "is_leaf": "true",
                    "is_three_character_code": "true",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                },
            ]
        )

        second_result = import_icd10_2019_2_from_csv(csv_path)
        self.assertEqual(second_result.inserted, 1)
        self.assertEqual(second_result.updated, 3)
        self.assertEqual(second_result.deactivated, 1)

        refreshed_a00 = db.session.get(MasIcd1020192, "A00")
        self.assertEqual(refreshed_a00.title, "Cholera Updated")
        self.assertFalse(refreshed_a00.has_children)
        self.assertTrue(refreshed_a00.is_coding_selectable)
        self.assertEqual(refreshed_a00.sex_selectable, "both")
        self.assertEqual(refreshed_a00.policy_status, "allowed")

        a000 = db.session.get(MasIcd1020192, "A00.0")
        self.assertFalse(a000.is_active)

        total_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(MasIcd1020192)
        )
        self.assertEqual(total_count, 5)

    def test_import_can_apply_policy_columns_when_requested(self):
        csv_path = self._write_csv(
            [
                {
                    "code": "A00",
                    "title": "Cholera",
                    "node_type": "category",
                    "semantic_level": "three_character",
                    "parent_code": "",
                    "chapter_code": "I",
                    "chapter_title": "Certain infectious and parasitic diseases",
                    "block_code": "A00-A09",
                    "block_title": "Intestinal infectious diseases",
                    "three_character_code": "A00",
                    "three_character_title": "Cholera",
                    "has_children": "false",
                    "is_leaf": "true",
                    "is_three_character_code": "true",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "true",
                    "sex_selectable": "both",
                    "age_group_selectable": "adult",
                    "policy_status": "allowed",
                    "restriction_note": "initial import",
                },
            ]
        )

        import_icd10_2019_2_from_csv(csv_path, apply_policy_columns=True)
        updated_csv_path = self._write_csv(
            [
                {
                    "code": "A00",
                    "title": "Cholera",
                    "node_type": "category",
                    "semantic_level": "three_character",
                    "parent_code": "",
                    "chapter_code": "I",
                    "chapter_title": "Certain infectious and parasitic diseases",
                    "block_code": "A00-A09",
                    "block_title": "Intestinal infectious diseases",
                    "three_character_code": "A00",
                    "three_character_title": "Cholera",
                    "has_children": "false",
                    "is_leaf": "true",
                    "is_three_character_code": "true",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "false",
                    "sex_selectable": "female",
                    "age_group_selectable": "neonate",
                    "policy_status": "restricted",
                    "restriction_note": "updated from source",
                },
            ]
        )

        import_icd10_2019_2_from_csv(updated_csv_path, apply_policy_columns=True)
        refreshed = db.session.get(MasIcd1020192, "A00")
        self.assertFalse(refreshed.is_coding_selectable)
        self.assertEqual(refreshed.sex_selectable, "female")
        self.assertEqual(refreshed.age_group_selectable, "neonate")
        self.assertEqual(refreshed.policy_status, "restricted")

    def test_new_three_character_rows_get_default_selectable_policy_except_stuz_codes(self):
        csv_path = self._write_csv(
            [
                {
                    "code": "A00",
                    "title": "Cholera",
                    "node_type": "category",
                    "semantic_level": "three_character",
                    "parent_code": "",
                    "chapter_code": "I",
                    "chapter_title": "Certain infectious and parasitic diseases",
                    "block_code": "A00-A09",
                    "block_title": "Intestinal infectious diseases",
                    "three_character_code": "A00",
                    "three_character_title": "Cholera",
                    "has_children": "false",
                    "is_leaf": "true",
                    "is_three_character_code": "true",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                },
                {
                    "code": "S00",
                    "title": "Superficial injury of head",
                    "node_type": "category",
                    "semantic_level": "three_character",
                    "parent_code": "",
                    "chapter_code": "XIX",
                    "chapter_title": "Injury, poisoning and certain other consequences of external causes",
                    "block_code": "S00-S09",
                    "block_title": "Injuries to the head",
                    "three_character_code": "S00",
                    "three_character_title": "Superficial injury of head",
                    "has_children": "false",
                    "is_leaf": "true",
                    "is_three_character_code": "true",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                },
                {
                    "code": "T00",
                    "title": "Superficial injuries involving multiple body regions",
                    "node_type": "category",
                    "semantic_level": "three_character",
                    "parent_code": "",
                    "chapter_code": "XIX",
                    "chapter_title": "Injury, poisoning and certain other consequences of external causes",
                    "block_code": "T00-T07",
                    "block_title": "Injuries involving multiple body regions",
                    "three_character_code": "T00",
                    "three_character_title": "Superficial injuries involving multiple body regions",
                    "has_children": "false",
                    "is_leaf": "true",
                    "is_three_character_code": "true",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                },
                {
                    "code": "U07",
                    "title": "Emergency use of U07",
                    "node_type": "category",
                    "semantic_level": "three_character",
                    "parent_code": "",
                    "chapter_code": "XXII",
                    "chapter_title": "Codes for special purposes",
                    "block_code": "U00-U49",
                    "block_title": "Codes for special purposes",
                    "three_character_code": "U07",
                    "three_character_title": "Emergency use of U07",
                    "has_children": "false",
                    "is_leaf": "true",
                    "is_three_character_code": "true",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                },
                {
                    "code": "Z00",
                    "title": "General examination and investigation of persons without complaint or reported diagnosis",
                    "node_type": "category",
                    "semantic_level": "three_character",
                    "parent_code": "",
                    "chapter_code": "XXI",
                    "chapter_title": "Factors influencing health status and contact with health services",
                    "block_code": "Z00-Z13",
                    "block_title": "Persons encountering health services for examination and investigation",
                    "three_character_code": "Z00",
                    "three_character_title": "General examination and investigation of persons without complaint or reported diagnosis",
                    "has_children": "false",
                    "is_leaf": "true",
                    "is_three_character_code": "true",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                },
            ]
        )

        import_icd10_2019_2_from_csv(csv_path)

        a00 = db.session.get(MasIcd1020192, "A00")
        self.assertTrue(a00.is_coding_selectable)
        self.assertEqual(a00.sex_selectable, "both")
        self.assertEqual(a00.age_group_selectable, "all")

        s00 = db.session.get(MasIcd1020192, "S00")
        self.assertIsNone(s00.is_coding_selectable)
        self.assertIsNone(s00.sex_selectable)
        self.assertIsNone(s00.age_group_selectable)

        t00 = db.session.get(MasIcd1020192, "T00")
        self.assertIsNone(t00.is_coding_selectable)
        self.assertIsNone(t00.sex_selectable)
        self.assertIsNone(t00.age_group_selectable)

        u07 = db.session.get(MasIcd1020192, "U07")
        self.assertIsNone(u07.is_coding_selectable)
        self.assertIsNone(u07.sex_selectable)
        self.assertIsNone(u07.age_group_selectable)

        z00 = db.session.get(MasIcd1020192, "Z00")
        self.assertIsNone(z00.is_coding_selectable)
        self.assertIsNone(z00.sex_selectable)
        self.assertIsNone(z00.age_group_selectable)
