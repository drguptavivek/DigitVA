"""Tests for migration d3a9c5e1f7b2 (owner decision 20, ICD-11 crosswalk
disagreements for WHO_2022_VA_2026).

Same throwaway-database shape as test_migrate_owner_decisions_15_16_17.py.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_migrate_owner_decision_20.py -q
"""
import csv
import importlib.util
import unittest
from pathlib import Path

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_migration_owner_decision_20"
PARENT_REVISION = "b1f4d8a6c9e2"
REVISION = "d3a9c5e1f7b2"
REPO = Path(__file__).resolve().parents[2]
MIGRATION_FILE = (
    REPO / "migrations" / "versions"
    / "d3a9c5e1f7b2_owner_decision_20_icd11_crosswalk_disagreements.py"
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
    spec = importlib.util.spec_from_file_location("owner_decision_20", MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OwnerDecision20MigrationTest(unittest.TestCase):
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

    def _rows(self, codes):
        with self.db.engine.connect() as conn:
            return {
                row.icd_code: (row.node_code, row.match_type, row.mapping_note)
                for row in conn.execute(
                    sa.text(
                        "SELECT m.icd_code, n.node_code, m.match_type, m.mapping_note "
                        "FROM map_icd_cod_buckets m "
                        "JOIN mas_cod_bucket_nodes n ON n.node_id = m.node_id "
                        "JOIN mas_cod_bucket_schemes s ON s.scheme_id = m.scheme_id "
                        "WHERE s.scheme_code = 'WHO_2022_VA_2026' AND m.icd_classification = 'icd11' "
                        "AND m.icd_code IN :codes"
                    ).bindparams(sa.bindparam("codes", expanding=True)),
                    {"codes": list(codes)},
                )
            }

    def _set(self, code, node_code, match_type, note):
        with self.db.engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE map_icd_cod_buckets m SET node_id = n.node_id, match_type = :mt, "
                    "mapping_note = :note FROM mas_cod_bucket_nodes n, mas_cod_bucket_schemes s "
                    "WHERE s.scheme_code = 'WHO_2022_VA_2026' AND m.scheme_id = s.scheme_id "
                    "AND n.scheme_id = s.scheme_id AND n.node_code = :node "
                    "AND m.icd_classification = 'icd11' AND m.icd_code = :code"
                ),
                {"node": node_code, "mt": match_type, "note": note, "code": code},
            )

    def _to_generated_state(self):
        """A deployment migrated before the CSV regeneration holds the old
        generated value; the fresh chain seeds the regenerated CSV."""
        for code, (old_node, old_match, old_note, _n, _t) in self.module.CHANGES.items():
            self._set(code, old_node, old_match, old_note)

    def test_moves_seven_stamps_four_and_downgrade_restores(self):
        self._to_generated_state()
        untouched = ["PA22", "PA2A", "PA09"]
        before_untouched = self._rows(untouched)
        self.assertEqual(len(before_untouched), len(untouched))

        alembic_upgrade(revision=REVISION)
        after = self._rows(self.module.CHANGES)
        self.assertEqual(len(after), 11)
        moved = 0
        for code, (old_node, _m, _n, new_node, new_note) in self.module.CHANGES.items():
            self.assertEqual(after[code], (new_node, "owner_decision", new_note))
            moved += old_node != new_node
        self.assertEqual(moved, 7)
        self.assertEqual(self._rows(untouched), before_untouched)

        alembic_downgrade(revision=PARENT_REVISION)
        for code, (old_node, old_match, old_note, _n, _t) in self.module.CHANGES.items():
            self.assertEqual(self._rows([code])[code], (old_node, old_match, old_note))

    def test_admin_edit_survives_upgrade_and_rerun_is_noop(self):
        self._to_generated_state()
        self._set("PA92", "vas_12_99", "manual_override", "admin")
        alembic_upgrade(revision=REVISION)
        self.assertEqual(self._rows(["PA92"])["PA92"][:2], ("vas_12_99", "manual_override"))
        self.assertEqual(self._rows(["PA08"])["PA08"][0], "vas_12_02")
        self.assertEqual(self._rows(["1C8C"])["1C8C"][1], "owner_decision")

        before = self._rows(self.module.CHANGES)
        alembic_downgrade(revision=PARENT_REVISION)
        alembic_upgrade(revision=REVISION)
        self.assertEqual(self._rows(self.module.CHANGES), before)


class DecisionsCsvMatchesMigrationTest(unittest.TestCase):
    def test_decision_20_rows_equal_the_migration(self):
        module = _load_module()
        with ICD11_DECISIONS_CSV.open(newline="", encoding="utf-8") as handle:
            from_csv = {
                row["code"]: (row["node_code"], row["note"])
                for row in csv.DictReader(handle)
                if row["decision"] == "20"
            }
        self.assertEqual(len(from_csv), 11)
        self.assertEqual(len(module.CHANGES), 11)
        for code, (_o, _m, _n, new_node, new_note) in module.CHANGES.items():
            self.assertEqual(from_csv.pop(code), (new_node, new_note.removeprefix(
                "Owner decision 20 (2026-09-29): ")))
        self.assertEqual(from_csv, {})
