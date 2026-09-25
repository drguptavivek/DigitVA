"""ICD-11 coding-selectability policy draft (digitva-dus.3).

Policy: docs/policy/who-2022-icd11-coding-allowability.md. A small synthetic
catalogue pins each rule with a code whose answer is known: annex ranges and
decision 5a make codes selectable, the S/V/Q/X chapters and the non-RA01
emergency codes never are, ICD-10 restrictions carry over only when every
ICD-10 source agrees (never from the blanket O/P/Q chapter rules; chapter 20
is all ages, owner 2026-09-24), and the draft imports through the existing
policy importer.
"""

import tempfile
import unittest
from pathlib import Path

import sqlalchemy as sa
from openpyxl import Workbook

from app import db
from app.models import MasIcd11Mms
from app.services.cod_bucket_icd11_generator import load_catalogue
from app.services.icd11_mms_service import import_icd11_mms_policy_json
from app.services.icd11_policy_draft_service import (
    FLAG_CONFLICT,
    draft_icd11_policy,
    load_category_rows,
    load_icd10_to_icd11,
    policy_payload,
)
from tests.base import BaseTestCase

RELEASE = "TEST-DUS3"

# (code, parent code, chapter, residual)
CATALOGUE = (
    ("1C15", None, "01", False),
    ("1G40", None, "01", False),
    ("1G41", None, "01", False),
    ("1G41.0", "1G41", "01", False),
    ("1G41.Z", "1G41", "01", True),
    ("1H00", None, "01", False),
    ("2C77", None, "02", False),
    ("2C77.0", "2C77", "02", False),
    ("2C77.Z", "2C77", "02", True),
    ("2F3Z", None, "02", True),
    ("5A20", None, "05", False),
    ("5A20.0", "5A20", "05", False),
    ("5C52.Y", None, "05", True),
    ("5C52.Z", None, "05", True),
    ("CA25", None, "12", False),
    ("CA25.0", "CA25", "12", False),
    ("GB81", None, "16", False),
    ("JA00", None, "18", False),
    ("LA00", None, "20", False),
    ("MH11", None, "21", False),
    ("MH11.0", "MH11", "21", False),
    ("MH11.Z", "MH11", "21", True),
    ("QA00", None, "24", False),
    ("RA01", None, "25", False),
    ("RA01.0", "RA01", "25", False),
    ("RA02", None, "25", False),
    ("SA00", None, "26", False),
    ("VD00", None, "V", False),
    ("XA0001", None, "X", False),
)

CAUSE_ROWS = [
    {"va_code": "VAs-01.01", "icd11_codes": "1G40-1G41"},
    {"va_code": "VAs-02.99", "icd11_codes": "2C77; 2F3Z"},
    {"va_code": "VAs-10.06", "icd11_codes": "LA00"},
    {"va_code": "VAs-98", "icd11_codes": "5C52.Y-5C52-Z; CA25; GB81"},
    {"va_code": "VAs-09.02", "icd11_codes": "JA00"},
    {"va_code": "VAs-10.05", "icd11_codes": "1C15"},
    {"va_code": "VAs-10.99", "icd11_codes": "MH11"},
    {"va_code": "VAs-01.13", "icd11_codes": "RA01.0; RA02"},
    # Not in WHO's annex: proves the exclusions beat any annex range.
    {"va_code": "TEST", "icd11_codes": "QA00; SA00; VD00"},
]

ICD10_RESTRICTIONS = {
    "A33": ("both", "neonate"),
    "C53": ("female", "all"),
    "D26": ("female", "all"),
    "D29": ("male", "all"),
    "E84": ("both", "all"),
    "P75": ("both", "neonate"),
    "Q61": ("both", "neonate"),
    "R95": ("both", "infant"),
}

ICD10_TO_ICD11 = {
    "A33": "1C15",
    "C53": "2C77.Z",
    "D26.9": "2F3Z",  # D26.9 and D29.9 disagree on sex
    "D29.9": "2F3Z",
    "Q00": "LA00",
    "E84.0": "CA25.0",  # E84.0 is not in the policy: its parent E84 counts
    "P75": "CA25.0",
    "Q61.2": "GB81",
    "R95": "MH11.Z",
    "R95.0": "MH11.0",
}


