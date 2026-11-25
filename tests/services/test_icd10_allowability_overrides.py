"""DigitVA allowability overrides layer (digitva-ghqe).

docs/policy/who-2022-icd10-coding-allowability.md, "DigitVA allowability
overrides layer". The CSV must equal the lists the migrations embedded.
"""
import csv
import importlib.util
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import MapIcd10LegacyReportingAlias, MasIcd1020192
from app.services.icd10_2019_2_service import (
    DEFAULT_ICD10_ALLOWABILITY_OVERRIDES_PATH,
    apply_icd10_2019_2_allowability_overrides,
)
from tests.base import BaseTestCase

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "migrations" / "versions"


def _migration(filename):
    spec = importlib.util.spec_from_file_location("mig_" + filename[:8], VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _csv_rows():
    with open(ROOT / DEFAULT_ICD10_ALLOWABILITY_OVERRIDES_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _add(code, three, *, selectable=True, age=None, sex=None):
    now = datetime.now(UTC)
    db.session.add(
        MasIcd1020192(
            code=code,
            title=code,
            node_type="category",
            semantic_level="three_character" if code == three else "detailed_code",
            sort_order=1,
            three_character_code=three,
            has_children=False,
            is_leaf=True,
            is_three_character_code=code == three,
            is_detailed_code=code != three,
            is_coding_selectable=selectable,
            age_group_selectable=age,
            sex_selectable=sex,
            policy_status="unreviewed",
            source_version="ICD-10-2019",
            source_path="test",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )


def _state(code):
    row = db.session.get(MasIcd1020192, code)
    return row.is_coding_selectable, row.age_group_selectable


class TestOverridesCsvMatchesMigrations(BaseTestCase):
    def test_csv_equals_migration_lists(self):
        rows = _csv_rows()
        q = {r["code"] for r in rows if r["age_group_selectable"] == "all"}
        transport = {r["code"] for r in rows if r["bead"] == "digitva-g2n"}
        r_families = {r["code"] for r in rows if r["match"] == "family"}
        self.assertEqual(len(q), 87)
        self.assertEqual(
            q, set(_migration("a3c9e1f7b2d4_icd10_congenital_anomalies_all_ages.py").Q_CODES)
        )
        self.assertEqual(
            transport,
            set(
                _migration(
                    "a5f7c3d92b18_owner_decisions_15_16_17_stillbirth_vocab.py"
                ).V_Y85_NOT_SELECTABLE_CODES
            ),
        )
        self.assertEqual(len(r_families), 85)
        self.assertEqual(
            r_families,
            set(_migration("1f037b4717e4_withdraw_icd10_r00_r94_symptom_codes.py").WITHDRAWN_FAMILIES),
        )
        self.assertEqual(len(rows), 87 + len(transport) + 85)


class TestApplyAllowabilityOverrides(BaseTestCase):
    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MapIcd10LegacyReportingAlias))
        db.session.execute(sa.delete(MasIcd1020192))
        _add("R10", "R10")
        _add("R10.4", "R10")
        _add("R17", "R17")
        _add("R50", "R50")
        _add("R54", "R54")
        _add("R95", "R95")
        _add("R99", "R99")
        _add("Q00", "Q00", age="neonate")
        _add("V10", "V10")
        db.session.commit()

    def test_apply_sets_listed_fields_and_second_run_is_noop(self):
        # present before absent: the starting state is the imported policy
        self.assertEqual(_state("R10"), (True, None))
        self.assertEqual(_state("Q00"), (True, "neonate"))
        self.assertEqual(_state("V10"), (True, None))

        result = apply_icd10_2019_2_allowability_overrides()

        self.assertEqual(_state("R10"), (False, None))
        self.assertEqual(_state("R17"), (False, None))
        self.assertEqual(_state("Q00"), (True, "all"))
        self.assertEqual(_state("V10"), (False, None))
        for kept in ("R50", "R54", "R95", "R99"):
            self.assertEqual(_state(kept), (True, None), kept)
        self.assertIn(
            {"code": "Q00", "field": "age_group_selectable", "before": "neonate", "after": "all"},
            result.changed,
        )
        self.assertIn(
            {"code": "V10", "field": "is_coding_selectable", "before": True, "after": False},
            result.changed,
        )
        self.assertEqual(result.counts["rows_changed"], 5)
        self.assertEqual(result.counts["fields_changed"], 5)
        self.assertIn("V01", result.missing)

        again = apply_icd10_2019_2_allowability_overrides()
        self.assertEqual(again.changed, [])
        self.assertEqual(again.counts["rows_changed"], 0)

    def test_family_match_covers_detailed_subcode(self):
        self.assertEqual(_state("R10.4"), (True, None))
        result = apply_icd10_2019_2_allowability_overrides()
        self.assertEqual(_state("R10.4"), (False, None))
        self.assertIn(
            {"code": "R10.4", "field": "is_coding_selectable", "before": True, "after": False},
            result.changed,
        )

    def test_invalid_row_raises_and_writes_nothing(self):
        header = "match,code,is_coding_selectable,sex_selectable,age_group_selectable\n"
        with tempfile.TemporaryDirectory() as tmp:
            for body, needle in (
                ("family,R10,false,,\ncode,R17,false,,sideways\n", "R17"),
                ("family,R10,false,,\nlevel,R17,false,,\n", "unknown match"),
                ("family,R10,false,,\ncode,,false,,\n", "missing code"),
            ):
                path = Path(tmp) / "o.csv"
                path.write_text(header + body, encoding="utf-8")
                with self.assertRaises(ValueError) as ctx:
                    apply_icd10_2019_2_allowability_overrides(path)
                self.assertIn(needle, str(ctx.exception))
        self.assertEqual(_state("R10"), (True, None))


class TestApplyOverridesRoute(BaseTestCase):
    URL = "/admin/api/icd10/2019-2/apply-overrides"

    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MapIcd10LegacyReportingAlias))
        db.session.execute(sa.delete(MasIcd1020192))
        _add("R10", "R10")
        db.session.commit()

    def test_admin_gets_changed_list(self):
        self._login(str(self.base_admin_user.user_id))
        response = self.client.post(self.URL, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn(
            {"code": "R10", "field": "is_coding_selectable", "before": True, "after": False},
            payload["changed"],
        )
        self.assertEqual(payload["counts"]["rows_changed"], 1)
        self.assertIn("R00", payload["missing"])
        self.assertEqual(_state("R10"), (False, None))

    def test_non_admin_refused(self):
        self._login(str(self.base_project_pi_user.user_id))
        response = self.client.post(self.URL, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(_state("R10"), (True, None))

    def test_missing_csrf_refused(self):
        self._login(str(self.base_admin_user.user_id))
        response = self.client.post(self.URL)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(_state("R10"), (True, None))
