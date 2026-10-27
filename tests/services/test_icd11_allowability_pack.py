"""Drift guard for the ICD-11 allowability pack Collect Plus applies offline.

The phone judges a local final with mobile/digitva-collect/assets/icd11-allowability-<release>.json
(scripts/export_icd11_allowability_pack.py); the server judges with mas_icd11_mms. These tests fail when the two can
diverge silently: the exporter's selection rules, the committed pack against the signed-off policy plus the
migrations after it, and (where the catalogue is loaded) the committed pack against the database itself.
"""

import json
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import MasIcd11Mms
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from scripts.export_icd11_allowability_pack import build_pack, groups_digest, pack_path
from tests.base import BaseTestCase

ROOT = Path(__file__).resolve().parents[2]
SIGNOFF = ROOT / "resource/icd11_mms_2026_01_policy_signoff_2026_09_29.json"
TEST_RELEASE = "TEST-S2PACK"
# b8d4f2a6c1e9: KD3B.Z becomes selectable with its siblings' restriction; "Draft: " is stripped from notes.
KD3B_Z = ("both", "neonate_infant", "chapter 19 (KA-KD), neonates and infants")


def _row(code, *, release=TEST_RELEASE, kind="category", selectable=True, sex="both", age="all", note=None, active=True, chapter="01"):
    return MasIcd11Mms(
        release=release,
        linearization_uri=f"test://{release}/{code}",
        code=code,
        title=f"Title {code}",
        class_kind=kind,
        chapter_no=chapter,
        is_coding_selectable=selectable,
        sex_selectable=sex,
        age_group_selectable=age,
        restriction_note=note,
        sort_order=0,
        source_version="test",
        is_active=active,
    )


def _committed() -> dict:
    return json.loads(pack_path(DEFAULT_ICD11_RELEASE).read_text(encoding="utf-8"))


def _by_code(pack: dict) -> dict:
    return {code: (g["sex"], g["age"], g["note"]) for g in pack["groups"] for code in g["codes"]}


class Icd11AllowabilityPackBuildTests(BaseTestCase):
    def test_pack_holds_exactly_the_active_selectable_categories_grouped_by_restriction(self):
        db.session.add_all([
            _row("1A00"),
            _row("1A01"),
            _row("GB00", sex="male"),
            _row("KA00", age="neonate_infant", note="chapter 19"),
            _row("KA01", age="neonate_infant", note="chapter 19"),
            _row("NA07.7", selectable=False, chapter="22"),
            _row("2A00", active=False),
            _row("BLOCK1", kind="block"),
            _row("3A00", release="TEST-OTHER"),
        ])
        db.session.flush()

        pack = build_pack(TEST_RELEASE)

        self.assertEqual(pack["schema"], 1)
        self.assertEqual(pack["release"], TEST_RELEASE)
        self.assertEqual(pack["count"], 5)
        self.assertEqual(
            pack["groups"],
            [
                {"sex": "both", "age": "all", "note": None, "codes": ["1A00", "1A01"]},
                {"sex": "both", "age": "neonate_infant", "note": "chapter 19", "codes": ["KA00", "KA01"]},
                {"sex": "male", "age": "all", "note": None, "codes": ["GB00"]},
            ],
        )
        self.assertEqual(pack["sha256"], groups_digest(TEST_RELEASE, pack["groups"]))
        self.assertIsNone(pack["db_revision"])  # a create_all test database has no alembic_version

    def test_an_unrestricted_selectable_row_with_null_policy_columns_is_both_and_all(self):
        db.session.add(_row("1A00", sex=None, age=None))
        db.session.flush()

        self.assertEqual(
            build_pack(TEST_RELEASE)["groups"],
            [{"sex": "both", "age": "all", "note": None, "codes": ["1A00"]}],
        )


class Icd11AllowabilityCommittedPackTests(BaseTestCase):
    def test_committed_pack_is_internally_consistent(self):
        pack = _committed()
        self.assertEqual(pack["schema"], 1)
        self.assertEqual(pack["release"], DEFAULT_ICD11_RELEASE)
        self.assertEqual(pack["sha256"], groups_digest(pack["release"], pack["groups"]))
        self.assertEqual(pack["count"], len(_by_code(pack)))
        self.assertEqual(pack["count"], sum(len(g["codes"]) for g in pack["groups"]))

    def test_committed_pack_equals_signed_off_policy_plus_the_migrations_after_it(self):
        """Chapter 22 is out and KD3B.Z is in (b8d4f2a6c1e9); a later policy change must update this and the pack."""
        items = json.loads(SIGNOFF.read_text(encoding="utf-8"))["items"]
        expected = {
            item["code"]: (
                item["sex_selectable"],
                item["age_group_selectable"],
                (item["restriction_note"] or "").removeprefix("Draft: ") or None,
            )
            for item in items
            if item["class_kind"] == "category" and item["is_coding_selectable"] and item["chapter_no"] != "22"
        }
        expected["KD3B.Z"] = KD3B_Z
        actual = _by_code(_committed())

        self.assertEqual(sorted(set(expected) ^ set(actual)), [])
        self.assertEqual({c: v for c, v in expected.items() if actual[c] != v}, {})
        self.assertIn("KD3B.Z", actual)
        self.assertNotIn("NA07.7", actual)

    def test_committed_pack_equals_the_database_when_the_catalogue_is_loaded(self):
        loaded = db.session.scalar(
            sa.select(sa.func.count()).select_from(MasIcd11Mms).where(MasIcd11Mms.release == DEFAULT_ICD11_RELEASE)
        )
        if not loaded:
            self.skipTest("mas_icd11_mms has no rows for the pinned release in this database")
        live = build_pack(DEFAULT_ICD11_RELEASE)
        committed = _committed()
        # db_revision records where the pack was cut; everything the device reads must be identical.
        self.assertEqual({**live, "db_revision": None}, {**committed, "db_revision": None})
