"""Tests for migrations dc762caa67dd (owner ICD-11 decisions on
WHO_2022_VA_2026) and fad35e5c4b79 (owner ICD-10 decisions 10, 11 and 12).

Policy: docs/policy/icd10-to-icd11-transition.md section 6. Follows the
throwaway-database shape from test_migrate_icd11_cod_bucket_mappings.py: a
database of its own, built from nothing but the migration chain.

On a fresh database 6c11b620f48f already seeds the regenerated CSV, so the
ICD-11 test first downgrades to reach the 2026-09-21 rows an existing
deployment holds, then upgrades again.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_migrate_owner_icd_decisions.py -q
"""
import csv
import importlib.util
import unittest
from pathlib import Path

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import stamp as alembic_stamp
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_migration_owner_icd_decisions"
PARENT_REVISION = "fba41e2f1f9d"
ICD11_REVISION = "dc762caa67dd"
ICD10_REVISION = "fad35e5c4b79"
REPO = Path(__file__).resolve().parents[2]
NEW_CSV = REPO / "resource" / "who_2022_va_2026_icd11_native_mappings.csv"
OLD_CSV = REPO / "resource" / "who_2022_va_2026_icd11_native_mappings_2026-09-21.csv"
OVERRIDES_CSV = (
    REPO / "docs" / "icd-causegrp-mappings" / "migration-artifacts"
    / "who-2022-va-icd-cod-2026-revision" / "WHO_2022_VA_2026_owner_decisions_overrides.csv"
)
ICD10_MIGRATION = REPO / "migrations" / "versions" / "fad35e5c4b79_apply_owner_icd10_decisions_who_2022_va_2026.py"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class MigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(MIGRATION_DB_NAME).render_as_string(hide_password=False)


