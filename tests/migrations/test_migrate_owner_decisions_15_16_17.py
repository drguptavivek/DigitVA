"""Tests for migration a5f7c3d92b18 (owner decisions 15, 16, 17 and the
stillbirth vocabulary rows).

Policy: docs/policy/icd10-to-icd11-transition.md section 6 (decisions
15-18) and docs/policy/who-2022-icd10-coding-allowability.md. Follows the
throwaway-database shape from test_migrate_owner_icd_decisions.py: a
database of its own, built from nothing but the migration chain.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_migrate_owner_decisions_15_16_17.py -q
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

MIGRATION_DB_NAME = "minerva_test_migration_owner_decisions_15_16_17"
PARENT_REVISION = "fdb562cccac4"
REVISION = "a5f7c3d92b18"
REPO = Path(__file__).resolve().parents[2]
MIGRATION_FILE = (
    REPO / "migrations" / "versions" / "a5f7c3d92b18_owner_decisions_15_16_17_stillbirth_vocab.py"
)
ICD10_OVERRIDES_CSV = (
    REPO / "docs" / "icd-causegrp-mappings" / "migration-artifacts"
    / "who-2022-va-icd-cod-2026-revision" / "WHO_2022_VA_2026_owner_decisions_overrides.csv"
)
ICD11_DECISIONS_CSV = (
    REPO / "docs" / "icd-causegrp-mappings" / "ICD-to-VA-Buckets" / "who_2022_va_icd11_owner_decisions.csv"
)


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


def _load_module():
    spec = importlib.util.spec_from_file_location("owner_decisions_15_16_17", MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OwnerDecisions151617MigrationTest(unittest.TestCase):
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
        self.module = _load_module()

    def _selectable(self, codes):
        with self.db.engine.connect() as conn:
            return dict(
                conn.execute(
                    sa.text(
                        "SELECT code, is_coding_selectable FROM mas_icd10_2019_2 "
                        "WHERE code IN :codes"
                    ).bindparams(sa.bindparam("codes", expanding=True)),
                    {"codes": list(codes)},
                ).all()
            )

    def _mapping_rows(self, scheme_code, classification, codes):
        with self.db.engine.connect() as conn:
            return {
                row.icd_code: (row.node_code, row.match_type, row.mapping_note)
                for row in conn.execute(
                    sa.text(
                        "SELECT m.icd_code, n.node_code, m.match_type, m.mapping_note "
                        "FROM map_icd_cod_buckets m "
                        "JOIN mas_cod_bucket_nodes n ON n.node_id = m.node_id "
                        "JOIN mas_cod_bucket_schemes s ON s.scheme_id = m.scheme_id "
                        "WHERE s.scheme_code = :scheme AND m.icd_classification = :cls "
                        "AND upper(m.icd_code) IN :codes"
                    ).bindparams(sa.bindparam("codes", expanding=True)),
                    {"scheme": scheme_code, "cls": classification, "codes": list(codes)},
                )
            }

    def _repoint_admin(self, classification, icd_code, node_code):
        """An admin edit, the way the bucket editor stamps it."""
        with self.db.engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE map_icd_cod_buckets m SET node_id = n.node_id, match_type = 'manual_override', "
                    "mapping_note = 'Manual override to default COD bucket scheme mapping.' "
                    "FROM mas_cod_bucket_nodes n, mas_cod_bucket_schemes s "
                    "WHERE s.scheme_code = 'WHO_2022_VA_2026' AND m.scheme_id = s.scheme_id "
                    "AND n.scheme_id = s.scheme_id AND n.node_code = :node "
                    "AND m.icd_classification = :cls AND m.icd_code = :code"
                ),
                {"node": node_code, "cls": classification, "code": icd_code},
            )

    def _vocab_rows(self):
        with self.db.engine.connect() as conn:
            return {
                (row.term_normalized, row.icd_classification, row.icd_code): (row.is_active, row.sort_order)
                for row in conn.execute(
                    sa.text(
                        "SELECT term_normalized, icd_classification, icd_code, is_active, sort_order "
                        "FROM mas_icd_search_terms WHERE term_normalized LIKE '%stillbirth%'"
                    )
                )
            }

    def test_decision_15_flips_three_character_v_and_y85_only(self):
        before = self._selectable(["V01", "V10", "V87", "V89", "V90", "Y85"])
        self.assertTrue(all(before.values()))
        alembic_upgrade(revision=REVISION)
        after = self._selectable(["V01", "V10", "V87", "V89", "V90", "Y85"])
        self.assertFalse(after["V01"])
        self.assertFalse(after["V10"])
        self.assertFalse(after["V87"])
        self.assertFalse(after["V89"])
        self.assertFalse(after["Y85"])
        self.assertTrue(after["V90"], "V90-V99 stay selectable")

        alembic_downgrade(revision=PARENT_REVISION)
        reverted = self._selectable(["V01", "V10", "V87", "V89", "V90", "Y85"])
        self.assertEqual(reverted, before)

    def test_decision_16_repoints_icd10_transport_and_keeps_admin_edit(self):
        self._repoint_admin("icd10", "V11", "vas_12_99")
        alembic_upgrade(revision=REVISION)

        after = self._mapping_rows("WHO_2022_VA_2026", "icd10", ["V01", "V10", "V11", "V82", "V83", "V87", "V88", "V89"])
        self.assertEqual(after["V01"][0], "vas_12_02", "V01-V09 stay Other transport")
        self.assertEqual(after["V10"][0], "vas_12_01")
        self.assertEqual(after["V10"][1], "owner_decision")
        self.assertEqual(after["V11"][0], "vas_12_99", "admin edit survives")
        self.assertEqual(after["V82"][0], "vas_12_01")
        self.assertEqual(after["V83"][0], "vas_12_02", "V83-V86 stay Other transport (nontraffic)")
        self.assertEqual(after["V87"][0], "vas_12_01")
        self.assertEqual(after["V88"][0], "vas_12_02")
        self.assertEqual(after["V89"][0], "vas_12_02", "V89 stays Other transport")

        # Rerun is a no-op.
        alembic_stamp(revision=PARENT_REVISION)
        alembic_upgrade(revision=REVISION)
        self.assertEqual(
            self._mapping_rows("WHO_2022_VA_2026", "icd10", ["V01", "V10", "V11", "V82", "V87", "V89"]),
            {k: v for k, v in after.items() if k in ("V01", "V10", "V11", "V82", "V87", "V89")},
        )

        alembic_downgrade(revision=PARENT_REVISION)
        reverted = self._mapping_rows("WHO_2022_VA_2026", "icd10", ["V01", "V10", "V11", "V82", "V87"])
        self.assertEqual(reverted["V10"][0], "vas_12_02")
        self.assertEqual(reverted["V10"][1], "transport_non_road")
        self.assertEqual(reverted["V11"][0], "vas_12_99", "admin edit still survives after downgrade")

    def _reset_icd11_pa_codes_to_pre_decision_17(self, codes):
        """A deployment migrated before the decision-17 CSV regeneration
        still holds the pre-decision (PA-split default) value; a fresh test
        chain seeds the already-regenerated CSV, so simulate that deployment
        state here rather than relying on chain order."""
        with self.db.engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE map_icd_cod_buckets m SET node_id = n.node_id, match_type = 'split', "
                    "mapping_note = 'ICD-11 2026-01 range PA00-PA5Z' "
                    "FROM mas_cod_bucket_nodes n, mas_cod_bucket_schemes s "
                    "WHERE s.scheme_code = 'WHO_2022_VA_2026' AND m.scheme_id = s.scheme_id "
                    "AND n.scheme_id = s.scheme_id AND n.node_code = 'vas_12_02' "
                    "AND m.icd_classification = 'icd11' AND upper(m.icd_code) IN :codes"
                ).bindparams(sa.bindparam("codes", expanding=True)),
                {"codes": list(codes)},
            )

    def test_decision_17_repoints_icd11_pa_codes(self):
        self._reset_icd11_pa_codes_to_pre_decision_17(self.module.ICD11_ROAD_TRAFFIC_CODES)
        alembic_upgrade(revision=REVISION)
        after = self._mapping_rows(
            "WHO_2022_VA_2026", "icd11",
            ["PA20", "PA21", "PA22", "PA29", "PA2A", "PA2E", "PA2Z"],
        )
        self.assertEqual(after["PA20"][0], "vas_12_02", "PA20/PA21 stay Other transport")
        self.assertEqual(after["PA21"][0], "vas_12_02")
        self.assertEqual(after["PA22"][0], "vas_12_01")
        self.assertEqual(after["PA22"][1], "owner_decision")
        self.assertEqual(after["PA29"][0], "vas_12_01")
        self.assertEqual(after["PA2A"][0], "vas_12_02", "PA2A-PA2D stay Other transport")
        self.assertEqual(after["PA2E"][0], "vas_12_01")
        self.assertEqual(after["PA2Z"][0], "vas_12_01")

        alembic_downgrade(revision=PARENT_REVISION)
        reverted = self._mapping_rows("WHO_2022_VA_2026", "icd11", ["PA22", "PA2Z"])
        self.assertEqual(reverted["PA22"][0], "vas_12_02")
        self.assertEqual(reverted["PA22"][1], "split")

    def _reset_vocab_to_pre_migration_state(self):
        """A deployment migrated before this migration's seed CSV edit still
        holds the bare (stillbirth, icd11, KD3B) row and none of the new
        terms; a fresh test chain seeds the already-edited CSV earlier in
        the chain (c5a8d2e7f1b4 reads it live), so simulate that deployment
        state here rather than relying on chain order."""
        import uuid
        from datetime import UTC, datetime

        with self.db.engine.begin() as conn:
            conn.execute(
                sa.text(
                    "DELETE FROM mas_icd_search_terms WHERE term_normalized LIKE '%stillbirth%' "
                    "AND NOT (term_normalized = 'stillbirth' AND icd_code = 'P95')"
                )
            )
            exists = conn.execute(
                sa.text(
                    "SELECT 1 FROM mas_icd_search_terms WHERE term_normalized = 'stillbirth' "
                    "AND icd_classification = 'icd11' AND icd_code = 'KD3B'"
                )
            ).first()
            if not exists:
                now = datetime.now(UTC)
                conn.execute(
                    sa.text(
                        "INSERT INTO mas_icd_search_terms (term_id, term, term_normalized, "
                        "icd_classification, icd_code, source, note, sort_order, is_active, "
                        "created_at, updated_at) VALUES (:id, 'stillbirth', 'stillbirth', 'icd11', "
                        "'KD3B', 'seed_used_cod', 'common term', 100, true, :now, :now)"
                    ),
                    {"id": str(uuid.uuid4()), "now": now},
                )

    def test_stillbirth_vocabulary_inserted_and_retired_key_deactivated(self):
        self._reset_vocab_to_pre_migration_state()
        alembic_upgrade(revision=REVISION)
        rows = self._vocab_rows()
        self.assertEqual(rows[("stillbirth", "icd11", "KD3B.1")], (True, 1))
        self.assertEqual(rows[("stillbirth", "icd11", "KD3B.0")], (True, 2))
        self.assertEqual(rows[("fresh stillbirth", "icd10", "P95")][0], True)
        self.assertEqual(rows[("fresh stillbirth", "icd11", "KD3B.1")][0], True)
        self.assertEqual(rows[("intrapartum stillbirth", "icd11", "KD3B.1")][0], True)
        self.assertEqual(rows[("macerated stillbirth", "icd10", "P95")][0], True)
        self.assertEqual(rows[("macerated stillbirth", "icd11", "KD3B.0")][0], True)
        self.assertEqual(rows[("antepartum stillbirth", "icd11", "KD3B.0")][0], True)
        # The pre-existing (stillbirth, icd11, KD3B) seed row is deactivated.
        self.assertEqual(rows[("stillbirth", "icd11", "KD3B")][0], False)

        alembic_stamp(revision=PARENT_REVISION)
        alembic_upgrade(revision=REVISION)
        self.assertEqual(self._vocab_rows(), rows, "rerun is a no-op")

        alembic_downgrade(revision=PARENT_REVISION)
        reverted = self._vocab_rows()
        self.assertEqual(reverted[("stillbirth", "icd11", "KD3B")][0], True, "reactivated")
        self.assertNotIn(("stillbirth", "icd11", "KD3B.1"), reverted)
        self.assertNotIn(("macerated stillbirth", "icd10", "P95"), reverted)


class OverridesMatchMigrationDecision16Test(unittest.TestCase):
    """The reset layer and the migration must say the same thing for decision 16."""

    def test_overrides_csv_decision_16_rows_equal_the_migration(self):
        module = _load_module()
        from_migration = {
            code: (module.ICD10_NEW_NODE, "owner_decision", module.ICD10_NEW_NOTE)
            for code in module.ICD10_ROAD_TRAFFIC_CODES
        }
        with ICD10_OVERRIDES_CSV.open(newline="", encoding="utf-8") as handle:
            from_csv = {
                row["icd_code"]: (row["node_code"], row["match_type"], row["mapping_note"])
                for row in csv.DictReader(handle)
                if row["mapping_note"].startswith("Owner decision 16")
            }
        self.assertEqual(len(from_csv), 74)
        self.assertEqual(from_csv, from_migration)

    def test_owner_decisions_csv_decision_17_rows_cover_the_migration_codes(self):
        module = _load_module()
        with ICD11_DECISIONS_CSV.open(newline="", encoding="utf-8") as handle:
            decision_17_tokens = {row["code"] for row in csv.DictReader(handle) if row["decision"] == "17"}
        self.assertEqual(decision_17_tokens, {"PA22-PA29", "PA2E-PA2F", "PA2Y-PA2Z"})
        self.assertEqual(len(module.ICD11_ROAD_TRAFFIC_CODES), 12)