def _rows():
    return [
        {
            "code": code,
            "title": f"Title {code}",
            "linearization_uri": f"test://{code}",
            "chapter_no": chapter,
            "is_residual": residual,
            "is_leaf": not any(other_parent == code for _, other_parent, _, _ in CATALOGUE),
        }
        for code, _, chapter, residual in CATALOGUE
    ]


def _catalogue():
    # load_catalogue's shape: chapter X left out.
    return {
        code: {"title": f"Title {code}", "parent": parent}
        for code, parent, chapter, _ in CATALOGUE
        if chapter != "X"
    }


def _draft(rows=None, catalogue=None):
    return draft_icd11_policy(
        release=RELEASE,
        rows=rows or _rows(),
        catalogue=catalogue or _catalogue(),
        cause_rows=CAUSE_ROWS,
        icd10_restrictions=ICD10_RESTRICTIONS,
        icd10_to_icd11=ICD10_TO_ICD11,
    )


class Icd11PolicyDraftRuleTests(unittest.TestCase):
    def setUp(self):
        self.decisions = {row["code"]: row for row in _draft().decisions}

    def test_annex_range_selects_parents_children_and_residuals(self):
        for code in ("1G40", "1G41", "1G41.0", "1G41.Z"):
            self.assertTrue(self.decisions[code]["selectable"], code)
            self.assertEqual(self.decisions[code]["rule"], "annex")
        self.assertIn("1H00", self.decisions)
        self.assertFalse(self.decisions["1H00"]["selectable"])
        self.assertEqual(self.decisions["1H00"]["rule"], "not_in_annex")

    def test_uncovered_code_without_crosswalk_suggestion_stays_unselectable(self):
        code = "1H00"
        crosswalk_targets = {
            target
            for value in ICD10_TO_ICD11.values()
            for alternative in value.split("/")
            for target in alternative.split("&")
        }
        self.assertNotIn(code, crosswalk_targets)
        self.assertFalse(self.decisions[code]["selectable"])
        self.assertEqual(self.decisions[code]["rule"], "not_in_annex")

    def test_malformed_5c52_range_is_read_as_owner_corrected(self):
        self.assertTrue(self.decisions["5C52.Y"]["selectable"])
        self.assertTrue(self.decisions["5C52.Z"]["selectable"])

    def test_q_s_v_x_chapters_and_non_ra01_emergency_codes_are_never_selectable(self):
        for code in ("QA00", "SA00", "VD00", "XA0001"):
            self.assertIn(code, self.decisions)
            self.assertFalse(self.decisions[code]["selectable"], code)
            self.assertEqual(self.decisions[code]["rule"], "excluded_chapter")
        self.assertFalse(self.decisions["RA02"]["selectable"])
        self.assertEqual(self.decisions["RA02"]["rule"], "excluded_emergency")
        self.assertTrue(self.decisions["RA01.0"]["selectable"])

    def test_decision_5a_codes_are_selectable_with_descendants(self):
        for code in ("5A20", "5A20.0", "RA01"):
            self.assertTrue(self.decisions[code]["selectable"], code)
            self.assertEqual(self.decisions[code]["rule"], "decision_5a")

    def test_one_to_one_icd10_restriction_is_carried(self):
        tetanus = self.decisions["1C15"]
        self.assertEqual((tetanus["sex"], tetanus["age"]), ("both", "neonate"))
        self.assertEqual(tetanus["restriction_rule"], "icd10 A33")
        # Every child of MH11 carries R95's infant rule, so MH11 does too.
        for code in ("MH11.0", "MH11.Z", "MH11"):
            self.assertEqual(self.decisions[code]["age"], "infant", code)

    def test_blanket_o_p_q_restrictions_are_never_carried(self):
        # Q61.2 (neonate by the ICD-10 Q chapter rule) outside chapters 18-20,
        # Q00 inside chapter 20 (all ages), P75 beside a both/all source.
        for code in ("GB81", "LA00", "CA25.0"):
            decision = self.decisions[code]
            self.assertTrue(decision["selectable"], code)
            self.assertEqual((decision["sex"], decision["age"]), ("both", "all"), code)
            self.assertEqual(decision["flags"], set(), code)

    def test_conflicting_icd10_restrictions_default_and_are_flagged(self):
        other = self.decisions["2F3Z"]
        self.assertEqual((other["sex"], other["age"]), ("both", "all"))
        self.assertIn(f"{FLAG_CONFLICT}:D26.9=female/all D29.9=male/all", other["flags"])

    def test_chapter_and_block_rules(self):
        self.assertEqual((self.decisions["JA00"]["sex"], self.decisions["JA00"]["age"]), ("female", "adult"))
        for code in ("2C77", "2C77.0", "2C77.Z"):
            self.assertEqual(self.decisions[code]["sex"], "female", code)
            self.assertEqual(self.decisions[code]["restriction_source"], "block")

    def test_payload_lists_only_selectable_rows_without_policy_status(self):
        payload = policy_payload(_draft())
        codes = {item["code"] for item in payload["items"]}
        self.assertIn("1G41.Z", codes)
        self.assertNotIn("QA00", codes)
        self.assertEqual(payload["row_count"], len(payload["items"]))
        self.assertTrue(all("policy_status" not in item for item in payload["items"]))
        notes = {item["code"]: item["restriction_note"] for item in payload["items"]}
        self.assertEqual(notes["1C15"], "Draft: icd10 A33")
        self.assertIsNone(notes["1G40"])