def _admin_execute(statement):
    engine = sa.create_engine(_server_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(sa.text(statement))
    finally:
        engine.dispose()


def _csv_count(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for row in csv.DictReader(handle) if row["scheme_code"] == "WHO_2022_VA_2026")


class OwnerIcdDecisionsMigrationTest(unittest.TestCase):
    def setUp(self):
        _admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"')
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        self.addCleanup(lambda: _admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"'))

        from tests.base import create_app_without_celery_takeover

        self.app = create_app_without_celery_takeover(MigrationConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)

        alembic_upgrade(revision=PARENT_REVISION)

        from app import db

        self.db = db
        self.addCleanup(db.engine.dispose)

    def _rows(self, scheme_code, classification):
        with self.db.engine.connect() as conn:
            return {
                row.icd_code: tuple(row)[1:]
                for row in conn.execute(
                    sa.text(
                        "SELECT m.icd_code, n.node_code, m.match_type, m.mapping_note, m.source_sheet "
                        "FROM map_icd_cod_buckets m "
                        "JOIN mas_cod_bucket_nodes n ON n.node_id = m.node_id "
                        "JOIN mas_cod_bucket_schemes s ON s.scheme_id = m.scheme_id "
                        "WHERE s.scheme_code = :scheme AND m.icd_classification = :cls"
                    ),
                    {"scheme": scheme_code, "cls": classification},
                )
            }

    def _version(self):
        with self.db.engine.connect() as conn:
            return conn.execute(
                sa.text("SELECT mapping_version FROM mas_cod_bucket_schemes WHERE scheme_code = 'WHO_2022_VA_2026'")
            ).scalar_one()

    def _repoint(self, classification, icd_code, node_code):
        """An admin edit, the way the bucket editor stamps it."""
        with self.db.engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE map_icd_cod_buckets m SET node_id = n.node_id, match_type = 'manual_override', "
                    "mapping_note = 'Manual override to default COD bucket scheme mapping.', "
                    "source_sheet = 'admin_cod_bucket_editor' "
                    "FROM mas_cod_bucket_nodes n, mas_cod_bucket_schemes s "
                    "WHERE s.scheme_code = 'WHO_2022_VA_2026' AND m.scheme_id = s.scheme_id "
                    "AND n.scheme_id = s.scheme_id AND n.node_code = :node "
                    "AND m.icd_classification = :cls AND m.icd_code = :code"
                ),
                {"node": node_code, "cls": classification, "code": icd_code},
            )

    def test_icd11_decisions_upgrade_downgrade_keep_admin_edits_and_rerun_cleanly(self):
        expected_new, expected_old = _csv_count(NEW_CSV), _csv_count(OLD_CSV)
        self.assertEqual((expected_new, expected_old), (18505, 16154))
        alembic_upgrade(revision=ICD11_REVISION)
        self.assertEqual(len(self._rows("WHO_2022_VA_2026", "icd11")), expected_new)

        # Back to what an existing deployment holds (the 2026-09-21 table).
        alembic_downgrade(revision=PARENT_REVISION)
        old = self._rows("WHO_2022_VA_2026", "icd11")
        self.assertEqual(len(old), expected_old)
        self.assertEqual(old["KD3B.Z"][:2], ("vas_10_99", "range"))
        self.assertEqual(old["MG26"][:2], ("vas_99", "range"))
        self.assertEqual(old["BA50"][:2], ("vas_04_99", "range"))
        self.assertEqual(old["KD3B.1"][:2], ("vas_11_01", "range"))
        self.assertNotIn("QA00", old)
        self.assertEqual(old["KD3B.Z"][3], "who_2022_va_cause_list_icd10_icd11.csv")

        self._repoint("icd11", "BA50", "vas_98")
        version = self._version()
        alembic_upgrade(revision=ICD11_REVISION)

        new = self._rows("WHO_2022_VA_2026", "icd11")
        self.assertEqual(len(new), expected_new)
        self.assertEqual(new["KD3B.Z"][:2], ("vas_11_02", "owner_decision"))
        self.assertTrue(new["KD3B.Z"][2].startswith("Owner decision 9 (2026-09-24): "))
        self.assertEqual(new["KD3B.Z"][3], "who_2022_va_icd11_owner_decisions.csv")
        self.assertEqual(new["KD3B.1"][:2], ("vas_11_01", "range"), "the child of KD3B keeps its cause")
        self.assertEqual(new["MG26"][:2], ("vas_01_99", "owner_decision"))
        self.assertEqual(new["QA00"][:2], ("vas_99", "owner_fallback"))
        self.assertEqual(new["5C52.Y"][:2], ("vas_98", "owner_decision"))
        self.assertEqual(new["BA50"][:2], ("vas_98", "manual_override"), "admin edit survives")
        self.assertEqual(new["BA51"][:2], ("vas_04_01", "owner_decision"))
        self.assertEqual(self._version(), version + 1)

        # A rerun changes nothing and does not bump the version.
        alembic_stamp(revision=PARENT_REVISION)
        alembic_upgrade(revision=ICD11_REVISION)
        self.assertEqual(self._rows("WHO_2022_VA_2026", "icd11"), new)
        self.assertEqual(self._version(), version + 1)

        alembic_downgrade(revision=PARENT_REVISION)
        reverted = self._rows("WHO_2022_VA_2026", "icd11")
        self.assertEqual(len(reverted), expected_old)
        self.assertEqual(reverted["BA50"][:2], ("vas_98", "manual_override"))
        self.assertEqual(reverted["KD3B.Z"], old["KD3B.Z"])

    def test_icd10_decisions_move_only_workbook_rows_and_revert(self):
        alembic_upgrade(revision=ICD11_REVISION)
        who_2022 = self._rows("WHO_2022_VA", "icd10")
        before = self._rows("WHO_2022_VA_2026", "icd10")
        self.assertEqual(before["A80"][:3], ("vas_01_99", "range", None))
        self.assertEqual(before["V10.3"][:2], ("vas_12_02", "transport_non_road"))
        self.assertEqual(before["I50.0"][:2], ("vas_04_99", "range"))
        self._repoint("icd10", "V11.3", "vas_12_99")
        version = self._version()

        alembic_upgrade(revision=ICD10_REVISION)

        after = self._rows("WHO_2022_VA_2026", "icd10")
        for code in [f"A{number}" for number in range(80, 90)]:
            self.assertEqual(after[code][:2], ("vas_01_07", "owner_decision"), code)
            self.assertTrue(after[code][2].startswith("Owner decision 11 (2026-09-24): "))
            self.assertEqual(after[code][3], "ICD_Mapped")
        moved_to_road = {code for code, row in after.items() if row[0] == "vas_12_01" and row[1] == "owner_decision"}
        self.assertEqual(len(moved_to_road), 64, "65 codes less the admin-edited V11.3")
        self.assertIn("V43.4", moved_to_road)
        self.assertEqual(after["V11.3"][:2], ("vas_12_99", "manual_override"))
        for code in ("V82.4", "V81.4", "V15.3", "V25.3", "V97.1"):
            self.assertEqual(after[code][0], "vas_12_02", code)
        self.assertEqual(after["I50.0"][:2], ("vas_04_01", "owner_decision"))
        self.assertEqual(after["I50.9"][:2], ("vas_04_01", "owner_decision"))
        self.assertIn("A80", who_2022)
        self.assertEqual(self._rows("WHO_2022_VA", "icd10"), who_2022, "WHO_2022_VA is untouched")
        self.assertEqual(self._version(), version + 1)

        alembic_stamp(revision=ICD11_REVISION)
        alembic_upgrade(revision=ICD10_REVISION)
        self.assertEqual(self._rows("WHO_2022_VA_2026", "icd10"), after)
        self.assertEqual(self._version(), version + 1)

        alembic_downgrade(revision=ICD11_REVISION)
        reverted = self._rows("WHO_2022_VA_2026", "icd10")
        self.assertEqual(reverted["V11.3"][:2], ("vas_12_99", "manual_override"))
        del reverted["V11.3"], before["V11.3"]
        self.assertEqual(reverted, before)


class OverridesMatchMigrationTest(unittest.TestCase):
    """The reset layer and the migration must say the same thing."""

    def test_overrides_csv_equals_the_migration_decisions(self):
        spec = importlib.util.spec_from_file_location("owner_icd10_decisions", ICD10_MIGRATION)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from_migration = {
            code: (new_node, module.DECISION_MATCH_TYPE, note)
            for codes, _old, (new_node, note) in module.DECISIONS
            for code in codes
        }
        with OVERRIDES_CSV.open(newline="", encoding="utf-8") as handle:
            from_csv = {
                row["icd_code"]: (row["node_code"], row["match_type"], row["mapping_note"])
                for row in csv.DictReader(handle)
            }
        self.assertEqual(len(from_csv), 77)
        self.assertEqual(from_csv, from_migration)