class Icd10ToIcd11LoaderTests(unittest.TestCase):
    def test_2025_targets_are_translated_to_2026_codes(self):
        tmp = Path(tempfile.mkdtemp())
        table = tmp / "10To11.txt"
        table.write_text(
            "10ClassKind\tDepth\ticd10Code\ticd10Chapter\ticd10Title\t11ClassKind\tDepth\t"
            "Foundation\tLinearization\ticd11Code\ticd11Chapter\ticd11Title\t2025-Jan-24\n"
            "category\t3\tA00\tI\tCholera\tcategory\t3\tf\tl\t1A00\t01\tCholera\n"
            "category\t3\tA01\tI\tTyphoid\tcategory\t3\tf\tl\tOLD1&XA01/OLD1\t01\tTyphoid\n"
            "block\t1\tA00-A09\tI\tIntestinal\tblock\t1\tf\tl\t\t01\tIntestinal\n",
            encoding="utf-8",
        )
        crosswalk = tmp / "11To10.txt"
        crosswalk.write_text("header\n", encoding="utf-8")
        changes = tmp / "changes.xlsx"
        workbook = Workbook()
        workbook.active.append(["Chapter", "Foundation", "2025", "2026", "Code", "Title", "Status"])
        workbook.active.append(["01", None, None, None, "OLD1 -> 1A07", "Typhoid", "MovedTo"])
        workbook.save(changes)

        mapping = load_icd10_to_icd11(str(table), str(changes), str(crosswalk))

        self.assertEqual(mapping, {"A00": "1A00", "A01": "1A07&XA01/1A07"})


class Icd11PolicyDraftImportTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        for index, (code, parent, chapter, residual) in enumerate(CATALOGUE):
            db.session.add(
                MasIcd11Mms(
                    release=RELEASE,
                    linearization_uri=f"test://{code}",
                    parent_linearization_uri=f"test://{parent}" if parent else None,
                    code=code,
                    title=f"Title {code}",
                    class_kind="category",
                    chapter_no=chapter,
                    is_residual=residual,
                    sort_order=index,
                    source_version="test",
                    is_active=True,
                )
            )
        db.session.flush()

    def _policy(self):
        rows = db.session.scalars(sa.select(MasIcd11Mms).where(MasIcd11Mms.release == RELEASE)).all()
        return {
            row.code: (row.is_coding_selectable, row.sex_selectable, row.age_group_selectable)
            for row in rows
        }

    def test_draft_from_the_database_imports_and_resets_unlisted_categories(self):
        draft = _draft(rows=load_category_rows(RELEASE), catalogue=load_catalogue(RELEASE))
        payload = policy_payload(draft)

        result = import_icd11_mms_policy_json(payload, release=RELEASE)

        self.assertEqual(result.skipped_items, [])
        self.assertEqual(result.updated_items, payload["row_count"])
        policy = self._policy()
        self.assertEqual(policy["1C15"], (True, "both", "neonate"))
        self.assertEqual(policy["JA00"], (True, "female", "adult"))
        self.assertEqual(policy["LA00"], (True, "both", "all"))
        self.assertEqual(policy["1G41.Z"], (True, "both", "all"))
        # Unlisted categories, chapter X included, become not selectable.
        for code in ("XA0001", "QA00", "1H00", "RA02"):
            self.assertEqual(policy[code], (False, None, None), code)
        selectable = {code for code, values in policy.items() if values[0]}
        self.assertEqual(selectable, {item["code"] for item in payload["items"]})
